import subprocess
import os
import sys
import time
import json
import re
import platform
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


def get_agent_product(agent_type):
    """Factory to get the appropriate AgentProduct implementation."""
    if agent_type == "gemini":
        from pkood.gemini_cli import GeminiAgentProduct

        return GeminiAgentProduct()
    if agent_type == "claude":
        from pkood.claude_code import ClaudeAgentProduct

        return ClaudeAgentProduct()
    from pkood.generic_product import GenericAgentProduct

    return GenericAgentProduct()


def create_agent(agent_id, directory, command, foreground=False):
    ensure_dirs()

    socket_path = SOCKETS_DIR / f"{agent_id}.sock"
    log_path = LOGS_DIR / f"{agent_id}.log"
    meta_path = STATE_DIR / f"{agent_id}_meta.json"

    # Check if it's actually alive
    is_alive = False
    if socket_path.exists():
        try:
            # We use `tmux ls` (list-sessions) against the specific socket file
            # to definitively check if the tmux server is still alive and listening.
            subprocess.run(
                get_tmux_cmd(agent_id) + ["ls"], capture_output=True, check=True
            )
            is_alive = True
        except subprocess.CalledProcessError:
            socket_path.unlink()
    elif meta_path.exists():
        try:
            with open(meta_path, "r") as f:
                old_meta = json.load(f)
            if old_meta.get("mode") == "foreground" and old_meta.get("pid"):
                os.kill(int(old_meta["pid"]), 0)
                is_alive = True
        except (ProcessLookupError, ValueError, Exception):
            pass  # Stale meta or process dead

    if is_alive:
        print(
            f"Error: Agent '{agent_id}' is already running. Use --name to specify a different name."
        )
        return False

    # Determine agent type
    agent_type = "other"
    cmd_lower = command.lower()
    if "gemini" in cmd_lower:
        agent_type = "gemini"
    elif "claude" in cmd_lower:
        agent_type = "claude"

    target_dir = str(Path(directory).resolve())
    env = os.environ.copy()
    env["PKOOD_AGENT_ID"] = agent_id
    env["GEMINI_SECURITY_FOLDER_TRUST_ENABLED"] = "false"

    if foreground:
        try:
            # Determine platform to use the right `script` command flags
            if platform.system() == "Darwin":
                # macOS script command: -q for quiet, -t 0 to flush immediately
                script_cmd = [
                    "script",
                    "-q",
                    "-t",
                    "0",
                    str(log_path),
                    "bash",
                    "-c",
                    command,
                ]
            else:
                # Linux script command: -q for quiet, -c for command, -f for flush
                script_cmd = ["script", "-q", "-c", command, "-f", str(log_path)]

            proc = subprocess.Popen(script_cmd, cwd=target_dir, env=env)

            # 1. Start blocking foreground process
            meta = {
                "agent_id": agent_id,
                "type": agent_type,
                "mode": "foreground",
                "pid": proc.pid,
                "timestamp": time.time(),
                "status": "FOREGROUND",
                "update_ts": time.time(),
                "is_stuck": False,
                "last_output_snippet": "Running in foreground terminal (logs captured via script).",
            }
            with open(meta_path, "w") as f:
                json.dump(meta, f)

            proc.wait()
        except KeyboardInterrupt:
            pass
        finally:
            kill_agent_by_id(agent_id)
        return True
    else:
        # Write initial meta for tmux process
        meta = {
            "agent_id": agent_id,
            "type": agent_type,
            "mode": "tmux",
            "pid": None,
            "timestamp": time.time(),
            "status": "STARTING",
            "update_ts": time.time(),
            "is_stuck": False,
            "last_output_snippet": "",
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f)

        # 1. Start detached tmux session
        tmux_base = get_tmux_cmd(agent_id)
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
    mode_file = STATE_DIR / f"{agent_id}_mode.txt"
    is_foreground = mode_file.exists() and mode_file.read_text().strip() == "foreground"

    if is_foreground:
        pid_file = STATE_DIR / f"{agent_id}_pid.txt"
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                import signal

                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass
    else:
        socket_path = SOCKETS_DIR / f"{agent_id}.sock"
        if socket_path.exists():
            subprocess.run(get_tmux_cmd(agent_id) + ["kill-server"])
            socket_path.unlink(missing_ok=True)

    # Clean up all state files
    for suffix in ["_meta.json", "_status.json", "_type.txt", "_mode.txt", "_pid.txt"]:
        path = STATE_DIR / f"{agent_id}{suffix}"
        if path.exists():
            path.unlink(missing_ok=True)
    return True


def inject_text_to_agent(agent_id, text):
    """Sends text input to an active agent's tmux session."""
    # Read metadata to check mode and type
    agent_type = "other"
    meta_path = STATE_DIR / f"{agent_id}_meta.json"
    if meta_path.exists():
        try:
            with open(meta_path, "r") as f:
                meta = json.load(f)
                if meta.get("mode") == "foreground":
                    print(f"Cannot inject text into a foreground agent ({agent_id}).")
                    return False
                agent_type = meta.get("type", "other")
        except Exception:
            pass

    socket_path = SOCKETS_DIR / f"{agent_id}.sock"
    if not socket_path.exists():
        return False

    # Check if alive
    try:
        # We use `tmux ls` (list-sessions) against the specific socket file
        # to definitively check if the tmux server is still alive and listening.
        subprocess.run(get_tmux_cmd(agent_id) + ["ls"], capture_output=True, check=True)
    except subprocess.CalledProcessError:
        return False

    product = get_agent_product(agent_type)

    # Strip trailing newlines to avoid double-enter confusion
    text = text.rstrip("\r\n")

    try:
        short_responses = {"y", "n", "yes", "no", "1", "2", "3", "4", "5"}
        if text.strip().lower() in short_responses:
            # Short answers for Inquirer-style prompts: do NOT use bracketed paste
            # because the Escape sequence in bracketed paste cancels the prompt.
            # Just send the keys directly.
            subprocess.run(
                get_tmux_cmd(agent_id) + ["send-keys", "-t", "main", text],
                check=True,
            )
            # Add a tiny delay to allow Node.js UI frameworks (like Clack or Inquirer)
            # to process the character and update their internal selection state.
            time.sleep(0.1)
            subprocess.run(
                get_tmux_cmd(agent_id) + ["send-keys", "-t", "main", "C-m"],
                check=True,
            )
        else:
            # Use a uniquely named buffer to avoid collisions for multiline text
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

            # Delegate submission keystrokes to the specific product implementation
            product.perform_long_inject(agent_id, text, get_tmux_cmd)

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

    settings["mcpServers"]["pkood"] = {
        "command": sys.executable,
        "args": [str(Path(__file__).resolve().parent / "cli.py"), "mcp", "--stdio"],
    }

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
    from pkood.common import get_agent_product

    product = get_agent_product(agent_type)
    approve_example = product.approve_example

    status_prompt = (
        "Call the pkood:list_agents and pkood:tail_agents MCP tools. "
        "Analyze the output and provide a concise, one-sentence summary of what each active agent is currently doing. "
        "Present the final results in a plain ASCII table with columns: Agent ID, Status, and Summary. "
        "If an agent is BLOCKED, explicitly explain why in the Summary column. "
        "IMPORTANT: If an agent has `mode: foreground`, explicitly mention that it is running in the user's active "
        "terminal and cannot be controlled remotely via MCP."
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
        f'"Action Required"), use `inject_to_agent` to send the appropriate input (like {approve_example}) '
        "to unblock it.\n"
        "10. Verify the agent is actively working on the task and no longer BLOCKED, then report back to the "
        "user that the agent is successfully running in the background."
    )

    kill_prompt = (
        "You are tasked with killing a Pkood background agent.\n"
        "1. Identify the agent name provided by the user in their request.\n"
        "2. If no agent name is provided, ask the user to specify one "
        "(you can use `list_agents` to show them the active agents).\n"
        "3. Use the `kill_agent` MCP tool to terminate the specified agent.\n"
        "4. Confirm to the user that the agent has been killed."
    )

    review_prompt = (
        "You are acting as a Fleet Manager to triage blocked agents.\n"
        "1. Call `list_agents` to find all agents with status 'BLOCKED' or those that look stuck in their logs.\n"
        "2. For each such agent, call `tail_agents(name=agent_id)` to see exactly what tool or command "
        "it is waiting for approval on.\n"
        "3. Present a numbered ASCII table to the user with columns: #, Agent ID, Mode, and Pending Action.\n"
        "4. **CRITICAL**: If an agent has `mode: foreground`, you cannot unblock it. In the Pending Action column, "
        "write 'Manual Action Required in Terminal'.\n"
        "5. Ask the user: 'Which background (tmux) agents should I unblock? (Reply with numbers, or \"all\")'.\n"
        f"6. Once the user provides the numbers, use `inject_to_agent` to send {approve_example} to each "
        "of the selected background agents.\n"
        "7. Confirm to the user which background agents have been unblocked and remind them to check any "
        "foreground agents manually."
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

            # Kill command
            kill_path = Path.home() / ".gemini" / "commands" / "pkood" / "kill.toml"
            kill_path.parent.mkdir(parents=True, exist_ok=True)
            with open(kill_path, "w") as f:
                f.write(
                    'description = "Kill an active Pkood background agent"\n'
                    f'prompt = """{kill_prompt}"""\n'
                )

            # Review command
            review_path = Path.home() / ".gemini" / "commands" / "pkood" / "review.toml"
            review_path.parent.mkdir(parents=True, exist_ok=True)
            with open(review_path, "w") as f:
                f.write(
                    'description = "Review and unblock multiple agents at once"\n'
                    f'prompt = """{review_prompt}"""\n'
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

            # Kill command
            kill_path = Path.home() / ".claude" / "commands" / "pkood:kill.md"
            kill_path.parent.mkdir(parents=True, exist_ok=True)
            with open(kill_path, "w") as f:
                f.write(f"# /pkood:kill\n{kill_prompt}\n")

            # Review command
            review_path = Path.home() / ".claude" / "commands" / "pkood:review.md"
            review_path.parent.mkdir(parents=True, exist_ok=True)
            with open(review_path, "w") as f:
                f.write(f"# /pkood:review\n{review_prompt}\n")
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
