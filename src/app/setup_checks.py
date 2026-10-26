"""First-run setup checks: Blender, MCP addon, MCP connection, API key."""
import glob
import os
import shutil
import subprocess

from src import blender_host


def check_blender():
    path = shutil.which("blender")
    return (bool(path), f"Blender: {'found at ' + path if path else 'not found in PATH'}")


def check_addon():
    hits = glob.glob(os.path.expanduser(
        "~/.config/blender/*/scripts/addons/blender_mcp.py"))
    return (bool(hits), "MCP addon: " + ("installed" if hits else "not installed"))


def check_mcp():
    ok = blender_host.mcp_port_open()
    return (ok, "MCP connection: " + ("live on port 9876" if ok
                                      else "not running (launch Blender)"))


def check_key(api_key):
    ok = bool(api_key)
    return (ok, "Meta API key: " + ("set (full mode)" if ok
                                    else "not set (metrics-only mode)"))


def run_checks(api_key):
    return [check_blender(), check_addon(), check_mcp(), check_key(api_key)]


def install_addon():
    proc = subprocess.run(["uvx", "mcp-for-blender", "install-addon"],
                          capture_output=True, text=True, timeout=300)
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-500:]
