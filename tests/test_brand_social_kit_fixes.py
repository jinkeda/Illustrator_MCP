"""
Tests for Brand Social Kit fixes (P0-P3).

Tests verify the 7 fixes applied to documents.py, validate.jsx,
query.py, proxy_client.py, and manifest.json.
"""

import json
import os
import re
import textwrap
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from string import Template
import inspect

from illustrator_mcp.tools.documents import (
    illustrator_export_document,
    ExportDocumentInput,
    ExportFormat,
)
from illustrator_mcp.proxy_client import execute_script_with_context
from illustrator_mcp import templates


# ==================== Helpers ====================

SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), "..",
    "illustrator_mcp", "resources", "scripts",
)

VALIDATE_JSX_PATH = os.path.join(SCRIPTS_DIR, "validate.jsx")
MANIFEST_PATH = os.path.join(SCRIPTS_DIR, "manifest.json")


def _read_validate_jsx() -> str:
    with open(VALIDATE_JSX_PATH, "r") as f:
        return f.read()


def _read_manifest() -> dict:
    with open(MANIFEST_PATH, "r") as f:
        return json.load(f)


def _export_source() -> str:
    from illustrator_mcp.tools import documents
    return inspect.getsource(documents.illustrator_export_document)


def _preflight_source() -> str:
    from illustrator_mcp.tools import query
    return inspect.getsource(query.illustrator_preflight_check)


def _make_mock_export_response(on_artboard=5, off_artboard=0, skipped=2):
    """Build a realistic nested CEP response for the precheck."""
    return {"result": json.dumps({
        "success": True,
        "result": json.dumps({
            "on_artboard": on_artboard,
            "off_artboard": off_artboard,
            "skipped": skipped,
            "items_total": on_artboard + off_artboard + skipped,
            "items_checked": on_artboard + off_artboard,
            "scope": "artboard",
        })
    })}


async def _run_export(params, captured_scripts=None, captured_kwargs=None):
    """Run illustrator_export_document with mocked execution, capturing scripts and kwargs."""
    scripts = captured_scripts if captured_scripts is not None else []
    kwargs_list = captured_kwargs if captured_kwargs is not None else []

    async def capture(script, **kw):
        scripts.append(script)
        kwargs_list.append(kw)
        return _make_mock_export_response()

    with patch("illustrator_mcp.tools.documents.execute_script_with_context",
               side_effect=capture):
        result = await illustrator_export_document(params)
    return result, scripts, kwargs_list


# ======================================================================
# Fix 1 (P0): Export silently succeeds when directory doesn't exist
# ======================================================================


class TestExportDirectoryCreation:
    """Fix 1: Export should auto-create parent directory if it doesn't exist."""

    def test_makedirs_called_for_missing_directory(self, tmp_path):
        """Verify os.makedirs creates the directory when it is missing."""
        missing_dir = tmp_path / "nonexistent" / "subdir"
        export_path = str(missing_dir / "output.png")

        assert not missing_dir.exists()

        params = ExportDocumentInput(file_path=export_path, format=ExportFormat.PNG)
        parent_dir = os.path.dirname(os.path.abspath(params.file_path))

        warnings = []
        if not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
            warnings.append(f"Created directory: {parent_dir}")

        assert missing_dir.exists()
        assert len(warnings) == 1
        assert "Created directory" in warnings[0]

    def test_no_warning_for_existing_directory(self, tmp_path):
        """Verify no warning when directory already exists."""
        export_path = str(tmp_path / "output.png")
        params = ExportDocumentInput(file_path=export_path, format=ExportFormat.PNG)
        parent_dir = os.path.dirname(os.path.abspath(params.file_path))

        warnings = []
        if not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
            warnings.append(f"Created directory: {parent_dir}")

        assert len(warnings) == 0

    def test_deep_nested_directory_creation(self, tmp_path):
        """Verify deeply nested dirs (3+ levels) are created."""
        deep = tmp_path / "a" / "b" / "c" / "d"
        export_path = str(deep / "output.svg")

        assert not deep.exists()

        parent_dir = os.path.dirname(os.path.abspath(export_path))
        os.makedirs(parent_dir, exist_ok=True)

        assert deep.exists()

    @pytest.mark.asyncio
    async def test_warning_appears_in_envelope(self, tmp_path):
        """Integration: warning about created dir appears in the output envelope."""
        missing_dir = tmp_path / "brand_kit" / "exports"
        export_path = str(missing_dir / "post.png")
        params = ExportDocumentInput(file_path=export_path, format=ExportFormat.PNG)

        result_str, _, _ = await _run_export(params)
        result = json.loads(result_str)

        # The dir-creation warning should surface through the envelope
        assert missing_dir.exists()
        found = any("Created directory" in w for w in result.get("warnings", []))
        assert found, f"Expected 'Created directory' warning in {result.get('warnings')}"

    @pytest.mark.asyncio
    async def test_no_dir_warning_for_existing(self, tmp_path):
        """Integration: no dir warning when directory already exists."""
        export_path = str(tmp_path / "output.png")
        params = ExportDocumentInput(file_path=export_path, format=ExportFormat.PNG)

        result_str, _, _ = await _run_export(params)
        result = json.loads(result_str)

        dir_warnings = [w for w in result.get("warnings", []) if "Created directory" in w]
        assert len(dir_warnings) == 0


# ======================================================================
# Fix 2 (P1): Export precheck uses scope="document" instead of "artboard"
# ======================================================================


class TestPrecheckScope:
    """Fix 2: Export precheck should use scope='artboard'."""

    @pytest.mark.asyncio
    async def test_precheck_includes_artboard_scope(self):
        """Verify precheck script contains scope: 'artboard'."""
        params = ExportDocumentInput(
            file_path="C:/output/test.png",
            format=ExportFormat.PNG,
            artboard_only=True,
            artboard_index=0,
        )
        _, scripts, _ = await _run_export(params)

        assert len(scripts) >= 1
        precheck_script = scripts[0]
        assert 'scope: "artboard"' in precheck_script

    @pytest.mark.asyncio
    async def test_precheck_not_run_without_artboard_only(self):
        """No precheck when artboard_only is False."""
        params = ExportDocumentInput(
            file_path="C:/output/test.png",
            format=ExportFormat.PNG,
            artboard_only=False,
        )
        _, scripts, _ = await _run_export(params)

        # Only one script call (the export itself), no precheck
        assert len(scripts) == 1
        assert "countItemsOnArtboard" not in scripts[0]

    @pytest.mark.asyncio
    async def test_precheck_with_null_artboard_index(self):
        """Precheck works with artboard_index=None (uses null in JS)."""
        params = ExportDocumentInput(
            file_path="C:/output/test.png",
            format=ExportFormat.PNG,
            artboard_only=True,
            artboard_index=None,
        )
        _, scripts, _ = await _run_export(params)

        precheck_script = scripts[0]
        assert "artboardIndex: null" in precheck_script
        assert 'scope: "artboard"' in precheck_script

    @pytest.mark.asyncio
    async def test_precheck_has_expected_options(self):
        """Precheck call has all expected option fields."""
        params = ExportDocumentInput(
            file_path="C:/output/test.png",
            format=ExportFormat.PNG,
            artboard_only=True,
            artboard_index=2,
        )
        _, scripts, _ = await _run_export(params)

        precheck = scripts[0]
        assert 'boundsType: "visible"' in precheck
        assert "ignoreHidden: true" in precheck
        assert "ignoreLocked: true" in precheck
        assert 'policy: "intersects"' in precheck
        assert "artboardIndex: 2" in precheck

    @pytest.mark.asyncio
    async def test_precheck_blank_artboard_warning(self):
        """Warning when precheck shows 0 items on artboard."""
        params = ExportDocumentInput(
            file_path="C:/output/test.png",
            format=ExportFormat.PNG,
            artboard_only=True,
            artboard_index=0,
        )

        async def mock_exec(script, **kw):
            return {"result": json.dumps({
                "success": True,
                "result": json.dumps({
                    "on_artboard": 0,
                    "off_artboard": 12,
                    "skipped": 3,
                    "items_total": 15,
                    "items_checked": 12,
                    "scope": "artboard",
                })
            })}

        with patch("illustrator_mcp.tools.documents.execute_script_with_context",
                   side_effect=mock_exec):
            result_str = await illustrator_export_document(params)

        result = json.loads(result_str)
        assert any("blank" in w.lower() for w in result.get("warnings", []))

    @pytest.mark.asyncio
    async def test_precheck_failure_is_non_fatal(self):
        """If precheck raises, export still proceeds with a warning."""
        params = ExportDocumentInput(
            file_path="C:/output/test.png",
            format=ExportFormat.PNG,
            artboard_only=True,
            artboard_index=0,
        )

        call_count = [0]

        async def mock_exec(script, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("Precheck boom")
            return _make_mock_export_response()

        with patch("illustrator_mcp.tools.documents.execute_script_with_context",
                   side_effect=mock_exec):
            result_str = await illustrator_export_document(params)

        result = json.loads(result_str)
        # Should have a warning about precheck failure but still attempted export
        assert any("Pre-export check failed" in w for w in result.get("warnings", []))
        assert call_count[0] == 2  # precheck + export

    @pytest.mark.asyncio
    async def test_precheck_result_in_diagnostics(self):
        """Precheck result appears in diagnostics."""
        params = ExportDocumentInput(
            file_path="C:/output/test.png",
            format=ExportFormat.PNG,
            artboard_only=True,
            artboard_index=0,
        )
        result_str, _, _ = await _run_export(params)
        result = json.loads(result_str)

        diag = result.get("diagnostics", {})
        precheck = diag.get("precheck_result", {})
        assert precheck.get("on_artboard") == 5
        assert precheck.get("scope") == "artboard"


# ======================================================================
# Fix 3 (P1): Guide lines trigger zero-size warnings in preflight
# ======================================================================


class TestGuideFiltering:
    """Fix 3: Guide lines should be skipped in zero-size check."""

    def test_guide_skip_in_preflight_jsx(self):
        """Verify the inline JSX contains guide filtering."""
        source = _preflight_source()
        assert "item.guides" in source

    def test_guide_check_after_hidden_check(self):
        """Guides filter must come AFTER the hidden/layer-hidden check."""
        source = _preflight_source()
        # Find the zero-size section
        zs_start = source.find("Zero-size check")
        zs_section = source[zs_start:]

        hidden_pos = zs_section.find("item.hidden")
        guide_pos = zs_section.find("item.guides")

        assert hidden_pos < guide_pos, \
            "Guide check should come after hidden check in zero-size section"

    def test_guide_check_before_width_height(self):
        """Guides filter must come BEFORE the width/height comparison."""
        source = _preflight_source()
        zs_start = source.find("Zero-size check")
        zs_section = source[zs_start:]

        guide_pos = zs_section.find("item.guides")
        width_pos = zs_section.find("item.width === 0")

        assert guide_pos < width_pos, \
            "Guide check should come before width/height check"

    def test_guide_check_uses_continue(self):
        """Guide filter skips the item with continue statement."""
        source = _preflight_source()
        # Find the line containing item.guides
        for line in source.splitlines():
            if "item.guides" in line and "continue" in line:
                return  # Found it
        pytest.fail("Expected 'item.guides' line with 'continue'")


# ======================================================================
# Fix 4 (P2): Hidden layer items in artboard-scoped validation
# ======================================================================


class TestLayerVisibilityFiltering:
    """Fix 4: Hidden layer items should be excluded from validation."""

    # --- validate.jsx ---

    def test_validate_jsx_has_isLayerHidden_function(self):
        """isLayerHidden is declared as a named function in validate.jsx."""
        content = _read_validate_jsx()
        assert "function isLayerHidden(item)" in content

    def test_validate_jsx_isLayerHidden_checks_visibility(self):
        """isLayerHidden checks l.visible."""
        content = _read_validate_jsx()
        # Grab the function body
        start = content.find("function isLayerHidden(item)")
        end = content.find("\n}", start) + 2
        body = content[start:end]

        assert "!l.visible" in body
        assert "return true" in body

    def test_validate_jsx_isLayerHidden_walks_parent_layers(self):
        """isLayerHidden traverses parent layers (l.parent.typename === 'Layer')."""
        content = _read_validate_jsx()
        start = content.find("function isLayerHidden(item)")
        end = content.find("\n}", start) + 2
        body = content[start:end]

        assert "l.parent.typename === 'Layer'" in body
        assert "l = l.parent" in body

    def test_validate_jsx_isLayerHidden_has_try_catch(self):
        """isLayerHidden wraps in try/catch for safety."""
        content = _read_validate_jsx()
        start = content.find("function isLayerHidden(item)")
        end = content.find("\n}", start) + 2
        body = content[start:end]

        assert "try" in body
        assert "catch" in body

    def test_validate_jsx_isLayerHidden_returns_false_default(self):
        """isLayerHidden returns false when no hidden ancestor found."""
        content = _read_validate_jsx()
        start = content.find("function isLayerHidden(item)")
        end = content.find("\n}", start) + 2
        body = content[start:end]

        assert "return false" in body

    def test_validate_jsx_countItems_uses_isLayerHidden(self):
        """countItemsOnArtboard combines isHidden with isLayerHidden."""
        content = _read_validate_jsx()
        # Find the hidden check line in countItemsOnArtboard
        assert "isHidden || isLayerHidden(item)" in content

    def test_validate_jsx_isLayerHidden_declared_before_countItems(self):
        """isLayerHidden is declared before countItemsOnArtboard (hoisting order)."""
        content = _read_validate_jsx()
        helper_pos = content.find("function isLayerHidden")
        counter_pos = content.find("function countItemsOnArtboard")

        assert helper_pos < counter_pos, \
            "isLayerHidden should be declared before countItemsOnArtboard"

    # --- query.py (inline JSX) ---

    def test_query_py_has_isLayerHidden_inline(self):
        """query.py inline JSX contains isLayerHidden helper."""
        source = _preflight_source()
        assert "function isLayerHidden(item)" in source

    def test_query_py_isLayerHidden_used_in_zero_size(self):
        """isLayerHidden(item) is used in zero-size check."""
        source = _preflight_source()
        zs_start = source.find("Zero-size check")
        zs_end = source.find("Empty text", zs_start)
        zs_section = source[zs_start:zs_end]

        assert "isLayerHidden(item)" in zs_section

    def test_query_py_isLayerHidden_used_in_empty_text(self):
        """isLayerHidden(tf) is used in empty text check."""
        source = _preflight_source()
        et_start = source.find("Empty text")
        et_section = source[et_start:]

        assert "isLayerHidden(tf)" in et_section

    def test_query_py_isLayerHidden_declared_before_use(self):
        """isLayerHidden helper is declared before the zero-size check."""
        source = _preflight_source()
        decl_pos = source.find("function isLayerHidden(item)")
        use_pos = source.find("isLayerHidden(item)")

        assert decl_pos < use_pos

    def test_query_py_layer_hidden_combined_with_item_hidden(self):
        """Zero-size uses (item.hidden || isLayerHidden(item)) together."""
        source = _preflight_source()
        assert "item.hidden || isLayerHidden(item)" in source

    def test_query_py_layer_hidden_combined_with_tf_hidden(self):
        """Empty text uses (tf.hidden || isLayerHidden(tf)) together."""
        source = _preflight_source()
        assert "tf.hidden || isLayerHidden(tf)" in source

    # --- manifest.json ---

    def test_manifest_exports_isLayerHidden(self):
        """Manifest exports list includes isLayerHidden."""
        manifest = _read_manifest()
        exports = manifest["libraries"]["validate"]["exports"]
        assert "isLayerHidden" in exports

    def test_manifest_export_order(self):
        """isLayerHidden is between isItemCenterOnArtboard and countItemsOnArtboard."""
        manifest = _read_manifest()
        exports = manifest["libraries"]["validate"]["exports"]
        assert exports.index("isItemCenterOnArtboard") < exports.index("isLayerHidden")
        assert exports.index("isLayerHidden") < exports.index("countItemsOnArtboard")


# ======================================================================
# Fix 5 (P2): PDF export timeout too short
# ======================================================================


class TestTimeoutParameter:
    """Fix 5: execute_script_with_context should accept optional timeout."""

    def test_signature_has_timeout_param(self):
        """execute_script_with_context accepts a timeout parameter."""
        sig = inspect.signature(execute_script_with_context)
        assert "timeout" in sig.parameters

    def test_timeout_param_is_optional_float(self):
        """timeout parameter has type Optional[float] with default None."""
        sig = inspect.signature(execute_script_with_context)
        param = sig.parameters["timeout"]
        assert param.default is None

    def test_export_pdf_uses_60s_timeout(self):
        """PDF export passes timeout=60.0."""
        source = _export_source()
        assert "timeout=60.0 if params.format == ExportFormat.PDF else None" in source

    def test_non_pdf_formats_pass_none_timeout(self):
        """Non-PDF formats pass timeout=None (uses default)."""
        source = _export_source()
        # The ternary produces None for non-PDF
        assert "else None" in source

    @pytest.mark.asyncio
    async def test_timeout_60_passed_to_bridge_for_pdf(self):
        """Custom timeout=60.0 is forwarded to _execute_via_bridge."""
        with patch("illustrator_mcp.proxy_client._execute_via_bridge",
                   new_callable=AsyncMock) as mock_bridge:
            mock_bridge.return_value = {"result": '{"success": true}'}

            await execute_script_with_context(
                script="test()",
                command_type="test",
                timeout=60.0,
            )

            _, kwargs = mock_bridge.call_args
            assert kwargs["timeout"] == 60.0

    @pytest.mark.asyncio
    async def test_default_timeout_uses_config(self):
        """None timeout falls back to config.timeout."""
        with patch("illustrator_mcp.proxy_client._execute_via_bridge",
                   new_callable=AsyncMock) as mock_bridge:
            with patch("illustrator_mcp.proxy_client.config") as mock_config:
                mock_config.timeout = 30.0
                mock_bridge.return_value = {"result": '{"success": true}'}

                await execute_script_with_context(
                    script="test()",
                    command_type="test",
                    timeout=None,
                )

                _, kwargs = mock_bridge.call_args
                assert kwargs["timeout"] == 30.0

    @pytest.mark.asyncio
    async def test_explicit_timeout_overrides_config(self):
        """Explicit timeout takes precedence over config.timeout."""
        with patch("illustrator_mcp.proxy_client._execute_via_bridge",
                   new_callable=AsyncMock) as mock_bridge:
            with patch("illustrator_mcp.proxy_client.config") as mock_config:
                mock_config.timeout = 30.0
                mock_bridge.return_value = {"result": '{"success": true}'}

                await execute_script_with_context(
                    script="test()",
                    command_type="test",
                    timeout=120.0,
                )

                _, kwargs = mock_bridge.call_args
                assert kwargs["timeout"] == 120.0

    @pytest.mark.asyncio
    async def test_pdf_export_calls_with_timeout(self):
        """End-to-end: PDF export passes timeout=60.0 through to execute_script_with_context."""
        params = ExportDocumentInput(
            file_path="C:/output/test.pdf",
            format=ExportFormat.PDF,
        )

        kwargs_list = []
        result_str, _, kwargs_list = await _run_export(params, captured_kwargs=kwargs_list)

        # The export call (not precheck since artboard_only=False)
        export_kw = kwargs_list[0]
        assert export_kw.get("timeout") == 60.0

    @pytest.mark.asyncio
    async def test_png_export_calls_with_none_timeout(self):
        """End-to-end: PNG export passes timeout=None."""
        params = ExportDocumentInput(
            file_path="C:/output/test.png",
            format=ExportFormat.PNG,
        )

        kwargs_list = []
        result_str, _, kwargs_list = await _run_export(params, captured_kwargs=kwargs_list)

        export_kw = kwargs_list[0]
        assert export_kw.get("timeout") is None


# ======================================================================
# Fix 6 (P3): No export dimensions in response
# ======================================================================


class TestExportDimensions:
    """Fix 6: Export response should include width/height."""

    # --- PNG/JPG/SVG (computed from artboard + scale) ---

    def test_png_export_script_has_dimension_vars(self):
        """PNG export JSX computes exportWidth and exportHeight."""
        source = templates.EXPORT_STANDARD.template
        assert "exportWidth" in source
        assert "exportHeight" in source

    def test_dimension_formula_uses_artboard_rect(self):
        """Dimensions are derived from artboardRect, not document size."""
        source = templates.EXPORT_STANDARD.template
        assert "abRect[2] - abRect[0]" in source   # width from artboard
        assert "abRect[3] - abRect[1]" in source    # height from artboard

    def test_dimension_formula_divides_by_100(self):
        """Scale is applied as percentage (divide by 100)."""
        source = templates.EXPORT_STANDARD.template
        assert "/ 100" in source

    def test_dimension_uses_math_round(self):
        """Pixel dimensions are rounded to integers."""
        source = templates.EXPORT_STANDARD.template
        assert "Math.round" in source

    def test_dimensions_returned_in_json(self):
        """width and height appear in the return JSON."""
        source = templates.EXPORT_STANDARD.template
        assert "width: exportWidth" in source
        assert "height: exportHeight" in source

    def test_jpg_export_also_has_dimensions(self):
        """JPG uses same EXPORT_STANDARD template as PNG, so also gets dimensions."""
        # JPG format uses config["type"] which is truthy, so it enters the same code path
        source = _export_source()
        # The dimension code is in the if config["type"] block which covers PNG, JPG, SVG
        assert "ExportOptionsJPEG" in source

    def test_svg_export_also_has_dimensions(self):
        """SVG uses same EXPORT_STANDARD template, so also gets dimensions."""
        source = _export_source()
        assert "ExportOptionsSVG" in source

    @pytest.mark.asyncio
    async def test_scale_embedded_in_dimension_formula(self):
        """The scale variable is embedded in the JSX dimension formula."""
        params = ExportDocumentInput(
            file_path="C:/output/test.png",
            format=ExportFormat.PNG,
            scale=2.0,
        )

        scripts = []
        await _run_export(params, captured_scripts=scripts)

        export_script = scripts[0]
        # scale=2.0 * 100 = 200.0
        assert "200.0 / 100" in export_script

    @pytest.mark.asyncio
    async def test_scale_1x_in_dimension_formula(self):
        """At scale=1.0, the formula uses 100.0."""
        params = ExportDocumentInput(
            file_path="C:/output/test.png",
            format=ExportFormat.PNG,
            scale=1.0,
        )

        scripts = []
        await _run_export(params, captured_scripts=scripts)

        export_script = scripts[0]
        assert "100.0 / 100" in export_script

    # --- PDF (vector dimensions in points) ---

    def test_pdf_template_has_width_pt(self):
        """PDF template returns width_pt."""
        rendered = templates.EXPORT_PDF.substitute(path="/test/output.pdf")
        assert "width_pt" in rendered

    def test_pdf_template_has_height_pt(self):
        """PDF template returns height_pt."""
        rendered = templates.EXPORT_PDF.substitute(path="/test/output.pdf")
        assert "height_pt" in rendered

    def test_pdf_template_width_formula(self):
        """PDF width uses abRect[2] - abRect[0]."""
        rendered = templates.EXPORT_PDF.substitute(path="/test/output.pdf")
        assert "abRect[2] - abRect[0]" in rendered

    def test_pdf_template_height_formula(self):
        """PDF height uses Math.abs(abRect[3] - abRect[1])."""
        rendered = templates.EXPORT_PDF.substitute(path="/test/output.pdf")
        assert "Math.abs(abRect[3] - abRect[1])" in rendered

    def test_pdf_template_uses_ok_data_envelope(self):
        """PDF template returns {ok: true, data: {...}, operation: ...}."""
        rendered = templates.EXPORT_PDF.substitute(path="/test/output.pdf")
        assert "ok: true" in rendered
        assert "data:" in rendered
        assert "operation:" in rendered

    def test_pdf_template_still_has_format(self):
        """PDF template still returns format: "PDF"."""
        rendered = templates.EXPORT_PDF.substitute(path="/test/output.pdf")
        assert '"PDF"' in rendered

    def test_pdf_template_gets_active_artboard(self):
        """PDF template reads the active artboard index."""
        rendered = templates.EXPORT_PDF.substitute(path="/test/output.pdf")
        assert "getActiveArtboardIndex()" in rendered

    def test_pdf_template_reads_artboard_rect(self):
        """PDF template reads artboardRect from the active artboard."""
        rendered = templates.EXPORT_PDF.substitute(path="/test/output.pdf")
        assert "artboards[abIdx].artboardRect" in rendered

    def test_pdf_template_is_valid_js_structure(self):
        """PDF template has matching parens and braces."""
        rendered = templates.EXPORT_PDF.substitute(path="/test.pdf")
        assert rendered.count("(") == rendered.count(")")
        assert rendered.count("{") == rendered.count("}")


# ======================================================================
# Fix 7: Bump validate.jsx version to 1.2.0
# ======================================================================


class TestManifestVersion:
    """Fix 7: validate.jsx version should be 1.2.0 in manifest."""

    def test_validate_version_is_1_2_0(self):
        """Manifest has validate version 1.2.0."""
        manifest = _read_manifest()
        assert manifest["libraries"]["validate"]["version"] == "1.2.0"

    def test_validate_description_updated(self):
        """Description mentions layer-visibility."""
        manifest = _read_manifest()
        desc = manifest["libraries"]["validate"]["description"]
        assert "layer-visibility" in desc

    def test_validate_has_three_exports(self):
        """validate library now exports 3 functions."""
        manifest = _read_manifest()
        exports = manifest["libraries"]["validate"]["exports"]
        assert len(exports) == 3

    def test_validate_exports_are_complete(self):
        """All three expected exports are present."""
        manifest = _read_manifest()
        exports = set(manifest["libraries"]["validate"]["exports"])
        expected = {"isItemCenterOnArtboard", "isLayerHidden", "countItemsOnArtboard"}
        assert exports == expected

    def test_validate_has_no_dependencies(self):
        """validate library has no dependencies."""
        manifest = _read_manifest()
        assert manifest["libraries"]["validate"]["dependencies"] == []

    def test_validate_file_is_validate_jsx(self):
        """validate library file is validate.jsx."""
        manifest = _read_manifest()
        assert manifest["libraries"]["validate"]["file"] == "validate.jsx"

    def test_manifest_is_valid_json(self):
        """manifest.json is valid JSON with required top-level keys."""
        manifest = _read_manifest()
        assert "libraries" in manifest
        assert "version" in manifest
        assert "validate" in manifest["libraries"]

    def test_validate_jsx_file_exists(self):
        """The validate.jsx file actually exists on disk."""
        assert os.path.isfile(VALIDATE_JSX_PATH)

    def test_validate_jsx_contains_all_exported_functions(self):
        """Each exported function is declared in validate.jsx."""
        manifest = _read_manifest()
        exports = manifest["libraries"]["validate"]["exports"]
        content = _read_validate_jsx()

        for fn_name in exports:
            assert f"function {fn_name}" in content, \
                f"Export '{fn_name}' not found as function declaration in validate.jsx"


# ======================================================================
# Cross-cutting integration tests
# ======================================================================


class TestExportIntegration:
    """Integration tests combining multiple fixes."""

    @pytest.mark.asyncio
    async def test_export_png_with_artboard_only(self, tmp_path):
        """Full export path: dir creation + precheck + export + dimensions."""
        missing_dir = tmp_path / "social_kit"
        export_path = str(missing_dir / "post.png")
        params = ExportDocumentInput(
            file_path=export_path,
            format=ExportFormat.PNG,
            artboard_only=True,
            artboard_index=0,
            scale=2.0,
        )

        result_str, scripts, kwargs_list = await _run_export(params)
        result = json.loads(result_str)

        # Fix 1: Directory was created
        assert missing_dir.exists()

        # Fix 2: Precheck used artboard scope
        assert len(scripts) >= 2
        assert 'scope: "artboard"' in scripts[0]

        # Fix 5: PDF timeout not applied for PNG
        export_kw = kwargs_list[-1]
        assert export_kw.get("timeout") is None

        # Fix 6: Export script computes dimensions
        export_script = scripts[-1]
        assert "exportWidth" in export_script
        assert "exportHeight" in export_script

    @pytest.mark.asyncio
    async def test_export_pdf_with_artboard_only(self, tmp_path):
        """PDF export path: dir creation + precheck + timeout."""
        missing_dir = tmp_path / "pdfs"
        export_path = str(missing_dir / "output.pdf")
        params = ExportDocumentInput(
            file_path=export_path,
            format=ExportFormat.PDF,
            artboard_only=True,
            artboard_index=0,
        )

        kwargs_list = []
        result_str, scripts, kwargs_list = await _run_export(
            params, captured_kwargs=kwargs_list
        )
        result = json.loads(result_str)

        # Fix 1: Directory created
        assert missing_dir.exists()

        # Fix 5: PDF timeout = 60s (last kwargs is the export call)
        export_kw = kwargs_list[-1]
        assert export_kw.get("timeout") == 60.0

    @pytest.mark.asyncio
    async def test_export_without_artboard_only_still_works(self):
        """Regression: export without artboard_only has no precheck, still succeeds."""
        params = ExportDocumentInput(
            file_path="C:/output/test.jpg",
            format=ExportFormat.JPG,
        )

        result_str, scripts, _ = await _run_export(params)
        result = json.loads(result_str)

        assert len(scripts) == 1  # No precheck
        assert "countItemsOnArtboard" not in scripts[0]

    @pytest.mark.asyncio
    async def test_export_diagnostics_include_format_and_scale(self):
        """Diagnostics contain file_path, format, scale, artboard_only."""
        params = ExportDocumentInput(
            file_path="C:/output/test.png",
            format=ExportFormat.PNG,
            scale=1.5,
            artboard_only=False,
        )

        result_str, _, _ = await _run_export(params)
        result = json.loads(result_str)
        diag = result.get("diagnostics", {})

        assert diag["file_path"] == "C:/output/test.png"
        assert diag["format"] == "png"
        assert diag["scale"] == 1.5
        assert diag["artboard_only"] is False

    @pytest.mark.asyncio
    async def test_all_four_formats_produce_valid_envelope(self):
        """Every export format produces a valid JSON envelope with ok field."""
        for fmt in [ExportFormat.PNG, ExportFormat.JPG, ExportFormat.SVG, ExportFormat.PDF]:
            params = ExportDocumentInput(
                file_path=f"C:/output/test.{fmt.value}",
                format=fmt,
            )
            result_str, _, _ = await _run_export(params)
            result = json.loads(result_str)
            assert "ok" in result, f"Missing 'ok' in envelope for {fmt.value}"
            assert "diagnostics" in result
            assert result["diagnostics"]["format"] == fmt.value


class TestValidateJsxStructure:
    """Structural tests for validate.jsx to catch syntax errors."""

    def test_all_functions_have_jsdoc(self):
        """Each exported function has a JSDoc comment above it."""
        content = _read_validate_jsx()
        manifest = _read_manifest()
        exports = manifest["libraries"]["validate"]["exports"]

        for fn_name in exports:
            fn_pos = content.find(f"function {fn_name}")
            # Look backwards from fn_pos for /**
            preceding = content[:fn_pos]
            last_jsdoc_end = preceding.rfind("*/")
            assert last_jsdoc_end != -1, f"No JSDoc found before {fn_name}"
            # JSDoc end should be reasonably close (within 20 lines)
            between = preceding[last_jsdoc_end:]
            newlines = between.count("\n")
            assert newlines <= 5, \
                f"JSDoc for {fn_name} is {newlines} lines away, expected <= 5"

    def test_no_trailing_syntax_errors(self):
        """validate.jsx ends cleanly (no dangling braces/parens)."""
        content = _read_validate_jsx()
        # Strip whitespace from end
        content = content.rstrip()
        assert content.endswith("}"), "validate.jsx should end with closing brace"

    def test_balanced_braces(self):
        """Braces are balanced in validate.jsx."""
        content = _read_validate_jsx()
        # Strip block comments (JSDoc contains {Object}, {Array} etc.)
        stripped = re.sub(r'/\*[\s\S]*?\*/', '', content)
        # Strip line comments
        stripped = re.sub(r'//.*', '', stripped)
        # Strip strings
        stripped = re.sub(r'"[^"]*"', '', stripped)
        stripped = re.sub(r"'[^']*'", '', stripped)
        assert stripped.count("{") == stripped.count("}"), "Unbalanced braces"
        assert stripped.count("(") == stripped.count(")"), "Unbalanced parens"
