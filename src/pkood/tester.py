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


def verify_injection(agent_id, text, timeout=60):
    """
    Injects text and verifies it was actually submitted.
    """
    state_file = STATE_DIR / f"{agent_id}_meta.json"
    log_path = LOGS_DIR / f"{agent_id}.log"

    # Baseline log size
    baseline_size = log_path.stat().st_size if log_path.exists() else 0

    try:
        meta = json_file(state_file)
        baseline_ts = meta.get("timestamp", 0)
    except Exception:
        baseline_ts = 0

    print(f"   Injecting: {text.splitlines()[0]}...")
    if not inject_text_to_agent(agent_id, text):
        print("   [!] Failed to call inject_text_to_agent.")
        return False

    # Wait for evidence of processing
    success = False
    for _ in range(timeout // 2):
        time.sleep(2)
        try:
            current_size = log_path.stat().st_size if log_path.exists() else 0
            meta = json_file(state_file)
            current_status = meta.get("status")
            current_ts = meta.get("timestamp", 0)

            # Evidence of success:
            # 1. Log size increased significantly (agent outputting stuff)
            # 2. Status moved to RUNNING or BLOCKED
            if current_size > baseline_size + 10:
                success = True
                break
            if current_ts > baseline_ts and current_status in ("RUNNING", "BLOCKED"):
                success = True
                break
        except Exception:
            pass

    if not success:
        print(f"   [!] Injection verification failed for: {text.splitlines()[0]}")
    return success


def wait_for_idle(agent_id, timeout=60, label="Stabilizing"):
    """Waits for the agent to reach the IDLE state, handling blockers along the way."""
    state_file = STATE_DIR / f"{agent_id}_meta.json"
    print(f"   Waiting for {agent_id} to become IDLE ({label})...")
    for i in range(timeout // 2):
        time.sleep(2)
        try:
            meta = json_file(state_file)
            status = meta.get("status")
            if status == "IDLE":
                return True
            if status == "BLOCKED":
                print("   (Agent is BLOCKED, injecting '2' to unblock)")
                inject_text_to_agent(agent_id, "2")
                time.sleep(5)
            elif i % 5 == 0:
                print(f"   (Still waiting... status: {status})")
        except Exception:
            pass

    print(f"   [!] Timeout: Agent '{agent_id}' did not become IDLE during '{label}'.")
    return False


def run_gemini_integration_tests():
    """Runs end-to-end integration tests for Gemini CLI."""
    return run_agent_integration_suite("gemini", "Gemini")


def run_claude_integration_tests():
    """Runs end-to-end integration tests for Claude Code."""
    return run_agent_integration_suite("claude", "Claude")


def run_agent_integration_suite(agent_cmd, display_name):
    """Generic test suite for any agent."""
    print(f"\n--- Full Integration Tests ({display_name}) ---")
    all_passed = True
    full_agent_id = f"pk_full_{agent_cmd}"
    sub_agent_id = f"pk_sub_{agent_cmd}"
    log_path = LOGS_DIR / f"{full_agent_id}.log"
    state_file = STATE_DIR / f"{full_agent_id}_meta.json"

    # Cleanup any previous run artifacts
    kill_agent_by_id(full_agent_id)
    kill_agent_by_id(sub_agent_id)
    time.sleep(1)

    print(f"Starting test agent '{full_agent_id}' with {display_name}...")
    if not create_agent(full_agent_id, str(Path.cwd()), agent_cmd):
        print(f"   [!] Failed to start {display_name} agent.")
        all_passed = False

    # 1. Startup
    if not wait_for_idle(full_agent_id, timeout=60, label="Startup"):
        print("   [!] Timeout: Agent did not become IDLE on startup.")
        all_passed = False

    # 2. Phase 1: Rigorous Injection Testing
    if all_passed:
        print("   --- Phase 1: Rigorous Injection Testing ---")

        # Test 1: Single line
        if not verify_injection(full_agent_id, "run bash -c 'echo PK_SINGLE_LINE'"):
            all_passed = False

        if all_passed and not wait_for_idle(
            full_agent_id, timeout=60, label="After Single Line"
        ):
            all_passed = False

        # Test 2: Multiline
        multiline_test = "run bash -c 'echo PK_MULTILINE_1 && echo PK_MULTILINE_2'"
        if all_passed and not verify_injection(full_agent_id, multiline_test):
            all_passed = False

        if all_passed and not wait_for_idle(
            full_agent_id, timeout=60, label="After Multiline"
        ):
            all_passed = False

        # Test 3: Realistic Massive Multiline
        massive_test = (
            "Create a Python script named `perfect_numbers.py` that finds and prints "
            "the first 4 perfect numbers. Include a brief explanation in comments and test it to ensure correctness.\n"
            "run bash -c 'echo PK_MASSIVE_SUCCESS'"
        )
        if all_passed and not verify_injection(full_agent_id, massive_test):
            all_passed = False

        if all_passed and not wait_for_idle(
            full_agent_id, timeout=80, label="After Massive Multiline"
        ):
            all_passed = False

        # Final check of logs for phase 1
        time.sleep(2)  # Give the pipe-pane a second to flush
        log_content = log_path.read_text(errors="ignore") if log_path.exists() else ""
        if (
            all_passed
            and "PK_MULTILINE_2" in log_content
            and "PK_MASSIVE_SUCCESS" in log_content
        ):
            print("   [OK] Injection Phase 1 verified.")
        else:
            print("   [!] Injection Phase 1 verification failed.")
            all_passed = False

    # 3. Phase 2: Skills Testing
    if all_passed:
        print("   --- Phase 2: Skills Testing ---")

        # Status Skill
        if not verify_injection(full_agent_id, "/pkood:status"):
            all_passed = False

        if all_passed and not wait_for_idle(
            full_agent_id, timeout=40, label="After Status Skill"
        ):
            all_passed = False

        log_content = log_path.read_text(errors="ignore") if log_path.exists() else ""
        if "STATUS" in log_content.upper():
            print("   [OK] /pkood:status skill verified.")
        else:
            print("   [!] /pkood:status skill failed or timed out.")
            all_passed = False

        # Start Skill
        if all_passed:
            print("\n   Testing /pkood:start skill...")
            task_prompt = (
                f"/pkood:start\nSpawn a new agent named '{sub_agent_id}' "
                "to write a python script that prints 'Hello Pkood'."
            )
            if not verify_injection(full_agent_id, task_prompt):
                all_passed = False

            # Wait for sub-agent socket
            print(f"   Waiting for sub-agent {sub_agent_id} to appear...")
            sub_socket_path = SOCKETS_DIR / f"{sub_agent_id}.sock"
            sub_spawned = False
            for _ in range(30):
                if sub_socket_path.exists():
                    sub_spawned = True
                    break
                time.sleep(2)
                # Check for blockers on main agent while waiting
                try:
                    m = json_file(state_file)
                    if m.get("status") == "BLOCKED":
                        print("   (Main agent BLOCKED, injecting '2')")
                        inject_text_to_agent(full_agent_id, "2")
                except Exception:
                    pass

            if sub_spawned:
                print("   [OK] /pkood:start skill successfully spawned the sub-agent.")
            else:
                print("   [!] /pkood:start skill failed to spawn the sub-agent.")
                all_passed = False

            # Return to IDLE
            if all_passed and not wait_for_idle(
                full_agent_id, timeout=40, label="Final Cleanup"
            ):
                all_passed = False

    print(f"   Cleaning up {display_name} test agent and sub-agent...")
    kill_agent_by_id(full_agent_id)
    kill_agent_by_id(sub_agent_id)

    return all_passed


def poll_file_sleep(file_path, timeout=10, interval=1):
    """Polls a file for existence, sleeping for `interval` seconds between checks, up to `timeout` seconds."""
    for _ in range(timeout // interval):
        time.sleep(interval)
        if file_path.exists():
            yield True


def json_file(filename):
    with open(filename) as f:
        return json.load(f)


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
                settings = json_file(settings_path)
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
        kill_path = Path.home() / ".gemini" / "commands" / "pkood" / "kill.toml"
        review_path = Path.home() / ".gemini" / "commands" / "pkood" / "review.toml"
        if (
            skill_path.exists()
            and cmd_path.exists()
            and kill_path.exists()
            and review_path.exists()
        ):
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
    # Support both global and local bin
    claude_path = shutil.which("claude")
    if not claude_path:
        local_claude = Path.home() / ".local" / "bin" / "claude"
        if local_claude.exists():
            claude_path = str(local_claude)

    if claude_path:
        print(f"Claude Code found: {claude_path}")
        config_path = Path.home() / ".claude.json"
        configured = False
        if config_path.exists():
            try:
                config = json_file(config_path)
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
        kill_path = Path.home() / ".claude" / "commands" / "pkood:kill.md"
        review_path = Path.home() / ".claude" / "commands" / "pkood:review.md"
        if (
            skill_path.exists()
            and cmd_path.exists()
            and kill_path.exists()
            and review_path.exists()
        ):
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
        if gemini_path:
            gemini_passed = run_gemini_integration_tests()
            if not gemini_passed:
                all_passed = False

        if claude_path:
            claude_passed = run_claude_integration_tests()
            if not claude_passed:
                all_passed = False

        if not gemini_path and not claude_path:
            print("\n[!] No supported agents found to run full integration tests.")
            all_passed = False

    print("\n" + "=" * 30)
    if all_passed:
        print("ALL TESTS PASSED! Pkood is ready.")
    else:
        print("SOME TESTS FAILED.")
    print("=" * 30)
