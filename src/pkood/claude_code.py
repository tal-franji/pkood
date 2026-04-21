import time
import json
from typing import Optional
from pathlib import Path
from pkood.agent_products import AgentProduct


class ClaudeAgentProduct(AgentProduct):
    @property
    def idle_indicators(self) -> list[str]:
        return ["(ctrl+c to exit)", "? for shortcuts"]

    @property
    def blocked_indicators(self) -> list[str]:
        return [
            "(y/n)",
            "confirm?",
            "password:",
            "[y/n]",
            "approve?",
            "press enter to confirm",
            "do you want to proceed?",
            "trust?",
            "trust this",
        ]

    @property
    def approve_example(self) -> str:
        return "'2' (Yes, and don't ask again for this tool in this directory)"

    @property
    def approve_test_input(self) -> str:
        return "2"

    def unblock_agent(self, agent_id, get_tmux_cmd_func):
        import subprocess
        import time

        # Claude Code menus accept '2' immediately. Sending '2' + 'Enter' (C-m)
        # too fast often gets ignored by its prompt toolkit.
        subprocess.run(
            get_tmux_cmd_func(agent_id)
            + ["send-keys", "-t", "main", self.approve_test_input],
            check=True,
        )
        time.sleep(0.5)
        # Send an Enter in case it was at the normal prompt, to clear the '2' and return to IDLE
        subprocess.run(
            get_tmux_cmd_func(agent_id) + ["send-keys", "-t", "main", "C-m"],
            check=True,
        )

    def perform_long_inject(self, agent_id, text, get_tmux_cmd_func):
        import subprocess

        # Claude Code UI often requires a definitive Enter to break out of paste handling
        # and another to actually submit the multiline prompt.
        time.sleep(0.2)
        subprocess.run(
            get_tmux_cmd_func(agent_id) + ["send-keys", "-t", "main", "C-m"],
            check=True,
        )
        time.sleep(0.1)
        subprocess.run(
            get_tmux_cmd_func(agent_id) + ["send-keys", "-t", "main", "C-m"],
            check=True,
        )

    # --- v2 Detached Agent Heuristics ---

    def is_my_process(self, cmdline: list[str]) -> bool:
        cmd_str = " ".join(cmdline).lower()
        if "claude.app" in cmd_str or "shipit" in cmd_str or "helper" in cmd_str:
            return False
        if "claude" in cmd_str:
            if not any(x in cmd_str for x in ["tmux", "python", "sh -c", "bash"]):
                return True
        return False

    def get_session_id(
        self, cwd: str, cmdline: Optional[list[str]] = None
    ) -> Optional[str]:
        history_file = Path.home() / ".claude/history.jsonl"
        if history_file.exists():
            try:
                with open(history_file, "r") as f:
                    lines = f.readlines()
                    for line in reversed(lines):
                        if f'"project":"{cwd}"' in line:
                            data = json.loads(line)
                            return data.get("sessionId")
            except Exception:
                pass
        return None

    def get_history_log_path(self, session_id: str, cwd: str) -> Optional[str]:
        history_file = Path.home() / ".claude/history.jsonl"
        if history_file.exists():
            return str(history_file.resolve())
        return None

    def read_history(
        self, session_id: str, cwd: str, num_lines: int = 50
    ) -> tuple[int, str]:
        if not session_id:
            return 0, "No session ID mapped."
        history_file = Path.home() / ".claude/history.jsonl"
        if history_file.exists():
            try:
                with open(history_file, "r", errors="ignore") as f:
                    lines = f.readlines()

                # Filter lines for this session
                session_lines = []
                for line in lines:
                    if f'"sessionId":"{session_id}"' in line:
                        session_lines.append(line)

                sz = len(session_lines)
                return sz, "".join(session_lines[-num_lines:])
            except Exception as e:
                return 0, f"Error reading log: {e}"
        return 0, "No history file found."
