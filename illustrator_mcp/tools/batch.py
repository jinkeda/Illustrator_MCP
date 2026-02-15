"""
Chunked multi-create for large Geometry IR payloads.

This module provides Python-side chunking for `element_create_multi`,
leveraging its built-in `offset`/`limit` pagination. Each chunk is a
separate `executeOpBatch` call, so the UI yields between chunks.

Adaptive chunk sizing: measures wall-clock per chunk, halves if >5s,
doubles if <1s (clamped to [50, 2000]).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from illustrator_mcp.proxy_client import execute_script_with_context

logger = logging.getLogger(__name__)

# Adaptive chunk sizing bounds
MIN_CHUNK_SIZE = 50
MAX_CHUNK_SIZE = 2000
SLOW_THRESHOLD_MS = 5000
FAST_THRESHOLD_MS = 1000


@dataclass
class ChunkResult:
    """Result of a single chunk execution."""
    offset: int
    limit: int
    ok: bool
    created: int = 0
    skipped: int = 0
    ms: float = 0.0
    error: Optional[str] = None
    ids: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


async def chunked_create_multi(
    geometry_ir: Dict[str, Any],
    chunk_size: int = 500,
    layer: Optional[str] = None,
    name: Optional[str] = None,
    fill: Optional[Dict] = None,
    stroke: Optional[Dict] = None,
    styles: Optional[List[Dict]] = None,
    style_scalars: Optional[List[float]] = None,
    palette: Optional[Dict] = None,
    timeout_per_chunk: float = 30.0,
    includes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create multi-path geometry in chunks using offset/limit pagination.

    Dispatches sequential `element_create_multi` calls with increasing
    offsets. Aggregates IDs, counts, and per-chunk timing into a single
    result envelope.

    Args:
        geometry_ir: Complete Geometry IR dict with ir="multi", paths=[...]
        chunk_size: Initial items per chunk (adaptively adjusted)
        layer: Target layer name
        name: Base name for items
        fill: Default fill color dict
        stroke: Default stroke color dict
        styles: Per-path explicit style array (length must match total paths)
        style_scalars: Per-path scalar array for palette interpolation
        palette: Color palette for scalar interpolation
        timeout_per_chunk: Timeout in seconds per chunk execution
        includes: Library includes for execute_script_with_context

    Returns:
        Aggregated result dict with keys:
          ok, ids, created, skipped, chunks, warnings

    Raises:
        ValueError: If styles/style_scalars length doesn't match path count
    """
    paths = geometry_ir.get("paths", [])
    total = len(paths)

    if total == 0:
        return {
            "ok": True,
            "ids": [],
            "created": 0,
            "skipped": 0,
            "chunks": [],
            "warnings": ["No paths in geometry IR"],
        }

    # Validate per-path array lengths
    if styles is not None and len(styles) != total:
        raise ValueError(
            f"styles length ({len(styles)}) != path count ({total})"
        )
    if style_scalars is not None and len(style_scalars) != total:
        raise ValueError(
            f"styleScalars length ({len(style_scalars)}) != path count ({total})"
        )

    # Build common params (shared across all chunks)
    common: Dict[str, Any] = {}
    if layer is not None:
        common["layer"] = layer
    if name is not None:
        common["name"] = name
    if fill is not None:
        common["fill"] = fill
    if stroke is not None:
        common["stroke"] = stroke
    if palette is not None:
        common["palette"] = palette

    # Resolve includes (default: SOC framework)
    includes = includes or ["task_executor"]

    # Aggregation accumulators
    all_ids: List[str] = []
    all_warnings: List[str] = []
    chunks: List[Dict[str, Any]] = []
    total_created = 0
    total_skipped = 0
    all_ok = True
    current_chunk_size = min(chunk_size, MAX_CHUNK_SIZE)
    offset = 0

    while offset < total:
        limit = min(current_chunk_size, total - offset)

        # Build per-chunk params
        chunk_params: Dict[str, Any] = {
            "geometry": geometry_ir,
            "offset": offset,
            "limit": limit,
            **common,
        }

        # Slice per-path arrays for this chunk
        if styles is not None:
            chunk_params["styles"] = styles[offset : offset + limit]
        if style_scalars is not None:
            chunk_params["styleScalars"] = style_scalars[offset : offset + limit]

        # Build SOC batch call
        ops = [{"task": "element_create_multi", "params": chunk_params}]
        script = f"executeOpBatch({json.dumps(ops)}, {{\"summaryOnly\": true}})"

        # Execute
        start_ms = time.monotonic() * 1000
        response = await execute_script_with_context(
            script=script,
            command_type="chunked_create_multi",
            params={"offset": offset, "limit": limit, "total": total},
            timeout=timeout_per_chunk,
            includes=includes,
        )
        elapsed_ms = time.monotonic() * 1000 - start_ms

        # Parse result
        chunk_result = ChunkResult(offset=offset, limit=limit, ok=False, ms=elapsed_ms)

        if response.get("error"):
            chunk_result.error = str(response["error"])
            all_ok = False
        else:
            raw = response.get("result", response)
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except json.JSONDecodeError:
                    pass

            if isinstance(raw, dict):
                chunk_result.ok = raw.get("ok", False)
                chunk_result.ids = raw.get("createdIds", [])
                chunk_result.created = raw.get("stats", {}).get("passed", 0)

                # Extract data from individual ops if available
                ops_data = raw.get("ops", [])
                if ops_data and isinstance(ops_data, list):
                    op = ops_data[0] if ops_data else {}
                    data = op.get("data", {})
                    chunk_result.created = data.get("created", chunk_result.created)
                    chunk_result.skipped = data.get("skipped", 0)
                    chunk_result.ids = data.get("ids", chunk_result.ids)
                    chunk_result.warnings = data.get("warnings", [])

                if not chunk_result.ok:
                    all_ok = False

        # Accumulate
        all_ids.extend(chunk_result.ids)
        all_warnings.extend(chunk_result.warnings)
        total_created += chunk_result.created
        total_skipped += chunk_result.skipped

        chunks.append({
            "offset": chunk_result.offset,
            "limit": chunk_result.limit,
            "ok": chunk_result.ok,
            "created": chunk_result.created,
            "skipped": chunk_result.skipped,
            "ms": round(chunk_result.ms, 1),
            **({"error": chunk_result.error} if chunk_result.error else {}),
        })

        logger.info(
            f"Chunk {len(chunks)}: offset={offset}, limit={limit}, "
            f"created={chunk_result.created}, ms={elapsed_ms:.0f}"
        )

        # On chunk failure, return partial result
        if chunk_result.error:
            break

        offset += limit

        # Adaptive chunk sizing
        if elapsed_ms > SLOW_THRESHOLD_MS and current_chunk_size > MIN_CHUNK_SIZE:
            current_chunk_size = max(MIN_CHUNK_SIZE, current_chunk_size // 2)
            logger.info(f"Chunk too slow ({elapsed_ms:.0f}ms), reducing to {current_chunk_size}")
        elif elapsed_ms < FAST_THRESHOLD_MS and current_chunk_size < MAX_CHUNK_SIZE:
            current_chunk_size = min(MAX_CHUNK_SIZE, current_chunk_size * 2)
            logger.info(f"Chunk fast ({elapsed_ms:.0f}ms), increasing to {current_chunk_size}")

    return {
        "ok": all_ok,
        "ids": all_ids,
        "created": total_created,
        "skipped": total_skipped,
        "chunks": chunks,
        "warnings": all_warnings,
    }
