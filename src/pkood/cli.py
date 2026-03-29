import argparse
import subprocess
import os
import sys
import time
import json
import platform
import shutil
import re
from pathlib import Path

BASE_DIR = Path.home() / ".pkood"
SOCKETS_DIR = BASE_DIR / "sockets"
LOGS_DIR = BASE_DIR / "logs"
STATE_DIR = BASE_DIR / "state"


def strip_ansi(text):
    """Removes ANSI escape sequences (colors, cursor moves) from terminal output."""
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", text)


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


def ensure_dirs():
    for d in [SOCKETS_DIR, LOGS_DIR, STATE_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def get_tmux_cmd(agent_id):
    socket_path = SOCKETS_DIR / f"{agent_id}.sock"
    return ["tmux", "-S", str(socket_path)]


def auto_detect_agent():
    """Detects available AI CLI agents in the system PATH."""
    supported_agents = ["gemini", "claude", "aider"]
    found_agents = []
    for agent in supported_agents:
        if shutil.which(agent):
            found_agents.append(agent)
    return found_agents


def create_agent(agent_id, directory, command):
    ensure_dirs()

    socket_path = SOCKETS_DIR / f"{agent_id}.sock"
    log_path = LOGS_DIR / f"{agent_id}.log"

    if socket_path.exists():
        # Check if it's actually alive
        try:
            subprocess.run(
                get_tmux_cmd(agent_id) + ["ls"], capture_output=True, check=True
            )
            print(f"Error: Agent '{agent_id}' is already running.")
            return False
        except subprocess.CalledProcessError:
            # Socket is stale
            socket_path.unlink()

    # 1. Start detached tmux session
    tmux_base = get_tmux_cmd(agent_id)
    target_dir = str(Path(directory).resolve())

    # We explicitly set PKOOD_AGENT_ID so the child process knows who it is.
    # We also disable Gemini CLI folder trust for Pkood agents so MCP tools work immediately.
    try:
        subprocess.run(
            tmux_base
            + [
                "new-session",
                "-d",
                "-s",
                "main",
                "-c",
                target_dir,
                "-e",
                f"PKOOD_AGENT_ID={agent_id}",
                "-e",
                "GEMINI_SECURITY_FOLDER_TRUST_ENABLED=false",
                command,
            ],
            check=True,
        )
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
        with open(watcher_log, "w") as wl:
            subprocess.Popen(
                [sys.executable, str(watcher_script), agent_id],
                stdout=wl,
                stderr=wl,
                start_new_session=True,
            )
    return True


def spawn(args):
    if create_agent(args.name, args.dir, args.command):
        print(f"Started agent '{args.name}' in background.")


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


def kill_agent_by_id(agent_id):
    """Kills an agent by its ID and cleans up state files."""
    socket_path = SOCKETS_DIR / f"{agent_id}.sock"

    if not socket_path.exists():
        return False

    subprocess.run(get_tmux_cmd(agent_id) + ["kill-server"])
    if socket_path.exists():
        socket_path.unlink()

    # Also clean up state files
    for suffix in ["_meta.json", "_status.json"]:
        path = STATE_DIR / f"{agent_id}{suffix}"
        if path.exists():
            path.unlink()
    return True


def inject_text_to_agent(agent_id, text):
    """Sends text input to an active agent's tmux session."""
    socket_path = SOCKETS_DIR / f"{agent_id}.sock"
    if not socket_path.exists():
        return False

    # Check if alive
    try:
        subprocess.run(get_tmux_cmd(agent_id) + ["ls"], capture_output=True, check=True)
    except subprocess.CalledProcessError:
        return False

    # Send the keys. C-m is the tmux representation of the Enter key.
    try:
        subprocess.run(
            get_tmux_cmd(agent_id) + ["send-keys", "-t", "main", text, "C-m"],
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def cmd_inject(args):
    """The 'inject' command handler."""
    if inject_text_to_agent(args.name, args.text):
        print(f"Successfully injected text into agent '{args.name}'.")
    else:
        print(f"Error: Agent '{args.name}' not found or not active.")


def kill_agent(args):
    if kill_agent_by_id(args.name):
        print(f"Killed agent '{args.name}'.")
    else:
        print(f"Error: Agent '{args.name}' not found.")


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
    if not mcp_server_path.exists():
        # We will create this file in the next step
        pass

    try:
        env = os.environ.copy()
        # Ensure the current directory is in PYTHONPATH so mcp_server can import pkood.cli
        # The script is in src/pkood/cli.py, so parent.parent is src/
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


def ask_confirmation(prompt):
    """Asks the user for a yes/no confirmation."""
    while True:
        choice = input(f"{prompt} [y/N] ").lower().strip()
        if choice in ("y", "yes"):
            return True
        if choice in ("n", "no", ""):
            return False
        print("Please enter 'y' or 'n'.")


def fix_gemini_config():
    """Adds the Pkood MCP server to Gemini CLI settings."""
    settings_path = Path.home() / ".gemini" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    settings = {}
    if settings_path.exists():
        try:
            with open(settings_path, "r") as f:
                settings = json.load(f)
        except Exception as e:
            print(f"   Error reading Gemini settings: {e}")
            return False

    # Gemini CLI uses "mcpServers" at the top level
    if "mcpServers" not in settings:
        settings["mcpServers"] = {}

    settings["mcpServers"]["pkood"] = {"url": "http://127.0.0.1:8000/sse"}

    # Clean up old/wrong key if it exists from previous versions
    if (
        "mcp" in settings
        and "servers" in settings["mcp"]
        and "pkood" in settings["mcp"]["servers"]
    ):
        del settings["mcp"]["servers"]["pkood"]
        if not settings["mcp"]["servers"]:
            del settings["mcp"]["servers"]
        if not settings["mcp"]:
            del settings["mcp"]

    try:
        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
        print("   Gemini CLI configuration updated successfully.")
        return True
    except Exception as e:
        print(f"   Error writing Gemini settings: {e}")
        return False


def fix_claude_config():
    """Adds the Pkood MCP server to Claude Code config by editing ~/.claude.json directly."""
    config_path = Path.home() / ".claude.json"

    config = {}
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
        except Exception as e:
            print(f"   Error reading Claude configuration: {e}")
            return False

    # Claude Code uses "mcpServers" at the top level
    if "mcpServers" not in config:
        config["mcpServers"] = {}

    # For Claude Code (CLI), stdio is the most reliable transport
    config["mcpServers"]["pkood"] = {
        "command": sys.executable,
        "args": [str(Path(__file__).resolve().parent / "cli.py"), "mcp", "--stdio"],
    }

    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        print("   Claude Code configuration updated successfully (using stdio).")
        return True
    except Exception as e:
        print(f"   Error writing Claude configuration: {e}")
        return False


def install_pkood_skill(agent_type):
    """Installs the SKILL.md for the specified agent type."""
    skill_content = """---
name: pkood
description: Manage and orchestrate multiple background AI agents using Pkood.
---
# Pkood AgOps Manager Skill

You are a Fleet Manager for Pkood background agents. You have access to the `pkood` MCP server and its tools.

## CRITICAL MANDATE
When a user asks for a "pkood summary", "fleet status", or anything involving "pkood agents",
you **MUST NOT** use your standard codebase tools (like codebase_investigator).
Instead, you **MUST** use the `pkood` MCP tools.

## Your Mission
1. **Fleet Awareness**: Use `pkood:list_agents` and `pkood:tail_agents` to monitor the status of background tasks.
2. **Orchestration**: Use `pkood:spawn_agent` to create new background tasks.
3. **Recovery**: Use `pkood:inject_to_agent` to unblock agents waiting for input.
4. **Log Analysis**: Use `pkood:get_log_directory` to perform deep searches across the fleet's history.

## Standard Procedures
- When summarizing, use a concise plain ASCII table.
- If an agent is 'BLOCKED', always check its logs using `pkood:tail_agents` and try to understand why before reporting.
- You are running in an environment where folder trust is pre-authorized by Pkood.
"""
    if agent_type == "gemini":
        path = Path.home() / ".gemini" / "skills" / "pkood" / "SKILL.md"
    elif agent_type == "claude":
        path = Path.home() / ".claude" / "skills" / "pkood" / "SKILL.md"
    else:
        return False

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(skill_content)
        return True
    except Exception as e:
        print(f"   Error installing skill for {agent_type}: {e}")
        return False


def install_pkood_commands(agent_type):
    """Installs slash commands for the specified agent type."""
    status_prompt = (
        "Call the pkood:list_agents and pkood:tail_agents MCP tools. "
        "Analyze the output and provide a concise, one-sentence summary of what each active agent is currently doing. "
        "Present the final results in a plain ASCII table with columns: Agent ID, Status, and Summary. "
        "If an agent is BLOCKED, explicitly explain why in the Summary column."
    )

    start_prompt = (
        "You are tasked with starting a new background Pkood agent to fulfill the user's request.\n"
        "Follow these steps carefully:\n"
        "1. Analyze the user's request. If the request is ambiguous or missing critical details "
        "(e.g., what task to perform or which directory to use), stop and ask the user for clarification before proceeding.\n"
        "2. Once clear, determine:\n"
        "   - A short, unique name for the new agent.\n"
        "   - The target working directory (default to the current workspace root if unspecified).\n"
        "   - A comprehensive prompt that captures exactly what the user wants the agent to do.\n"
        "3. Use the `spawn_agent` tool to start the agent. For the command, use `gemini` or `claude` (default to the agent CLI you are currently using).\n"
        "4. Iteratively monitor the agent's startup using `tail_agents`.\n"
        '5. The newly spawned CLI will likely ask initial interactive questions (e.g., "Do you trust this folder?"). '
        "Use `inject_to_agent` to send 'y' (or other required inputs) to bypass these startup prompts.\n"
        "6. Continue checking `tail_agents` and injecting answers until you see a standard prompt indicating the agent is ready for instructions.\n"
        "7. Use `inject_to_agent` to send the comprehensive prompt you drafted in step 2.\n"
        "8. Verify the agent received the instruction, then report back to the user that the agent is successfully running in the background."
    )

    try:
        if agent_type == "gemini":
            # Status command
            status_path = Path.home() / ".gemini" / "commands" / "pkood" / "status.toml"
            status_path.parent.mkdir(parents=True, exist_ok=True)
            with open(status_path, "w") as f:
                f.write(
                    f'description = "Show the status of all Pkood agents"\nprompt = "{status_prompt}"\n'
                )

            # Start command
            start_path = Path.home() / ".gemini" / "commands" / "pkood" / "start.toml"
            start_path.parent.mkdir(parents=True, exist_ok=True)
            with open(start_path, "w") as f:
                f.write(
                    f'description = "Start a new Pkood agent session and assign it a task"\nprompt = """{start_prompt}"""\n'
                )
        elif agent_type == "claude":
            # Status command
            status_path = Path.home() / ".claude" / "commands" / "pkood:status.md"
            status_path.parent.mkdir(parents=True, exist_ok=True)
            with open(status_path, "w") as f:
                f.write(f"# /pkood:status\n{status_prompt}\n")

            # Start command
            start_path = Path.home() / ".claude" / "commands" / "pkood:start.md"
            start_path.parent.mkdir(parents=True, exist_ok=True)
            with open(start_path, "w") as f:
                f.write(f"# /pkood:start\n{start_prompt}\n")
        return True
    except Exception as e:
        print(f"   Error installing commands for {agent_type}: {e}")
        return False


def test_pkood(args):
    print("Running Pkood System Tests...\n")
    all_passed = True

    # 1. Environment Checks
    print("--- Environment Check ---")

    # Check OS / WSL
    sys_os = platform.system()
    print(f"Operating System: {sys_os}")
    if sys_os == "Windows":
        print("[!] Native Windows is not directly supported.")
        print("[!] Please run Pkood inside WSL2 (Windows Subsystem for Linux).")
        print("    Install WSL2: wsl --install")
        all_passed = False
    elif sys_os == "Linux" and "microsoft-standard" in platform.release().lower():
        print("WSL2 Environment detected: OK")

    # Check Tmux
    try:
        subprocess.run(["tmux", "-V"], capture_output=True, check=True)
        print("Tmux installation: OK")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("[!] Tmux is not installed or not in PATH.")
        if sys_os == "Darwin":
            print("    Install via Homebrew: brew install tmux")
        elif sys_os == "Linux":
            print("    Install via apt: sudo apt install tmux")
        all_passed = False

    # 2. AI Agent & MCP Checks
    print("\n--- AI Agent & MCP Check ---")

    # Gemini CLI
    gemini_path = shutil.which("gemini")
    if gemini_path:
        print(f"Gemini CLI found: {gemini_path}")
        settings_path = Path.home() / ".gemini" / "settings.json"
        configured = False
        if settings_path.exists():
            try:
                with open(settings_path, "r") as f:
                    settings = json.load(f)
                    # Check both for robustness, but Gemini CLI uses "mcpServers"
                    mcp_servers = settings.get("mcpServers", {})
                    if "pkood" in mcp_servers:
                        configured = True
            except Exception:
                pass

        if configured:
            print("   MCP Configuration: OK")
        else:
            print("   [!] MCP Configuration: MISSING")
            if ask_confirmation(
                "       Would you like to automatically configure Gemini CLI for Pkood?"
            ):
                fix_gemini_config()
            else:
                print("       Skipping Gemini CLI configuration.")

        # Skill & Command check
        skill_path = Path.home() / ".gemini" / "skills" / "pkood" / "SKILL.md"
        cmd_path = Path.home() / ".gemini" / "commands" / "pkood" / "status.toml"
        if skill_path.exists() and cmd_path.exists():
            print("   Pkood Skill & Commands: OK")
        else:
            print("   [!] Pkood Skill & Commands: MISSING")
            if ask_confirmation(
                "       Would you like to install Pkood Skills and Slash Commands for Gemini CLI?"
            ):
                install_pkood_skill("gemini")
                install_pkood_commands("gemini")
    else:
        print("Gemini CLI: Not found")

    # Claude Code
    claude_path = shutil.which("claude")
    if claude_path:
        print(f"Claude Code found: {claude_path}")
        config_path = Path.home() / ".claude.json"
        configured = False
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)
                    mcp_servers = config.get("mcpServers", {})
                    if "pkood" in mcp_servers:
                        configured = True
            except Exception:
                pass

        if configured:
            print("   MCP Configuration: OK")
        else:
            print("   [!] MCP Configuration: MISSING")
            if ask_confirmation(
                "       Would you like to automatically configure Claude Code for Pkood?"
            ):
                fix_claude_config()
            else:
                print("       Skipping Claude Code configuration.")

        # Skill & Command check
        skill_path = Path.home() / ".claude" / "skills" / "pkood" / "SKILL.md"
        cmd_path = Path.home() / ".claude" / "commands" / "pkood:status.md"
        if skill_path.exists() and cmd_path.exists():
            print("   Pkood Skill & Commands: OK")
        else:
            print("   [!] Pkood Skill & Commands: MISSING")
            if ask_confirmation(
                "       Would you like to install Pkood Skills and Slash Commands for Claude Code?"
            ):
                install_pkood_skill("claude")
                install_pkood_commands("claude")
    else:
        print("Claude Code: Not found")

    # 3. MCP Service Check
    print("\n--- MCP Service Check ---")
    pid_file = BASE_DIR / "mcp.pid"
    mcp_running = False
    if pid_file.exists():
        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            mcp_running = True
        except (ValueError, ProcessLookupError, PermissionError):
            pid_file.unlink()

    if mcp_running:
        print("MCP Service Status: RUNNING")
    else:
        print("   [!] MCP Service Status: NOT RUNNING")
        if ask_confirmation("       Would you like to start the MCP service now?"):
            # Create a mock args object for cmd_mcp
            mcp_args = argparse.Namespace(external_unsafe=False, port=8000)
            cmd_mcp(mcp_args)
            # Give it a second to start
            time.sleep(1)
        else:
            print("       Skipping MCP service startup.")

    if not all_passed:
        print(
            "\n[!] Pre-flight checks failed. Please resolve the issues above and try again."
        )
        return

    print("\n--- Functional Test ---")
    test_agent_id = "pkood-test-runner"

    # Make sure we're clean (silently)
    kill_args = argparse.Namespace(name=test_agent_id)
    socket_path = SOCKETS_DIR / f"{test_agent_id}.sock"
    if socket_path.exists():
        kill_agent(kill_args)

    print(f"1. Spawning background agent '{test_agent_id}'...")
    spawn_args = argparse.Namespace(name=test_agent_id, dir=".", command="sleep 5")
    spawn(spawn_args)

    # Give it a couple of seconds to boot and watcher to log
    time.sleep(2)

    print("2. Checking agent list...")
    # Read the state directly instead of using list_agents to avoid printing the whole table during a test
    socket_path = SOCKETS_DIR / f"{test_agent_id}.sock"
    if socket_path.exists():
        print("   Socket created: OK")
    else:
        print("   [!] Socket missing. Spawn failed.")
        all_passed = False

    try:
        subprocess.run(
            ["tmux", "-S", str(socket_path), "ls"], capture_output=True, check=True
        )
        print("   Session active: OK")
    except subprocess.CalledProcessError:
        print("   [!] Session not active. Spawn failed.")
        all_passed = False

    print("3. Checking watcher state...")
    state_path = STATE_DIR / f"{test_agent_id}_meta.json"
    if state_path.exists():
        print("   State file generated: OK")
    else:
        print("   [!] State file missing. Watcher failed to start or crashed.")
        all_passed = False

    print("4. Testing cleanup...")
    kill_agent(kill_args)
    if not socket_path.exists() and not state_path.exists():
        print("   Cleanup successful: OK")
    else:
        print("   [!] Socket remained after kill.")
        all_passed = False

    print("\n" + "=" * 30)
    if all_passed:
        print("ALL TESTS PASSED! Pkood is ready.")
    else:
        print("SOME TESTS FAILED.")
    print("=" * 30)


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
    subparsers.add_parser("test", help="Run system checks and functional tests")

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
