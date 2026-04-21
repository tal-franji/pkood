import time
import json
from typing import Optional
from pathlib import Path
from pkood.agent_products import AgentProduct


class GeminiAgentProduct(AgentProduct):
    @property
    def idle_indicators(self) -> list[str]:
        return ["type your message"]

    @property
    def blocked_indicators(self) -> list[str]:
        return [
            "(y/n)",
            "confirm?",
            "password:",
            "[y/n]",
            "approval",
            "action required",
            "allow execution",
            "allow this tool",
            "allow all server tools",
            "loop detection",
            "do you want to proceed?",
        ]

    @property
    def approve_example(self) -> str:
        return "'2' (allow for session)"

    @property
    def approve_test_input(self) -> str:
        return "y"

    def perform_long_inject(self, agent_id, text, get_tmux_cmd_func):
        import subprocess

        # Long prompts for prompt_toolkit: require Escape then Enter
        time.sleep(0.1)
        subprocess.run(
            get_tmux_cmd_func(agent_id) + ["send-keys", "-t", "main", "Escape"],
            check=True,
        )
        time.sleep(0.2)
        subprocess.run(
            get_tmux_cmd_func(agent_id) + ["send-keys", "-t", "main", "C-m"],
            check=True,
        )

    # --- v2 Detached Agent Heuristics ---

    def is_my_process(self, cmdline: list[str]) -> bool:
        cmd_str = " ".join(cmdline).lower()
        if "gemini" in cmd_str and "node" in cmd_str:
            if not any(x in cmd_str for x in ["tmux", "python", "sh -c", "bash"]):
                return True
        return False

    def get_session_id(
        self, cwd: str, cmdline: Optional[list[str]] = None
    ) -> Optional[str]:
        projects_file = Path.home() / ".gemini/projects.json"
        if projects_file.exists():
            try:
                with open(projects_file, "r") as f:
                    data = json.load(f)
                    return data.get("projects", {}).get(cwd)
            except Exception:
                pass
        return None

    def get_history_log_path(self, session_id: str, cwd: str) -> Optional[str]:
        if not session_id:
            return None
        chat_dir = Path.home() / f".gemini/tmp/{session_id}/chats"
        if chat_dir.exists():
            sessions = list(chat_dir.glob("*.json"))
            if sessions:
                latest = max(sessions, key=lambda p: p.stat().st_mtime)
                return str(latest.resolve())
        return None

    def read_history(
        self, session_id: str, cwd: str, num_lines: int = 50
    ) -> tuple[int, str]:
        if not session_id:
            return 0, "No session ID mapped."
        log_path = self.get_history_log_path(session_id, cwd)
        if log_path and Path(log_path).exists():
            try:
                with open(log_path, "r", errors="ignore") as f:
                    lines = f.readlines()
                    sz = len(lines)
                    return sz, "".join(lines[-num_lines:])
            except Exception as e:
                return 0, f"Error reading log: {e}"
        return 0, "No history files found."
