# Tests for Illustrator MCP

This directory contains unit tests for the Illustrator MCP server.

## Running Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_documents.py -v

# Run with coverage
pip install pytest-cov
pytest tests/ --cov=illustrator_mcp --cov-report=html
```

## Test Structure

- `test_documents.py` - Document operation tool tests
- `test_shapes.py` - Shape drawing tool tests
- `test_objects.py` - Object operation tool tests
- `test_pathfinder.py` - Pathfinder operation tests
- `conftest.py` - Shared test fixtures
