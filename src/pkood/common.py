import subprocess
import sys
import time
import json
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

    # Strip trailing newlines to avoid double-enter confusion
    text = text.rstrip("\r\n")

    try:
        # Use a uniquely named buffer to avoid collisions
        buf_name = f"pkood_{agent_id}_inject"
        subprocess.run(
            get_tmux_cmd(agent_id) + ["set-buffer", "-b", buf_name, text],
            check=True,
        )
        # Paste the buffer with -p for bracketed paste
        subprocess.run(
            get_tmux_cmd(agent_id)
            + ["paste-buffer", "-b", buf_name, "-p", "-t", "main"],
            check=True,
        )

        short_responses = {"y", "n", "yes", "no", "1", "2", "3", "4", "5"}
        if text.strip().lower() in short_responses:
            # Short answers for Inquirer-style prompts: just send Enter
            subprocess.run(
                get_tmux_cmd(agent_id) + ["send-keys", "-t", "main", "C-m"],
                check=True,
            )
        else:
            # Long prompts for prompt_toolkit: require Escape then Enter
            time.sleep(0.1)
            subprocess.run(
                get_tmux_cmd(agent_id) + ["send-keys", "-t", "main", "Escape"],
                check=True,
            )
            time.sleep(0.2)
            subprocess.run(
                get_tmux_cmd(agent_id) + ["send-keys", "-t", "main", "C-m"],
                check=True,
            )

        # Cleanup buffer
        subprocess.run(
            get_tmux_cmd(agent_id) + ["delete-buffer", "-b", buf_name],
            check=False,  # Ignore if it fails
        )
        return True
    except subprocess.CalledProcessError:
        return False


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
        "(e.g., what task to perform or which directory to use), stop and ask the user for clarification "
        "before proceeding.\n"
        "2. Once clear, determine:\n"
        "   - A short, unique name for the new agent.\n"
        "   - The target working directory (default to the current workspace root if unspecified).\n"
        "   - A comprehensive prompt that captures exactly what the user wants the agent to do.\n"
        "3. Use the `spawn_agent` tool to start the agent. For the command, use `gemini` or `claude` "
        "(default to the agent CLI you are currently using).\n"
        "4. Iteratively monitor the agent's startup using `tail_agents`.\n"
        '5. The newly spawned CLI will likely ask initial interactive questions (e.g., "Do you trust this folder?"). '
        "Use `inject_to_agent` to send 'y' (or other required inputs) to bypass these startup prompts.\n"
        "6. Continue checking `tail_agents` and injecting answers until you see a standard prompt indicating "
        "the agent is ready for instructions.\n"
        "7. Use `inject_to_agent` to send the comprehensive prompt you drafted in step 2.\n"
        "8. Check `list_agents` and `tail_agents` again after a brief wait to ensure the agent has started "
        "processing the prompt and is not BLOCKED.\n"
        '9. If the agent becomes BLOCKED asking for tool execution approval (e.g., "Allow execution of:", '
        "\"Action Required\"), use `inject_to_agent` to send the appropriate input (like '1' or '2' for "
        "allow once/session) to unblock it.\n"
        "10. Verify the agent is actively working on the task and no longer BLOCKED, then report back to the "
        "user that the agent is successfully running in the background."
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
                    'description = "Start a new Pkood agent session and assign it a task"\n'
                    f'prompt = """{start_prompt}"""\n'
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


def spawn(args):
    if create_agent(args.name, args.dir, args.command):
        print(f"Started agent '{args.name}' in background.")


def kill_agent(args):
    if kill_agent_by_id(args.name):
        print(f"Killed agent '{args.name}'.")
    else:
        print(f"Error: Agent '{args.name}' not found.")
