import subprocess
import time
import json
import platform
import shutil
import os
from pathlib import Path
from pkood.common import (
    BASE_DIR,
    SOCKETS_DIR,
    LOGS_DIR,
    STATE_DIR,
    create_agent,
    kill_agent_by_id,
    inject_text_to_agent,
    ask_confirmation,
    install_pkood_skill,
    install_pkood_commands,
    fix_gemini_config,
    fix_claude_config,
)


def run_full_integration_tests():
    """Runs end-to-end integration tests involving agent creation, text injection, and skills."""
    print("\n--- Full Integration Tests ---")
    all_passed = True
    full_agent_id = "pk_full_test_agent"
    sub_agent_id = "pk_sub_agent_test"

    # Cleanup any previous run artifacts
    kill_agent_by_id(full_agent_id)
    kill_agent_by_id(sub_agent_id)

    print(f"Starting test agent '{full_agent_id}' with Gemini CLI...")
    if create_agent(full_agent_id, str(Path.cwd()), "gemini"):
        print("   Waiting 5 seconds for Gemini CLI to initialize...")
        time.sleep(5)

        print("   Testing text injection (simple echo)...")
        inject_text_to_agent(full_agent_id, "run bash -c 'echo PK_MAGIC_INJECT'")
        print("   Waiting 10 seconds for execution/prompt...")
        time.sleep(10)

        print("   Injecting '2' to approve tool execution for session...")
        inject_text_to_agent(full_agent_id, "2")
        print("   Waiting 5 seconds for completion...")
        time.sleep(5)

        log_path = LOGS_DIR / f"{full_agent_id}.log"
        log_content = log_path.read_text(errors="ignore") if log_path.exists() else ""

        if "PK_MAGIC_INJECT" in log_content:
            print("   [OK] Text injection and execution verified.")
        else:
            print("   [!] Text injection failed.")
            all_passed = False

        print("   Testing /pkood:status skill...")
        inject_text_to_agent(full_agent_id, "/pkood:status")
        print("   Waiting 15 seconds for skill execution...")
        time.sleep(15)

        print("   (Injecting '2' to approve MCP tool execution for session...)")
        inject_text_to_agent(full_agent_id, "2")
        time.sleep(10)

        log_content = log_path.read_text(errors="ignore") if log_path.exists() else ""
        if full_agent_id in log_content and "STATUS" in log_content.upper():
            print("   [OK] /pkood:status skill verified.")
        else:
            print("   [!] /pkood:status skill failed or timed out.")
            all_passed = False

        print("   Testing /pkood:start skill...")
        task_prompt = (
            f"/pkood:start\nSpawn a new agent named '{sub_agent_id}' "
            "to write a python script that prints 'Hello Pkood'."
        )
        inject_text_to_agent(full_agent_id, task_prompt)
        print(
            "   Waiting 40 seconds for sub-agent to be spawned (this may take a bit)..."
        )

        for _ in range(13):
            time.sleep(3)
            state_file = STATE_DIR / f"{full_agent_id}_meta.json"
            if state_file.exists():
                try:
                    with open(state_file) as f:
                        meta = json.load(f)
                    if meta.get("status") == "BLOCKED":
                        print(
                            "   (Agent is BLOCKED, injecting '2' to allow tool for session)"
                        )
                        inject_text_to_agent(full_agent_id, "2")
                except Exception:
                    pass

        sub_socket_path = SOCKETS_DIR / f"{sub_agent_id}.sock"
        if sub_socket_path.exists():
            print("   [OK] /pkood:start skill successfully spawned the sub-agent.")
        else:
            print("   [!] /pkood:start skill failed to spawn the sub-agent.")
            if log_path.exists():
                print("   --- Tail of failed agent log ---")
                lines = log_path.read_text(errors="ignore").splitlines()[-20:]
                print("\n".join(lines))
            all_passed = False

        print("   Cleaning up full test agent and sub-agent...")
        kill_agent_by_id(full_agent_id)
        kill_agent_by_id(sub_agent_id)

    else:
        print("   [!] Failed to start full test agent.")
        all_passed = False

    return all_passed


def test_pkood(args):
    # We need to import these here or they will be circular if we put them at the top
    # but wait, tester.py doesn't need to import from cli.py anymore!
    from pkood.common import kill_agent_by_id

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
            # Always update to ensure latest version
            install_pkood_skill("gemini")
            install_pkood_commands("gemini")
            print("   Pkood Skill & Commands: OK")
        else:
            print("   [!] Pkood Skill & Commands: MISSING")
            if ask_confirmation(
                "       Would you like to install Pkood Skills and Slash Commands for Gemini CLI?"
            ):
                install_pkood_skill("gemini")
                install_pkood_commands("gemini")
                print("   Pkood Skill & Commands: OK")
            else:
                print("       Skipping Pkood Skill & Commands installation.")
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
            # Always update to ensure latest version
            install_pkood_skill("claude")
            install_pkood_commands("claude")
            print("   Pkood Skill & Commands: OK")
        else:
            print("   [!] Pkood Skill & Commands: MISSING")
            if ask_confirmation(
                "       Would you like to install Pkood Skills and Slash Commands for Claude Code?"
            ):
                install_pkood_skill("claude")
                install_pkood_commands("claude")
                print("   Pkood Skill & Commands: OK")
            else:
                print("       Skipping Pkood Skill & Commands installation.")
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
            # Use subprocess to call the CLI instead of importing cmd_mcp to avoid circularity
            # Actually, common.py doesn't have cmd_mcp.
            # We can use subprocess.run([sys.executable, "-m", "pkood.cli", "mcp"])
            print("       Please start it using: pkood mcp --stdio")
            all_passed = False
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
    socket_path = SOCKETS_DIR / f"{test_agent_id}.sock"
    if socket_path.exists():
        kill_agent_by_id(test_agent_id)

    print(f"1. Spawning background agent '{test_agent_id}'...")
    if create_agent(test_agent_id, ".", "sleep 5"):
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
        kill_agent_by_id(test_agent_id)
        if not socket_path.exists() and not state_path.exists():
            print("   Cleanup successful: OK")
        else:
            print("   [!] Socket remained after kill.")
            all_passed = False
    else:
        print("   [!] Failed to spawn test agent.")
        all_passed = False

    if getattr(args, "full", False) and all_passed:
        integration_passed = run_full_integration_tests()
        all_passed = all_passed and integration_passed

    print("\n" + "=" * 30)
    if all_passed:
        print("ALL TESTS PASSED! Pkood is ready.")
    else:
        print("SOME TESTS FAILED.")
    print("=" * 30)
