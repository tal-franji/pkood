import argparse
import subprocess
import os
import sys
import time
import json
import shutil
from pathlib import Path

from pkood.common import (
    BASE_DIR,
    SOCKETS_DIR,
    LOGS_DIR,
    STATE_DIR,
    strip_ansi,
    ensure_dirs,
    get_tmux_cmd,
    create_agent,
    inject_text_to_agent,
    spawn,
    kill_agent,
)
from pkood.tester import test_pkood


def get_agents_status():
    """Returns structured metadata for all agents."""
    ensure_dirs()
    sockets = list(SOCKETS_DIR.glob("*.sock"))
    results = []

    for sock in sockets:
        agent_id = sock.stem
        log_path = LOGS_DIR / f"{agent_id}.log"
        meta_path = STATE_DIR / f"{agent_id}_meta.json"
        status_path = STATE_DIR / f"{agent_id}_status.json"

        log_size = (
            f"{log_path.stat().st_size / 1024:.1f}K" if log_path.exists() else "0K"
        )

        # 1. Get Mechanical Status (from watcher)
        status = "UNKNOWN"
        if meta_path.exists():
            try:
                with open(meta_path, "r") as f:
                    meta = json.load(f)
                    status = meta.get("status", "UNKNOWN")
            except Exception:
                pass

        # Cross-check with tmux
        try:
            subprocess.run(
                get_tmux_cmd(agent_id) + ["ls"], capture_output=True, check=True
            )
            if status == "UNKNOWN":
                status = "RUNNING"
        except subprocess.CalledProcessError:
            status = "EXITED"

        # 2. Get Semantic Focus (from agent)
        focus = ""
        if status_path.exists():
            try:
                with open(status_path, "r") as f:
                    status_data = json.load(f)
                    focus = status_data.get("current_focus", "") or status_data.get(
                        "status_message", ""
                    )
            except Exception:
                pass

        results.append(
            {
                "agent_id": agent_id,
                "status": status,
                "log_size": log_size,
                "focus": focus,
            }
        )
    return results


def get_all_tails(include_summarizer=False):
    """Returns a dictionary of agent IDs and their cleaned tail output."""
    ensure_dirs()
    sockets = list(SOCKETS_DIR.glob("*.sock"))
    tails = {}

    for sock in sockets:
        agent_id = sock.stem
        if not include_summarizer and agent_id == "pkood-summarizer":
            continue

        # Check if alive
        try:
            subprocess.run(
                get_tmux_cmd(agent_id) + ["ls"], capture_output=True, check=True
            )
        except subprocess.CalledProcessError:
            continue  # Skip dead agents

        # Capture Pane
        try:
            capture_cmd = get_tmux_cmd(agent_id) + ["capture-pane", "-p", "-t", "main"]
            result = subprocess.run(
                capture_cmd, capture_output=True, text=True, check=True
            )
            raw_output = result.stdout
        except subprocess.CalledProcessError:
            raw_output = "No output available."

        recent_lines = "\n".join(raw_output.splitlines()[-50:])
        tails[agent_id] = strip_ansi(recent_lines)
    return tails


def cmd_tail(args):
    """The 'tail' command: outputs the last 50 lines of logs for all active agents."""
    tails = get_all_tails()
    if not tails:
        print("No active agents found.")
        return

    for agent_id, clean_text in tails.items():
        print(f"## Agent: {agent_id}")
        print("```")
        print(clean_text)
        print("```\n")


def auto_detect_agent():
    """Detects available AI CLI agents in the system PATH."""
    supported_agents = ["gemini", "claude", "aider"]
    found_agents = []
    for agent in supported_agents:
        if shutil.which(agent):
            found_agents.append(agent)
    return found_agents


def start(args):
    agent_id = args.name
    if not agent_id:
        # Default name to current directory name
        agent_id = Path(args.dir).resolve().name

    # Auto-detect agent or fallback to shell
    available_agents = auto_detect_agent()

    if len(available_agents) == 1:
        launch_cmd = available_agents[0]
        print(f"Auto-detected agent: {launch_cmd}")
    elif len(available_agents) > 1:
        launch_cmd = os.environ.get("SHELL", "bash")
        print(
            f"Found multiple agents ({', '.join(available_agents)}). Defaulting to shell: {launch_cmd}"
        )
    else:
        launch_cmd = os.environ.get("SHELL", "bash")
        print(f"No agents detected. Defaulting to shell: {launch_cmd}")

    if create_agent(agent_id, args.dir, launch_cmd):
        print(f"Starting interactive session for '{agent_id}'...")
        # Give a tiny bit of time for tmux to initialize before attaching
        time.sleep(0.1)
        socket_path = SOCKETS_DIR / f"{agent_id}.sock"
        os.execvp("tmux", ["tmux", "-S", str(socket_path), "attach", "-t", "main"])


def list_agents(args):
    agents = get_agents_status()
    if not agents:
        print("No active agents found.")
        return

    print(f"{'AGENT ID':<20} | {'STATUS':<10} | {'LOG'}")
    print("-" * 50)
    for a in agents:
        print(f"{a['agent_id']:<20} | {a['status']:<10} | {a['log_size']}")


def attach(args):
    agent_id = args.name
    socket_path = SOCKETS_DIR / f"{agent_id}.sock"

    if not socket_path.exists():
        print(f"Error: Agent '{agent_id}' not found.")
        return

    print(f"Attaching to '{agent_id}'... (Press Ctrl+B then D to detach)")
    os.execvp("tmux", ["tmux", "-S", str(socket_path), "attach", "-t", "main"])


def cmd_inject(args):
    """The 'inject' command handler."""
    if inject_text_to_agent(args.name, args.text):
        print(f"Successfully injected text into agent '{args.name}'.")
    else:
        print(f"Error: Agent '{args.name}' not found or not active.")


def cmd_mcp(args):
    """Manages the background MCP service."""
    ensure_dirs()

    # If stdio mode is requested, run the server in the foreground
    if getattr(args, "stdio", False):
        mcp_server_path = Path(__file__).parent / "mcp_server.py"
        env = os.environ.copy()
        env["PYTHONPATH"] = (
            str(Path(__file__).parent.parent) + os.pathsep + env.get("PYTHONPATH", "")
        )
        # We replace the current process with the MCP server
        os.execve(
            sys.executable, [sys.executable, str(mcp_server_path), "--stdio"], env
        )
        return

    pid_file = BASE_DIR / "mcp.pid"

    # Check if already running
    if pid_file.exists():
        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)  # Check if process exists
            print(f"MCP service is already running (PID: {pid}).")
            return
        except (ValueError, ProcessLookupError, PermissionError):
            pid_file.unlink()

    # Determine bind address
    host = "0.0.0.0" if args.external_unsafe else "127.0.0.1"
    port = args.port

    print(f"Starting MCP service on {host}:{port}...")

    # Spawn mcp_server.py as a background process
    mcp_server_path = Path(__file__).parent / "mcp_server.py"

    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = (
            str(Path(__file__).parent.parent) + os.pathsep + env.get("PYTHONPATH", "")
        )

        proc = subprocess.Popen(
            [sys.executable, str(mcp_server_path), "--host", host, "--port", str(port)],
            stdout=open(LOGS_DIR / "mcp.log", "a"),
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )

        with open(pid_file, "w") as f:
            f.write(str(proc.pid))

        print(f"MCP service started in background (PID: {proc.pid}).")
        print(f"Logs: {LOGS_DIR / 'mcp.log'}")

    except Exception as e:
        print(f"Error starting MCP service: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Pkood: Agentic Operations Orchestrator"
    )
    subparsers = parser.add_subparsers(dest="action", help="Commands")

    # Spawn
    spawn_parser = subparsers.add_parser("spawn", help="Spawn a new agent")
    spawn_parser.add_argument("--name", required=True, help="Unique name for the agent")
    spawn_parser.add_argument(
        "--dir", default=".", help="Directory to run the command in"
    )
    spawn_parser.add_argument("command", help="The command to run")

    # Start
    start_parser = subparsers.add_parser(
        "start", help="Start an interactive shell session and attach"
    )
    start_parser.add_argument("--name", help="Unique name (defaults to directory name)")
    start_parser.add_argument("--dir", default=".", help="Directory to start in")

    # List
    subparsers.add_parser("list", aliases=["ls", "ps"], help="List all running agents")

    # Tail
    subparsers.add_parser(
        "tail", help="Output the last 50 lines of logs for all active agents"
    )

    # Attach
    attach_parser = subparsers.add_parser("attach", help="Attach to an agent session")
    attach_parser.add_argument("name", help="Name of the agent to attach to")

    # Kill
    kill_parser = subparsers.add_parser("kill", help="Kill an agent session")
    kill_parser.add_argument("name", help="Name of the agent to kill")

    # Inject
    inject_parser = subparsers.add_parser(
        "inject", help="Inject text into an active agent session"
    )
    inject_parser.add_argument("name", help="Name of the agent")
    inject_parser.add_argument("text", help="Text to inject")

    # MCP
    mcp_parser = subparsers.add_parser("mcp", help="Manage the background MCP service")
    mcp_parser.add_argument(
        "--external-unsafe",
        action="store_true",
        help="Bind to 0.0.0.0 (potentially unsafe)",
    )
    mcp_parser.add_argument(
        "--port", type=int, default=8000, help="Port to bind to (default: 8000)"
    )
    mcp_parser.add_argument(
        "--stdio", action="store_true", help="Run in stdio mode (for local AI agents)"
    )

    # Test
    test_parser = subparsers.add_parser(
        "test", help="Run system checks and functional tests"
    )
    test_parser.add_argument(
        "--full",
        action="store_true",
        help="Run full integration tests (for developers)",
    )

    args = parser.parse_args()

    if args.action == "spawn":
        spawn(args)
    elif args.action == "start":
        start(args)
    elif args.action in ("list", "ls", "ps"):
        list_agents(args)
    elif args.action == "tail":
        cmd_tail(args)
    elif args.action == "mcp":
        cmd_mcp(args)
    elif args.action == "inject":
        cmd_inject(args)
    elif args.action == "attach":
        attach(args)
    elif args.action == "kill":
        kill_agent(args)
    elif args.action == "test":
        test_pkood(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
