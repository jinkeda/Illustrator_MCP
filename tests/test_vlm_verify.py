"""Live verification: filter + visual refinements on 59-item dashboard.

Requires a fixture PNG at a local temp path that only exists after a live
stress-test run.  The filter-only assertions are always exercised; the
composite overlay portion is skipped when the fixture is absent.
"""
import os
import pytest
from illustrator_mcp.overlay import composite_overlay, map_bounds_to_pixels, get_png_dimensions
from illustrator_mcp.tools.execute import _filter_items

_FIXTURE_PNG = r"C:\Users\k.jin\AppData\Local\Temp\vlm_stress_base.png"

DATA = {"artboard": [0, 0, 1200, -800], "items": [{"name":"legend_other","type":"TextFrame","bounds":[658,-262.84,709.28,-274.79]},{"name":"dot_other","type":"PathItem","bounds":[640,-261,650,-271]},{"name":"ring_other","type":"PathItem","bounds":[870,-460,910,-500]},{"name":"legend_consumer","type":"TextFrame","bounds":[658,-290.84,729.76,-302.79]},{"name":"dot_consumer","type":"PathItem","bounds":[640,-289,650,-299]},{"name":"ring_consumer","type":"PathItem","bounds":[846,-436,934,-524]},{"name":"legend_smb","type":"TextFrame","bounds":[658,-318.84,702.89,-330.79]},{"name":"dot_smb","type":"PathItem","bounds":[640,-317,650,-327]},{"name":"ring_smb","type":"PathItem","bounds":[818,-408,962,-552]},{"name":"legend_enterprise","type":"TextFrame","bounds":[658,-346.84,729.2,-358.79]},{"name":"dot_enterprise","type":"PathItem","bounds":[640,-345,650,-355]},{"name":"ring_enterprise","type":"PathItem","bounds":[790,-380,990,-580]},{"name":"rpanel_title","type":"TextFrame","bounds":[640,-308.33,764.42,-323.54]},{"name":"right_panel_bg","type":"PathItem","bounds":[619.5,-299.5,1160.5,-660.5]},{"name":"val_dec","type":"TextFrame","bounds":[488,-344.51,511.44,-354.29]},{"name":"month_dec","type":"TextFrame","bounds":[495,-623.67,511.19,-634.54]},{"name":"bar_dec","type":"PathItem","bounds":[480,-360,540,-640]},{"name":"val_nov","type":"TextFrame","bounds":[408,-369.22,431.44,-379]},{"name":"month_nov","type":"TextFrame","bounds":[415,-623.67,431.81,-634.54]},{"name":"bar_nov","type":"PathItem","bounds":[400,-384.71,460,-640]},{"name":"val_oct","type":"TextFrame","bounds":[328,-393.92,351.44,-403.71]},{"name":"month_oct","type":"TextFrame","bounds":[335,-623.67,349.85,-634.54]},{"name":"bar_oct","type":"PathItem","bounds":[320,-409.41,380,-640]},{"name":"val_sep","type":"TextFrame","bounds":[248,-463.92,271.44,-473.71]},{"name":"month_sep","type":"TextFrame","bounds":[255,-623.67,270.69,-634.54]},{"name":"bar_sep","type":"PathItem","bounds":[240,-479.41,300,-640]},{"name":"val_aug","type":"TextFrame","bounds":[168,-443.33,191.44,-453.12]},{"name":"month_aug","type":"TextFrame","bounds":[175,-623.67,192.1,-634.54]},{"name":"bar_aug","type":"PathItem","bounds":[160,-458.82,220,-640]},{"name":"val_jul","type":"TextFrame","bounds":[88,-476.28,111.44,-486.06]},{"name":"month_jul","type":"TextFrame","bounds":[95,-623.67,106.57,-634.54]},{"name":"bar_jul","type":"PathItem","bounds":[80,-491.76,140,-640]},{"name":"chart_title","type":"TextFrame","bounds":[50,-308.33,224.94,-323.54]},{"name":"chart_area_bg","type":"PathItem","bounds":[39.5,-299.5,580.5,-660.5]},{"name":"delta_kpi-churn","type":"TextFrame","bounds":[896,-219.16,926.32,-233.29]},{"name":"value_kpi-churn","type":"TextFrame","bounds":[896,-148.26,960.8,-183.04]},{"name":"label_kpi-churn","type":"TextFrame","bounds":[896,-140.84,947.02,-152.79]},{"name":"accent_kpi-churn","type":"PathItem","bounds":[880,-120,1140,-124]},{"name":"card_kpi-churn","type":"PathItem","bounds":[879.5,-119.5,1140.5,-260.5]},{"name":"delta_kpi-nps","type":"TextFrame","bounds":[616,-219.16,647.26,-233.29]},{"name":"value_kpi-nps","type":"TextFrame","bounds":[616,-148.26,648.83,-183.04]},{"name":"label_kpi-nps","type":"TextFrame","bounds":[616,-140.84,662.23,-152.79]},{"name":"accent_kpi-nps","type":"PathItem","bounds":[600,-120,860,-124]},{"name":"card_kpi-nps","type":"PathItem","bounds":[599.5,-119.5,860.5,-260.5]},{"name":"delta_kpi-usr","type":"TextFrame","bounds":[336,-219.16,370.07,-233.29]},{"name":"value_kpi-usr","type":"TextFrame","bounds":[336,-148.26,409.53,-183.04]},{"name":"label_kpi-usr","type":"TextFrame","bounds":[336,-140.84,391.78,-152.79]},{"name":"accent_kpi-usr","type":"PathItem","bounds":[320,-120,580,-124]},{"name":"card_kpi-usr","type":"PathItem","bounds":[319.5,-119.5,580.5,-260.5]},{"name":"delta_kpi-rev","type":"TextFrame","bounds":[56,-219.16,96.74,-233.29]},{"name":"value_kpi-rev","type":"TextFrame","bounds":[56,-148.26,137.6,-183.04]},{"name":"label_kpi-rev","type":"TextFrame","bounds":[56,-140.84,95.84,-152.79]},{"name":"accent_kpi-rev","type":"PathItem","bounds":[40,-120,300,-124]},{"name":"card_kpi-rev","type":"PathItem","bounds":[39.5,-119.5,300.5,-260.5]},{"name":"section_divider_1","type":"PathItem","bounds":[40,-99.5,1160,-100.5]},{"name":"subtitle_text","type":"TextFrame","bounds":[40,-52,217.85,-65.04]},{"name":"title_text","type":"TextFrame","bounds":[40,-4.61,363.23,-35.04]},{"name":"header_bar","type":"PathItem","bounds":[0,0,1200,-80]},{"name":"bg_canvas","type":"PathItem","bounds":[0,0,1200,-800]}]}


class TestFilterItems:
    """Pure-data tests that don't need a fixture PNG."""

    def test_filter_counts(self):
        kept, filtered_count = _filter_items(DATA["items"], DATA["artboard"])
        assert len(kept) + filtered_count == len(DATA["items"])
        # bg_canvas and section_divider_1 should be filtered
        assert filtered_count == 2

    def test_bg_canvas_filtered(self):
        kept, _ = _filter_items(DATA["items"], DATA["artboard"])
        kept_names = {it["name"] for it in kept}
        assert "bg_canvas" not in kept_names

    def test_section_divider_filtered(self):
        kept, _ = _filter_items(DATA["items"], DATA["artboard"])
        kept_names = {it["name"] for it in kept}
        assert "section_divider_1" not in kept_names

    def test_text_frames_preserved(self):
        kept, _ = _filter_items(DATA["items"], DATA["artboard"])
        kept_names = {it["name"] for it in kept}
        # All TextFrame items should survive (immune to thin-stroke filter)
        for it in DATA["items"]:
            if it["type"] == "TextFrame":
                assert it["name"] in kept_names, f"TextFrame '{it['name']}' was filtered"


def _fixture_is_valid():
    """Check fixture PNG exists AND is decodable."""
    if not os.path.exists(_FIXTURE_PNG):
        return False
    try:
        with open(_FIXTURE_PNG, "rb") as f:
            return get_png_dimensions(f.read()) is not None
    except Exception:
        return False


@pytest.mark.skipif(
    not _fixture_is_valid(),
    reason=f"Fixture PNG missing or invalid: {_FIXTURE_PNG}"
)
class TestCompositeOverlay:
    """Overlay tests that require the live stress-test fixture PNG."""

    def test_annotated_overlay(self):
        with open(_FIXTURE_PNG, "rb") as f:
            raw_png = f.read()
        dims = get_png_dimensions(raw_png)
        assert dims is not None, "Could not decode PNG dimensions"

        kept, _ = _filter_items(DATA["items"], DATA["artboard"])
        annotations = []
        for i, item in enumerate(kept):
            bounds_px = map_bounds_to_pixels(item["bounds"], DATA["artboard"], dims)
            annotations.append({"label": str(i + 1), "bounds_px": bounds_px})

        annotated = composite_overlay(raw_png, annotations)
        assert len(annotated) > 0
