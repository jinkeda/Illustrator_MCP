"""
MCP CLI relay — send tool calls to a running illustrator-mcp server via stdin/stdout.
Usage: python scripts/mcp_relay.py <tool_name> <json_args>
"""
import sys, json, subprocess, os

def call_mcp_tool(tool_name: str, args: dict, timeout: float = 30) -> dict:
    """Spawn illustrator-mcp, send a tools/call request, read the response."""
    
    # Initialize request
    init_req = json.dumps({
        "jsonrpc": "2.0", "id": 0,
        "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "mcp-relay", "version": "0.1"}}
    })
    
    # The actual tool call
    tool_req = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args}
    })
    
    # Notifications  
    init_notif = json.dumps({
        "jsonrpc": "2.0",
        "method": "notifications/initialized"
    })
    
    # Frame messages with Content-Length header (MCP stdio transport)
    def frame(msg: str) -> str:
        return f"Content-Length: {len(msg)}\r\n\r\n{msg}"
    
    payload = frame(init_req) + frame(init_notif) + frame(tool_req)
    
    # Spawn the MCP server
    env = os.environ.copy()
    proc = subprocess.Popen(
        [sys.executable, "-m", "illustrator_mcp.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    
    try:
        stdout, stderr = proc.communicate(input=payload.encode(), timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return {"error": "Timeout"}
    
    # Parse responses — find the one with id=1
    stdout_str = stdout.decode("utf-8", errors="replace")
    
    # Extract JSON bodies from Content-Length framed messages
    results = []
    pos = 0
    while pos < len(stdout_str):
        header_end = stdout_str.find("\r\n\r\n", pos)
        if header_end == -1:
            break
        header = stdout_str[pos:header_end]
        # Parse Content-Length
        cl = 0
        for line in header.split("\r\n"):
            if line.lower().startswith("content-length:"):
                cl = int(line.split(":")[1].strip())
        body_start = header_end + 4
        body = stdout_str[body_start:body_start + cl]
        try:
            parsed = json.loads(body)
            results.append(parsed)
        except json.JSONDecodeError:
            pass
        pos = body_start + cl
    
    # Find our tool call response (id=1)
    for r in results:
        if r.get("id") == 1:
            return r
    
    return {"error": "No response found", "all_responses": results, 
            "stderr": stderr.decode("utf-8", errors="replace")[:500]}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python mcp_relay.py <tool_name> '<json_args>'")
        sys.exit(1)
    
    tool = sys.argv[1]
    args = json.loads(sys.argv[2])
    result = call_mcp_tool(tool, args, timeout=45)
    print(json.dumps(result, indent=2)[:2000])
