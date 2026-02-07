"""
Chunking utilities for large operation batches.

Provides automatic chunking of op arrays to prevent:
- Memory issues in ExtendScript
- WebSocket message size limits
- Execution timeouts
"""

from typing import List, Dict, Any, Iterator, Optional
from dataclasses import dataclass, field


@dataclass
class ChunkConfig:
    """Configuration for operation chunking."""
    
    # Maximum ops per chunk (default: 100)
    max_ops_per_chunk: int = 100
    
    # Maximum create ops per chunk (creates are heavier)
    max_create_ops_per_chunk: int = 50
    
    # Whether to include summaryOnly for each chunk
    use_summary_only: bool = True
    
    # Stop on first chunk failure
    strict: bool = True


DEFAULT_CONFIG = ChunkConfig()


def should_chunk(ops: List[Dict], config: ChunkConfig = None) -> bool:
    """
    Determine if ops should be chunked.
    
    Args:
        ops: List of operations
        config: Chunk configuration
        
    Returns:
        True if chunking recommended
    """
    config = config or DEFAULT_CONFIG
    
    if len(ops) > config.max_ops_per_chunk:
        return True
    
    # Count create ops
    create_count = sum(
        1 for op in ops 
        if op.get("task", "").startswith("element_create") or
           op.get("task", "").startswith("text_create")
    )
    
    if create_count > config.max_create_ops_per_chunk:
        return True
    
    return False


def chunk_ops(
    ops: List[Dict], 
    config: ChunkConfig = None
) -> Iterator[List[Dict]]:
    """
    Split operations into chunks, respecting dependencies.
    
    Current strategy: Simple sequential chunking.
    Future: Could analyze target IDs to ensure create ops
    come before their dependent modify ops.
    
    Args:
        ops: List of operations
        config: Chunk configuration
        
    Yields:
        Chunks of operations
    """
    config = config or DEFAULT_CONFIG
    
    chunk = []
    creates_in_chunk = 0
    
    for op in ops:
        is_create = (
            op.get("task", "").startswith("element_create") or
            op.get("task", "").startswith("text_create")
        )
        
        # Check if we need to start a new chunk
        should_split = (
            len(chunk) >= config.max_ops_per_chunk or
            (is_create and creates_in_chunk >= config.max_create_ops_per_chunk)
        )
        
        if should_split and chunk:
            yield chunk
            chunk = []
            creates_in_chunk = 0
        
        chunk.append(op)
        if is_create:
            creates_in_chunk += 1
    
    # Yield final chunk
    if chunk:
        yield chunk


def merge_chunk_results(
    results: List[Dict[str, Any]], 
    created_ids: List[str]
) -> Dict[str, Any]:
    """
    Merge multiple chunk results into a single response.
    
    Args:
        results: List of chunk results
        created_ids: Accumulated created IDs from all chunks
        
    Returns:
        Merged result dictionary
    """
    if not results:
        return {
            "ok": True,
            "stats": {"total": 0, "executed": 0, "passed": 0, "failed": 0},
            "createdIds": [],
            "chunks": 0
        }
    
    # Aggregate stats
    total_stats = {
        "total": 0,
        "executed": 0,
        "passed": 0,
        "failed": 0
    }
    
    total_ms = 0.0
    all_ok = True
    all_errors = []
    all_warnings = []
    
    for i, result in enumerate(results):
        stats = result.get("stats", {})
        total_stats["total"] += stats.get("total", 0)
        total_stats["executed"] += stats.get("executed", 0)
        total_stats["passed"] += stats.get("passed", 0)
        total_stats["failed"] += stats.get("failed", 0)
        
        timing = result.get("timing", {})
        total_ms += timing.get("total_ms", 0)
        
        if not result.get("ok", True):
            all_ok = False
        
        # Collect errors with chunk index
        for err in result.get("errors", []):
            if isinstance(err, dict):
                err["chunk"] = i
            all_errors.append(err)
        
        # Collect warnings
        all_warnings.extend(result.get("warnings", []))
    
    return {
        "ok": all_ok,
        "chunks": len(results),
        "stats": total_stats,
        "timing": {"total_ms": total_ms},
        "createdIds": created_ids,
        "errors": all_errors if all_errors else None,
        "warnings": all_warnings if all_warnings else None
    }


def estimate_chunk_count(ops: List[Dict], config: ChunkConfig = None) -> int:
    """
    Estimate how many chunks will be created.
    
    Args:
        ops: List of operations
        config: Chunk configuration
        
    Returns:
        Estimated chunk count
    """
    config = config or DEFAULT_CONFIG
    
    if not ops:
        return 0
    
    return max(1, (len(ops) + config.max_ops_per_chunk - 1) // config.max_ops_per_chunk)
