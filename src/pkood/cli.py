from typing import Any, Union
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
    check_os_compatibility,
)
from pkood.tester import test_pkood


def get_json_properly(
    filename: Union[str, Path], names: Union[str, list[str]], default=None
) -> Any:
    result = default
    if isinstance(names, str):
        names = [names]
    filename_path = Path(filename)
    if filename_path.exists():
        try:
            with open(filename_path, "r") as f:
                jobj = json.load(f)
                for name in names:
                    if name in jobj:
                        result = jobj[name]
                        break
        except Exception:
            pass
    return result


def get_agents_status(hide_old_exited=True):
    """Returns structured metadata for all agents."""
    ensure_dirs()

    # Gather all agent IDs from state files or sockets
    agent_ids = set()
    for p in STATE_DIR.glob("*_meta.json"):
        agent_ids.add(p.name.replace("_meta.json", ""))
    for p in SOCKETS_DIR.glob("*.sock"):
        agent_ids.add(p.stem)

    results = []
    current_time = time.time()

    for agent_id in agent_ids:
        log_path = LOGS_DIR / f"{agent_id}.log"
        meta_path = STATE_DIR / f"{agent_id}_meta.json"
        status_path = STATE_DIR / f"{agent_id}_status.json"

        # 1. Get Mechanical Status (from watcher)
        status = get_json_properly(meta_path, "status", "UNKNOWN")
        is_foreground = get_json_properly(meta_path, "mode", "") == "foreground"

        log_size = (
            f"{log_path.stat().st_size / 1024:.1f}K" if log_path.exists() else "0K"
        )

        if is_foreground:
            pid = get_json_properly(meta_path, "pid")
            if pid:
                try:
                    os.kill(int(pid), 0)
                    status = "FOREGROUND"
                except (ProcessLookupError, ValueError):
                    status = "EXITED"
            else:
                if status != "EXITED":
                    status = "EXITED"
        else:
            # Cross-check with tmux
            try:
                # We use `tmux ls` (list-sessions) against the specific socket file
                # to definitively check if the tmux server is still alive and listening.
                subprocess.run(
                    get_tmux_cmd(agent_id) + ["ls"], capture_output=True, check=True
                )
                if status == "UNKNOWN":
                    status = "RUNNING"
            except subprocess.CalledProcessError:
                status = "EXITED"

        # Filter out old EXITED agents
        if hide_old_exited and status == "EXITED":
            # For foreground agents, use meta_path mtime since they don't have logs
            check_path = log_path if log_path.exists() else meta_path
            last_modified = check_path.stat().st_mtime if check_path.exists() else 0
            if (current_time - last_modified) > 3600:
                continue

        # 2. Get Semantic Focus (from agent)
        focus = get_json_properly(status_path, ["current_focus", "status_message"], "")

        results.append(
            {
                "agent_id": agent_id,
                "status": status,
                "mode": get_json_properly(meta_path, "mode", "tmux"),
                "log_size": log_size,
                "focus": focus,
            }
        )
    return results


def get_all_tails(include_summarizer=False, filter_id=None):
    """Returns a dictionary of agent IDs and their cleaned tail output."""
    ensure_dirs()

    # Gather all agent IDs
    agent_ids = set()
    for p in STATE_DIR.glob("*_meta.json"):
        agent_ids.add(p.name.replace("_meta.json", ""))
    for p in SOCKETS_DIR.glob("*.sock"):
        agent_ids.add(p.stem)

    tails = {}

    for agent_id in agent_ids:
        if filter_id and agent_id != filter_id:
            continue
        if not include_summarizer and agent_id == "pkood-summarizer":
            continue

        meta_path = STATE_DIR / f"{agent_id}_meta.json"
        is_foreground = get_json_properly(meta_path, "mode", "") == "foreground"

        # Get total lines from the log file
        total_lines = 0
        log_path = LOGS_DIR / f"{agent_id}.log"
        if log_path.exists():
            try:
                with open(log_path, "rb") as f:
                    total_lines = sum(1 for _ in f)
            except Exception:
                pass

        if is_foreground:
            # Foreground agents have no tmux pane, so we just read the raw log file tail directly
            if log_path.exists():
                try:
                    with open(log_path, "r", errors="ignore") as f:
                        lines = f.readlines()
                        raw_output = "".join(lines[-50:])
                except Exception:
                    raw_output = "Error reading log."
            else:
                raw_output = "No output available."
        else:
            # Check if alive
            try:
                # We use `tmux ls` (list-sessions) against the specific socket file
                # to definitively check if the tmux server is still alive and listening.
                subprocess.run(
                    get_tmux_cmd(agent_id) + ["ls"], capture_output=True, check=True
                )
            except subprocess.CalledProcessError:
                continue  # Skip dead agents

            # Capture Pane
            try:
                capture_cmd = get_tmux_cmd(agent_id) + [
                    "capture-pane",
                    "-p",
                    "-t",
                    "main",
                ]
                result = subprocess.run(
                    capture_cmd, capture_output=True, text=True, check=True
                )
                raw_output = result.stdout
            except subprocess.CalledProcessError:
                raw_output = "No output available."

        recent_lines = "\n".join(raw_output.splitlines()[-50:])
        clean_text = strip_ansi(recent_lines)
        tails[agent_id] = f"[Total Lines: {total_lines}]\n{clean_text}"
    return tails


def cmd_tail(args):
    """The 'tail' command: outputs the last 50 lines of logs for all active agents."""
    tails = get_all_tails(filter_id=args.name)
    if not tails:
        if args.name:
            print(f"Agent '{args.name}' not found or not active.")
        else:
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

    # Check if a specific command was requested
    if hasattr(args, "cmd") and args.cmd:
        launch_cmd = args.cmd
        print(f"Using requested agent command: {launch_cmd}")
    else:
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

    is_foreground = getattr(args, "foreground", False)
    if create_agent(agent_id, args.dir, launch_cmd, foreground=is_foreground):
        if not is_foreground:
            print(f"Starting interactive session for '{agent_id}'...")
            # Give a tiny bit of time for tmux to initialize before attaching
            time.sleep(0.1)
            socket_path = SOCKETS_DIR / f"{agent_id}.sock"
            os.execvp("tmux", ["tmux", "-S", str(socket_path), "attach", "-t", "main"])


def list_agents(args):
    hide_old_exited = not getattr(args, "all", False)
    is_tab = getattr(args, "tab", False)
    agents = get_agents_status(hide_old_exited=hide_old_exited)
    if not agents:
        if not is_tab:
            if hide_old_exited:
                print("No active or recently exited agents found (use --all to show all).")
            else:
                print("No agents found.")
        return

    if is_tab:
        for a in agents:
            print(f"{a['agent_id']}\t{a['status']}\t{a['log_size']}")
    else:
        print(f"{'AGENT ID':<20} | {'STATUS':<10} | {'LOG'}")
        print("-" * 50)
        for a in agents:
            print(f"{a['agent_id']:<20} | {a['status']:<10} | {a['log_size']}")


def attach(args):
    agent_id = args.name

    meta_path = STATE_DIR / f"{agent_id}_meta.json"
    is_foreground = get_json_properly(meta_path, "mode", "") == "foreground"

    if is_foreground:
        print(f"Cannot attach to a foreground agent ('{agent_id}').")
        return

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
    start_parser.add_argument(
        "--cmd",
        help="Specific CLI command to launch (e.g., 'gemini', 'claude'). "
        "If omitted, auto-detects or falls back to shell.",
    )
    start_parser.add_argument(
        "--foreground",
        "--fg",
        action="store_true",
        help="Run the agent directly in the foreground (no tmux). Attach/detach/inject will be disabled.",
    )
    # List
    list_parser = subparsers.add_parser(
        "list", aliases=["ls", "ps"], help="List all running agents"
    )
    list_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Show all agents, including old EXITED ones",
    )
    list_parser.add_argument(
        "--tab",
        action="store_true",
        help="Output as plain tab-separated list without headers",
    )

    # Tail
    tail_parser = subparsers.add_parser(
        "tail", help="Output the last 50 lines of logs for all active agents"
    )
    tail_parser.add_argument("name", nargs="?", help="Optional name of the agent")

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
        check_os_compatibility("spawn")
        spawn(args)
    elif args.action == "start":
        check_os_compatibility("spawn") # start uses tmux spawn
        start(args)
    elif args.action in ("list", "ls", "ps"):
        list_agents(args)
    elif args.action == "tail":
        cmd_tail(args)
    elif args.action == "mcp":
        cmd_mcp(args)
    elif args.action == "inject":
        check_os_compatibility("inject")
        cmd_inject(args)
    elif args.action == "attach":
        check_os_compatibility("attach")
        attach(args)
    elif args.action == "kill":
        kill_agent(args)
    elif args.action == "test":
        check_os_compatibility("spawn")
        test_pkood(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
