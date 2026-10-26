"""Ensure a Blender instance is serving the MCP addon on port 9876.

The MCP addon cannot run in background Blender, so a GUI Blender must be
running. If the port already answers we use it as-is and never touch that
instance; otherwise we launch one new Blender with the addon enabled.
"""
import socket
import subprocess
import time

PORT = 9876


def mcp_port_open():
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=1.5):
            return True
    except OSError:
        return False


def ensure_blender(log=print, timeout=45):
    if mcp_port_open():
        log("Blender MCP: using the instance already running")
        return True
    log("Blender MCP: launching Blender with the MCP addon...")
    subprocess.Popen(
        ["blender", "--python-expr",
         "import bpy; bpy.ops.preferences.addon_enable(module='blender_mcp')"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if mcp_port_open():
            log("Blender MCP: connected")
            return True
        time.sleep(1)
    log("Blender MCP: Blender did not open the MCP port in time")
    return False
