"""
test_import_svg.py — Unit tests for the path_import_svg tool.

Pure Python tests (no Illustrator needed).
Tests focus on the parsing/IR conversion layer — the JSX execution
is not tested here (requires live Illustrator).

Run: python -m pytest tests/test_import_svg.py -v
"""

import json
import pytest
from illustrator_mcp.svgd import parse_svg_d
from illustrator_mcp.tools.import_svg import (
    _ir_points_to_draw_spec,
    _build_appearance,
    PathImportSvgInput,
)
from illustrator_mcp.tools._models import ColorRGB, StrokeSpec


# ── IR-to-spec conversion tests ───────────────────────────────────────


class TestIRToDrawSpec:
    def test_simple_line_points(self):
        """IR from lineTo → anchors only, no left/right."""
        ir = parse_svg_d("M 0,0 L 100,0 L 100,100 Z")
        spec = _ir_points_to_draw_spec(ir)
        assert len(spec) == 3
        assert spec[0]["anchor"] == [0, 0]
        assert spec[1]["anchor"] == [100, 0]
        assert "left" not in spec[0]
        assert "right" not in spec[0]

    def test_cubic_bezier_points(self):
        """IR from cubic → anchors with left/right handles."""
        ir = parse_svg_d("M 0,0 C 25,50 75,50 100,0")
        spec = _ir_points_to_draw_spec(ir)
        assert len(spec) == 2
        # First point has out-handle (right)
        assert "right" in spec[0]
        assert spec[0]["right"] == [25, 50]
        # Second point has in-handle (left)
        assert "left" in spec[1]
        assert spec[1]["left"] == [75, 50]

    def test_arc_produces_handles(self):
        """IR from arc → anchors with handles (arc→cubic)."""
        ir = parse_svg_d("M 0,0 A 50,50 0 1,1 100,0")
        spec = _ir_points_to_draw_spec(ir)
        assert len(spec) > 1
        # Should have handles from cubic approximation
        has_handles = any("left" in s or "right" in s for s in spec)
        assert has_handles

    def test_multi_subpath_conversion(self):
        """Multi-subpath IR → separate point specs per subpath."""
        ir = parse_svg_d("M 0,0 L 10,0 L 10,10 Z M 20,20 L 30,20 L 30,30 Z")
        assert ir["ir"] == "multi"
        for sp in ir["subpaths"]:
            spec = _ir_points_to_draw_spec(sp)
            assert len(spec) == 3
            for pt in spec:
                assert "anchor" in pt


# ── Input validation tests ────────────────────────────────────────────


class TestInputValidation:
    def test_minimal_input(self):
        """d field is required and sufficient."""
        inp = PathImportSvgInput(d="M 0,0 L 100,0")
        assert inp.d == "M 0,0 L 100,0"
        assert inp.layer is None
        assert inp.tag is None
        assert inp.name is None
        assert inp.fill is None
        assert inp.stroke is None
        assert inp.id is None

    def test_full_input(self):
        """All optional fields can be set."""
        inp = PathImportSvgInput(
            d="M 0,0 L 100,0 Z",
            layer="Icons",
            tag="arrow",
            name="arrow_path",
            fill=ColorRGB(r=255, g=0, b=0),
            stroke=StrokeSpec(r=0, g=0, b=0, width=2.0),
            id="my_arrow",
        )
        assert inp.layer == "Icons"
        assert inp.tag == "arrow"
        assert inp.name == "arrow_path"
        assert inp.fill.r == 255
        assert inp.stroke.width == 2.0
        assert inp.id == "my_arrow"


# ── Fill/stroke/id appearance tests ───────────────────────────────────


class TestAppearanceSpec:
    """Tests for _build_appearance and spec wiring."""

    def test_fill_color_in_appearance(self):
        """ColorRGB fill → spec.appearance.fill = {r, g, b}."""
        params = PathImportSvgInput(
            d="M 0,0 L 100,0 Z",
            fill=ColorRGB(r=255, g=0, b=0),
        )
        app = _build_appearance(params)
        assert app is not None
        assert app["fill"] == {"r": 255, "g": 0, "b": 0}
        assert "noFill" not in app

    def test_fill_false_produces_nofill(self):
        """fill=False → spec.appearance.noFill = True."""
        params = PathImportSvgInput(d="M 0,0 L 100,0 Z", fill=False)
        app = _build_appearance(params)
        assert app is not None
        assert app["noFill"] is True
        assert "fill" not in app

    def test_stroke_color_in_appearance(self):
        """StrokeSpec → spec.appearance.stroke = {r, g, b, width}."""
        params = PathImportSvgInput(
            d="M 0,0 L 100,0 Z",
            stroke=StrokeSpec(r=0, g=128, b=255, width=3.0),
        )
        app = _build_appearance(params)
        assert app is not None
        assert app["stroke"] == {"r": 0, "g": 128, "b": 255, "width": 3.0}
        assert "noStroke" not in app

    def test_stroke_false_produces_nostroke(self):
        """stroke=False → spec.appearance.noStroke = True."""
        params = PathImportSvgInput(d="M 0,0 L 100,0 Z", stroke=False)
        app = _build_appearance(params)
        assert app is not None
        assert app["noStroke"] is True
        assert "stroke" not in app

    def test_stroke_width_default_omitted(self):
        """StrokeSpec with no width → stroke dict has no width key."""
        params = PathImportSvgInput(
            d="M 0,0 L 100,0 Z",
            stroke=StrokeSpec(r=0, g=0, b=0),
        )
        app = _build_appearance(params)
        assert app is not None
        assert "width" not in app["stroke"]
        assert app["stroke"] == {"r": 0, "g": 0, "b": 0}

    def test_fill_none_does_not_emit_appearance(self):
        """None fill + None stroke → no appearance key at all."""
        params = PathImportSvgInput(d="M 0,0 L 100,0 Z")
        app = _build_appearance(params)
        assert app is None

    def test_fill_and_stroke_together(self):
        """Both fill and stroke → both in appearance."""
        params = PathImportSvgInput(
            d="M 0,0 L 100,0 Z",
            fill=ColorRGB(r=255, g=255, b=0),
            stroke=StrokeSpec(r=0, g=0, b=0, width=1.5),
        )
        app = _build_appearance(params)
        assert app["fill"] == {"r": 255, "g": 255, "b": 0}
        assert app["stroke"] == {"r": 0, "g": 0, "b": 0, "width": 1.5}

    def test_fill_false_stroke_color(self):
        """fill=False + stroke=color → both noFill and stroke."""
        params = PathImportSvgInput(
            d="M 0,0 L 100,0 Z",
            fill=False,
            stroke=StrokeSpec(r=0, g=0, b=0),
        )
        app = _build_appearance(params)
        assert app["noFill"] is True
        assert app["stroke"] == {"r": 0, "g": 0, "b": 0}

    def test_color_validation_rejects_garbage(self):
        """Out-of-range values reject at validation time."""
        with pytest.raises(Exception):
            ColorRGB(r=300, g=0, b=0)
        with pytest.raises(Exception):
            ColorRGB(r=-1, g=0, b=0)
        with pytest.raises(Exception):
            StrokeSpec(r=0, g=0, b=0, width=-1.0)


class TestIdSpec:
    """Tests for user-supplied ID wiring."""

    def test_id_in_input(self):
        """id param is stored on the input model."""
        inp = PathImportSvgInput(d="M 0,0 L 100,0 Z", id="triangle")
        assert inp.id == "triangle"

    @pytest.mark.asyncio
    async def test_id_roundtrip_in_result(self):
        """Returned ID matches user-supplied id."""
        from unittest.mock import AsyncMock, patch, MagicMock
        import illustrator_mcp.tools.execute as ex_mod

        mock_draw = json.dumps({"ok": True, "uuid": "my_shape", "bounds": [0, 0, 100, 50]})

        with patch.object(ex_mod, "_counter", MagicMock()):
            from illustrator_mcp.tools.import_svg import illustrator_path_import_svg
            params = PathImportSvgInput(d="M 0,0 L 100,0 L 100,50 Z", id="my_shape")
            with patch(
                "illustrator_mcp.tools.import_svg.execute_script_with_context",
                new_callable=AsyncMock,
                return_value={"result": mock_draw},
            ) as mock_exec:
                result = json.loads(await illustrator_path_import_svg(params))

        assert result["ok"] is True
        assert result["result"]["uuid"] == "my_shape"
        # Verify spec.id was passed in the script
        call_args = mock_exec.call_args
        script_arg = call_args.kwargs.get("script", call_args[1].get("script", ""))
        assert '"id": "my_shape"' in script_arg or '"id":"my_shape"' in script_arg


# ── Error code passthrough tests (H7) ─────────────────────────────────


class TestErrorCodePassthrough:
    """Tests that svgd.py safety limit errors have correct error codes."""

    def test_d_too_long_error_code(self):
        """E_D_TOO_LONG code is present in error message."""
        d = "M 0,0 " + "L 1,1 " * 20000
        with pytest.raises(ValueError) as exc_info:
            parse_svg_d(d)
        assert "E_D_TOO_LONG" in str(exc_info.value)

    def test_coord_overflow_error_code(self):
        """E_COORD_OVERFLOW code is present in error message."""
        d = "M 0,0 L 200000,0"
        with pytest.raises(ValueError) as exc_info:
            parse_svg_d(d)
        assert "E_COORD_OVERFLOW" in str(exc_info.value)


# ── Response shape tests (H5) ─────────────────────────────────────────


class TestResponseShape:
    """Tests for the expected H5 response payload structure.

    Since we can't actually call Illustrator, these verify the
    parsing/IR side only. The full response shape is tested in
    live integration tests.
    """

    def test_ir_determinism(self):
        """Same d string → same IR output (deterministic)."""
        d = "M 10,20 C 30,40 50,60 70,80 Z"
        ir1 = parse_svg_d(d)
        ir2 = parse_svg_d(d)
        assert ir1 == ir2


# ── Envelope integration tests ────────────────────────────────────────


class TestEnvelopeIntegration:
    """Tests that import_svg returns standardized format_envelope responses.

    Mocks execute_script_with_context to avoid needing Illustrator.
    """

    @pytest.fixture(autouse=True)
    def _patch_counter(self, monkeypatch):
        """Stub out mutation counter to avoid import-order issues."""
        from unittest.mock import MagicMock
        import illustrator_mcp.tools.execute as ex_mod
        monkeypatch.setattr(ex_mod, "_counter", MagicMock())

    def _parse(self, json_str: str) -> dict:
        return json.loads(json_str)

    @pytest.mark.asyncio
    async def test_parse_error_envelope(self):
        """SVG parse ValueError → {ok:false, error:{code:'SVG001',...}}."""
        from illustrator_mcp.tools.import_svg import illustrator_path_import_svg, PathImportSvgInput
        # d string exceeding MAX_D_LENGTH triggers E_D_TOO_LONG
        d = "M 0,0 " + "L 1,1 " * 20000
        params = PathImportSvgInput(d=d)
        result = self._parse(await illustrator_path_import_svg(params))
        assert result["ok"] is False
        assert result["error"] is not None
        assert result["error"]["code"] == "SVG001"
        assert "SVG path data too long" in result["error"]["message"]
        assert result["diagnostics"]["tool"] == "path_import_svg"

    @pytest.mark.asyncio
    async def test_execution_error_envelope(self):
        """execute_script_with_context raises → {ok:false, error:{...}}."""
        from unittest.mock import AsyncMock, patch
        from illustrator_mcp.tools.import_svg import illustrator_path_import_svg, PathImportSvgInput
        params = PathImportSvgInput(d="M 0,0 L 100,0")
        with patch(
            "illustrator_mcp.tools.import_svg.execute_script_with_context",
            new_callable=AsyncMock,
            side_effect=ConnectionError("WebSocket gone"),
        ):
            result = self._parse(await illustrator_path_import_svg(params))
        assert result["ok"] is False
        assert result["error"] is not None
        assert "WebSocket gone" in result["error"]["message"]

    @pytest.mark.asyncio
    async def test_success_envelope(self):
        """Successful draw → {ok:true, result:{...}, warnings:[...]}."""
        from unittest.mock import AsyncMock, patch
        from illustrator_mcp.tools.import_svg import illustrator_path_import_svg, PathImportSvgInput
        mock_draw = json.dumps({"ok": True, "uuid": "abc123", "bounds": [0, 0, 100, 50]})
        params = PathImportSvgInput(d="M 0,0 L 100,0 L 100,50 Z")
        with patch(
            "illustrator_mcp.tools.import_svg.execute_script_with_context",
            new_callable=AsyncMock,
            return_value={"result": mock_draw},
        ):
            result = self._parse(await illustrator_path_import_svg(params))
        assert result["ok"] is True
        assert result["error"] is None
        assert "warnings" in result
        assert result["diagnostics"]["tool"] == "path_import_svg"
        # Domain data is unwrapped into result
        assert result["result"]["uuid"] == "abc123"
        assert result["result"]["bounds"] == [0, 0, 100, 50]

    @pytest.mark.asyncio
    async def test_draw_error_envelope(self):
        """drawPathPoints returns ok:false → {ok:false, error:{...}}."""
        from unittest.mock import AsyncMock, patch
        from illustrator_mcp.tools.import_svg import illustrator_path_import_svg, PathImportSvgInput
        mock_draw = json.dumps({"ok": False, "error": "Path creation failed"})
        params = PathImportSvgInput(d="M 0,0 L 100,0")
        with patch(
            "illustrator_mcp.tools.import_svg.execute_script_with_context",
            new_callable=AsyncMock,
            return_value={"result": mock_draw},
        ):
            result = self._parse(await illustrator_path_import_svg(params))
        assert result["ok"] is False
        assert result["error"] is not None
        assert "Path creation failed" in result["error"]["message"]


class TestFormatEnvelopePassthrough:
    """Lock test: format_envelope passes dict result through unchanged (C)."""

    def test_dict_result_passthrough(self):
        """format_envelope({"result": {"x": 1}}) → ok:true, result:{"x": 1}."""
        from illustrator_mcp.proxy_client import format_envelope
        env = json.loads(format_envelope({"result": {"x": 1, "imported": True}}))
        assert env["ok"] is True
        assert env["result"] == {"x": 1, "imported": True}
        assert env["error"] is None

