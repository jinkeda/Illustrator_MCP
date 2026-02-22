"""Live integration test: feeds real Illustrator DOM data through vlm_grounding.py."""
import json
import sys
sys.path.insert(0, r"c:\Users\k.jin\OneDrive\PhD\claude\Illustrator_Agent\Illustrator_MCP")

from illustrator_mcp.vlm_grounding import (
    build_dom_map, build_relationship_map, verify_hypothesis,
    capture_dom_snapshot, diff_dom_snapshots,
    VLMHypothesis, DOMMapResult,
)

# ── Real data from Illustrator ──
# Using only the 11 distinct items (skipping duplicates at end)
ITEMS = [
    {"name":"off_artboard","type":"PathItem","bounds":[850,-100,900,-150],"mcp_id":"off_artboard","fill":"#c800c8"},
    {"name":"sq3","type":"PathItem","bounds":[520,-400,560,-440],"mcp_id":"sq3","fill":"#646464"},
    {"name":"sq2","type":"PathItem","bounds":[460,-400,500,-440],"mcp_id":"sq2","fill":"#646464"},
    {"name":"sq1","type":"PathItem","bounds":[400,-400,440,-440],"mcp_id":"sq1","fill":"#646464"},
    {"name":"circle2","type":"PathItem","bounds":[140,-370,220,-450],"mcp_id":"circle2","fill":"#34a853"},
    {"name":"circle1","type":"PathItem","bounds":[100,-350,180,-430],"mcp_id":"circle1","fill":"#fbbc04"},
    {"name":"card2_title","type":"TextFrame","bounds":[425,-62.98,519.64,-82.54],"mcp_id":"card2_title",
     "contents":"Second Card","font":"MyriadPro-Regular","fontSize":18},
    {"name":"card2_bg","type":"PathItem","bounds":[400,-53,700,-253],"mcp_id":"card2_bg","fill":"#ea4335"},
    {"name":"card1_body","type":"TextFrame","bounds":[70,-100,163.27,-113.04],"mcp_id":"card1_body",
     "contents":"Body text of card 1","font":"MyriadPro-Regular","fontSize":12},
    {"name":"card1_title","type":"TextFrame","bounds":[70,-59.98,140.09,-79.54],"mcp_id":"card1_title",
     "contents":"Card Title","font":"MyriadPro-Regular","fontSize":18},
    {"name":"card1_bg","type":"PathItem","bounds":[50,-50,350,-250],"mcp_id":"card1_bg","fill":"#4285f4"},
]

AB_RECT = [0, 0, 800, -600]

print("=" * 60)
print("LIVE TEST 1: build_dom_map")
print("=" * 60)
dm = build_dom_map(ITEMS, AB_RECT)
print(f"  Items in map: {len(dm.by_id)}")
print(f"  Overlay mappings: {len(dm.overlay_to_id)}")
print(f"  Sample entry (card1_bg):")
entry = dm.by_id.get("card1_bg", {})
for k, v in entry.items():
    print(f"    {k}: {v}")

print(f"\n  Overlay->ID mappings:")
for ov, mid in sorted(dm.overlay_to_id.items(), key=lambda x: int(x[0].strip("[]"))):
    print(f"    {ov} -> {mid}")

print("\n" + "=" * 60)
print("LIVE TEST 2: build_relationship_map")
print("=" * 60)
rel = build_relationship_map(dm)
pairs = rel["pairs"]
print(f"  Total relationships: {len(pairs)}")
print(f"  Truncated: {rel.get('relationships_truncated', False)}")
for pk, pv in list(pairs.items())[:5]:
    print(f"  {pk}: gap_x={pv['gap_x']}, aligned={pv['aligned_edges']}, overlap={pv['overlap']}")

print("\n" + "=" * 60)
print("LIVE TEST 3: verify_hypothesis — misalignment")
print("=" * 60)
# card1_title vs card2_title tops should be misaligned (~3pt)
h1 = VLMHypothesis(
    suspected_issue="misalignment",
    elements=["[10]", "[7]"],  # card1_title and card2_title
    edge="top",
)
r1 = verify_hypothesis(h1, dm)
print(f"  Confirmed: {r1.confirmed}")
print(f"  Message: {r1.message}")
print(f"  Evidence: {json.dumps(r1.evidence, indent=2)}")

print("\n" + "=" * 60)
print("LIVE TEST 4: verify_hypothesis — overlap (circles)")
print("=" * 60)
h2 = VLMHypothesis(
    suspected_issue="overlap",
    elements=["[6]", "[5]"],  # circle1 and circle2
)
r2 = verify_hypothesis(h2, dm)
print(f"  Confirmed: {r2.confirmed}")
print(f"  Message: {r2.message}")
print(f"  Evidence: {json.dumps(r2.evidence, indent=2)}")

print("\n" + "=" * 60)
print("LIVE TEST 5: verify_hypothesis — spacing (3 squares)")
print("=" * 60)
h3 = VLMHypothesis(
    suspected_issue="spacing",
    elements=["[4]", "[3]", "[2]"],  # sq1, sq2, sq3
)
r3 = verify_hypothesis(h3, dm)
print(f"  Confirmed: {r3.confirmed}")
print(f"  Message: {r3.message}")
print(f"  Evidence: {json.dumps(r3.evidence, indent=2)}")

print("\n" + "=" * 60)
print("LIVE TEST 6: verify_hypothesis — off_artboard")
print("=" * 60)
h4 = VLMHypothesis(
    suspected_issue="off_artboard",
    elements=["[1]"],  # off_artboard
)
r4 = verify_hypothesis(h4, dm, artboard_screen=[0, 0, 800, 600])
print(f"  Confirmed: {r4.confirmed}")
print(f"  Message: {r4.message}")
print(f"  Evidence: {json.dumps(r4.evidence, indent=2)}")

print("\n" + "=" * 60)
print("LIVE TEST 7: verify_hypothesis — style_mismatch")
print("=" * 60)
h5 = VLMHypothesis(
    suspected_issue="style_mismatch",
    elements=["[6]", "[5]"],  # circle1 (#fbbc04) vs circle2 (#34a853)
)
r5 = verify_hypothesis(h5, dm)
print(f"  Confirmed: {r5.confirmed}")
print(f"  Message: {r5.message}")
print(f"  Evidence: {json.dumps(r5.evidence, indent=2)}")

print("\n" + "=" * 60)
print("LIVE TEST 8: diff_dom_snapshots — simulate a move")
print("=" * 60)
before = capture_dom_snapshot(ITEMS)
after_items = [dict(i) for i in ITEMS]
# Move card2_bg 10pt to the right
for item in after_items:
    if item["mcp_id"] == "card2_bg":
        item["bounds"] = [410, -53, 710, -253]
# Remove circle2
after_items = [i for i in after_items if i.get("mcp_id") != "circle2"]
# Add a new item
after_items.append({"name":"new_star","type":"PathItem","bounds":[300,-300,350,-350],"mcp_id":"new_star","fill":"#ff00ff"})

diff = diff_dom_snapshots(before, after_items)
print(f"  Unchanged: {diff.unchanged}")
print(f"  Moved: {[m['name'] for m in diff.moved]}")
print(f"  Removed: {diff.removed}")
print(f"  Added: {diff.added}")
print(f"  Resized: {[r['name'] for r in diff.resized]}")
print(f"  Mutations: {diff.mutations}")

print("\n" + "=" * 60)
print("ALL LIVE TESTS COMPLETE ✓")
print("=" * 60)
