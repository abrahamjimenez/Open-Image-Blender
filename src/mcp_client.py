"""Minimal stdio MCP client for the Blender MCP server (uvx mcp-for-blender)."""
import json
import subprocess


class MCPClient:
    def __init__(self, command=("uvx", "mcp-for-blender")):
        self.proc = subprocess.Popen(
            list(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self._id = 0
        self._request("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "openimageblender", "version": "0.1"}})
        self.proc.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.proc.stdin.flush()

    def _request(self, method, params=None):
        self._id += 1
        self.proc.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "id": self._id, "method": method,
             "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed the connection")
        out = json.loads(line)
        if "error" in out:
            raise RuntimeError(f"MCP {method} failed: {out['error']}")
        return out["result"]

    def tools(self):
        return [t["name"] for t in self._request("tools/list")["tools"]]

    def call(self, tool, arguments=None):
        result = self._request("tools/call", {"name": tool, "arguments": arguments or {}})
        text = "\n".join(c.get("text", "") for c in result.get("content", [])
                         if c.get("type") == "text")
        if result.get("isError"):
            raise RuntimeError(f"Blender tool {tool} error: {text[:500]}")
        return text

    def execute_code(self, code):
        return self.call("execute_blender_code", {"code": code})

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
