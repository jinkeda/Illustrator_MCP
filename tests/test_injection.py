import pytest
from pathlib import Path
import sys

# Add project root to path to insure imports work
root_dir = Path(__file__).parent.parent
sys.path.append(str(root_dir))

from illustrator_mcp.tools.execute import inject_libraries

def test_inject_no_includes():
    script = "var x = 1;"
    result = inject_libraries(script, None)
    assert result == script
    result = inject_libraries(script, [])
    assert result == script

def test_inject_geometry():
    script = "// user script"
    # geometry.jsx should exist in the real file system as created
    result = inject_libraries(script, ["geometry"])
    
    # Check for content from geometry.jsx
    assert "function getVisibleBounds" in result
    assert "mmToPoints" in result
    
    # Check user script is appended
    assert result.endswith("// user script\n") or result.endswith("// user script")

def test_inject_multiple():
    script = "// user script"
    result = inject_libraries(script, ["geometry", "selection"])
    
    # Check for content from both
    assert "function getVisibleBounds" in result
    assert "function getOrderedSelection" in result

def test_inject_missing_library():
    with pytest.raises(ValueError) as excinfo:
        inject_libraries("foo", ["non_existent_library_123"])
    assert "Library not found" in str(excinfo.value)
