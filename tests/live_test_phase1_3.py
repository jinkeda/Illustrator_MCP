"""
Live test of the Task Protocol implementation in Illustrator.
"""
import asyncio
import json
from illustrator_mcp.tools.execute import (
    illustrator_execute_script,
    illustrator_execute_task,
    ExecuteScriptInput,
    ExecuteTaskInput,
)
from illustrator_mcp.protocol import TaskPayload


async def test_basic_script():
    """Test 1: Basic script execution still works."""
    print("=" * 60)
    print("TEST 1: Basic Script Execution")
    print("=" * 60)
    
    result = await illustrator_execute_script(ExecuteScriptInput(
        script='JSON.stringify({test: "basic", version: app.version})',
        description='Test basic execution'
    ))
    print(result)
    print()


async def test_task_executor_library():
    """Test 2: task_executor.jsx library loads correctly."""
    print("=" * 60)
    print("TEST 2: Task Executor Library Loading")
    print("=" * 60)
    
    result = await illustrator_execute_script(ExecuteScriptInput(
        script='''
// Test that functions are available
var functions = [
    typeof executeTask,
    typeof collectTargets,
    typeof describeItem,
    typeof safeExecute,
    typeof ErrorCodes
];
JSON.stringify({
    success: true,
    functions: functions,
    errorCodes: ErrorCodes
});
''',
        description='Test library loading',
        includes=['task_executor']
    ))
    print(result)
    print()


async def test_execute_task_tool():
    """Test 3: illustrator_execute_task tool works."""
    print("=" * 60)
    print("TEST 3: Execute Task Tool (with trace)")
    print("=" * 60)
    
    payload = TaskPayload(
        task="test_query_selection",
        targets={"type": "selection"},
        params={"testParam": "value"},
        options={"trace": True}
    )
    
    compute_fn = '''
    var actions = [];
    for (var i = 0; i < items.length; i++) {
        actions.push({
            item: items[i],
            itemRef: describeItem(items[i]),
            name: items[i].name || "unnamed"
        });
    }
    return actions;
'''
    
    apply_fn = '''
    // Just count items, don't modify
    for (var i = 0; i < actions.length; i++) {
        report.stats.itemsModified++;
    }
'''
    
    result = await illustrator_execute_task(ExecuteTaskInput(
        payload=payload,
        compute_fn=compute_fn,
        apply_fn=apply_fn
    ))
    print(result)
    print()


async def test_declarative_selector():
    """Test 4: Declarative target selector."""
    print("=" * 60)
    print("TEST 4: Declarative Target Selector (all items)")
    print("=" * 60)
    
    payload = TaskPayload(
        task="query_all_items",
        targets={"type": "all"},
        params={},
        options={"dryRun": True}
    )
    
    compute_fn = '''
    var actions = [];
    for (var i = 0; i < items.length; i++) {
        actions.push({
            item: items[i],
            itemRef: describeItem(items[i])
        });
    }
    return actions;
'''
    
    apply_fn = '''
    // Dry run - no modifications
'''
    
    result = await illustrator_execute_task(ExecuteTaskInput(
        payload=payload,
        compute_fn=compute_fn,
        apply_fn=apply_fn
    ))
    print(result)
    print()


async def main():
    print("\n" + "=" * 60)
    print("ILLUSTRATOR MCP - LIVE TEST PHASE 1-3")
    print("=" * 60 + "\n")
    
    await test_basic_script()
    await test_task_executor_library()
    await test_execute_task_tool()
    await test_declarative_selector()
    
    print("=" * 60)
    print("ALL TESTS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
