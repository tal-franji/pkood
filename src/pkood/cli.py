import argparse
import subprocess
import os
import sys
import time
import json
from pathlib import Path

BASE_DIR = Path.home() / ".pkood"
SOCKETS_DIR = BASE_DIR / "sockets"
LOGS_DIR = BASE_DIR / "logs"
STATE_DIR = BASE_DIR / "state"

def ensure_dirs():
    for d in [SOCKETS_DIR, LOGS_DIR, STATE_DIR]:
        d.mkdir(parents=True, exist_ok=True)

def get_tmux_cmd(agent_id):
    socket_path = SOCKETS_DIR / f"{agent_id}.sock"
    return ["tmux", "-S", str(socket_path)]

def create_agent(agent_id, directory, command):
    ensure_dirs()
    
    socket_path = SOCKETS_DIR / f"{agent_id}.sock"
    log_path = LOGS_DIR / f"{agent_id}.log"
    
    if socket_path.exists():
        # Check if it's actually alive
        try:
            subprocess.run(get_tmux_cmd(agent_id) + ["ls"], capture_output=True, check=True)
            print(f"Error: Agent '{agent_id}' is already running.")
            return False
        except subprocess.CalledProcessError:
            # Socket is stale
            socket_path.unlink()

    # 1. Start detached tmux session
    tmux_base = get_tmux_cmd(agent_id)
    target_dir = str(Path(directory).resolve())
    try:
        subprocess.run(tmux_base + ["new-session", "-d", "-s", "main", "-c", target_dir, command], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error starting tmux session: {e}")
        return False

    # 2. Setup pipe-pane for continuous logging
    pipe_cmd = f"cat >> {log_path}"
    subprocess.run(tmux_base + ["pipe-pane", "-t", "main", pipe_cmd], check=True)

    # 3. Start the watcher in the background
    watcher_script = Path(__file__).parent / "pkood_watcher.py"
    watcher_log = LOGS_DIR / f"{agent_id}_watcher.log"
    if watcher_script.exists():
        with open(watcher_log, 'w') as wl:
            subprocess.Popen([sys.executable, str(watcher_script), agent_id], 
                             stdout=wl, stderr=wl, start_new_session=True)
    return True

def spawn(args):
    if create_agent(args.name, args.dir, args.command):
        print(f"Started agent '{args.name}' in background.")

def start(args):
    agent_id = args.name
    if not agent_id:
        # Default name to current directory name
        agent_id = Path(args.dir).resolve().name
    
    # Use user's shell or default to bash
    shell = os.environ.get("SHELL", "bash")
    
    if create_agent(agent_id, args.dir, shell):
        print(f"Starting interactive session for '{agent_id}'...")
        # Give a tiny bit of time for tmux to initialize before attaching
        time.sleep(0.1)
        socket_path = SOCKETS_DIR / f"{agent_id}.sock"
        os.execvp("tmux", ["tmux", "-S", str(socket_path), "attach", "-t", "main"])

def list_agents(args):
    ensure_dirs()
    sockets = list(SOCKETS_DIR.glob("*.sock"))
    if not sockets:
        print("No active agents found.")
        return

    print(f"{'AGENT ID':<20} | {'STATUS':<10} | {'LOG SIZE':<10}")
    print("-" * 45)
    
    for sock in sockets:
        agent_id = sock.stem
        log_path = LOGS_DIR / f"{agent_id}.log"
        state_path = STATE_DIR / f"{agent_id}_meta.json"
        
        log_size = f"{log_path.stat().st_size / 1024:.1f} KB" if log_path.exists() else "0 KB"
        
        status = "UNKNOWN"
        if state_path.exists():
            try:
                with open(state_path, 'r') as f:
                    meta = json.load(f)
                    status = meta.get("status", "UNKNOWN")
            except Exception:
                pass
        
        # Cross-check with tmux
        try:
            subprocess.run(get_tmux_cmd(agent_id) + ["ls"], capture_output=True, check=True)
            if status == "UNKNOWN":
                status = "RUNNING"
        except subprocess.CalledProcessError:
            status = "EXITED"
            
        print(f"{agent_id:<20} | {status:<10} | {log_size:<10}")

def attach(args):
    agent_id = args.name
    socket_path = SOCKETS_DIR / f"{agent_id}.sock"
    
    if not socket_path.exists():
        print(f"Error: Agent '{agent_id}' not found.")
        return

    print(f"Attaching to '{agent_id}'... (Press Ctrl+B then D to detach)")
    os.execvp("tmux", ["tmux", "-S", str(socket_path), "attach", "-t", "main"])

def kill_agent(args):
    agent_id = args.name
    socket_path = SOCKETS_DIR / f"{agent_id}.sock"
    
    if not socket_path.exists():
        print(f"Error: Agent '{agent_id}' not found.")
        return

    subprocess.run(get_tmux_cmd(agent_id) + ["kill-server"])
    if socket_path.exists():
        socket_path.unlink()
    
    # Also clean up state file
    state_path = STATE_DIR / f"{agent_id}_meta.json"
    if state_path.exists():
        state_path.unlink()
        
    print(f"Killed agent '{agent_id}'.")

def main():
    parser = argparse.ArgumentParser(description="Pkood: Agentic Operations Orchestrator")
    subparsers = parser.add_subparsers(dest="action", help="Commands")

    # Spawn
    spawn_parser = subparsers.add_parser("spawn", help="Spawn a new agent")
    spawn_parser.add_argument("--name", required=True, help="Unique name for the agent")
    spawn_parser.add_argument("--dir", default=".", help="Directory to run the command in")
    spawn_parser.add_argument("command", help="The command to run")

    # Start
    start_parser = subparsers.add_parser("start", help="Start an interactive shell session and attach")
    start_parser.add_argument("--name", help="Unique name (defaults to directory name)")
    start_parser.add_argument("--dir", default=".", help="Directory to start in")

    # List
    subparsers.add_parser("list", aliases=["ls", "ps"], help="List all running agents")

    # Attach
    attach_parser = subparsers.add_parser("attach", help="Attach to an agent session")
    attach_parser.add_argument("name", help="Name of the agent to attach to")

    # Kill
    kill_parser = subparsers.add_parser("kill", help="Kill an agent session")
    kill_parser.add_argument("name", help="Name of the agent to kill")

    args = parser.parse_args()

    if args.action == "spawn":
        spawn(args)
    elif args.action == "start":
        start(args)
    elif args.action in ("list", "ls", "ps"):
        list_agents(args)
    elif args.action == "attach":
        attach(args)
    elif args.action == "kill":
        kill_agent(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
