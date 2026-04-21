from abc import ABC
from typing import Optional


class AgentProduct(ABC):
    """Base class for agent-specific behavior and terminal detection logic."""

    @property
    def idle_indicators(self) -> list[str]:
        """Strings that indicate the agent is sitting at a main prompt."""
        return ["> ", "$ "]

    @property
    def blocked_indicators(self) -> list[str]:
        """Strings that indicate the agent is stuck waiting for a tool/safety approval."""
        return ["(y/n)", "confirm?", "password:", "[y/n]", "approval"]

    @property
    def approve_example(self) -> str:
        """Example input to send via inject_to_agent to approve a blocked action for the session."""
        return "'2' (allow for session)"

    @property
    def approve_test_input(self) -> str:
        """The input to send during automated tests to approve a blocked action."""
        return "2"

    def unblock_agent(self, agent_id, get_tmux_cmd_func):
        """Action to perform to unblock the agent during tests."""
        # By default, use the normal inject flow which sends the test input + Enter.
        from pkood.common import inject_text_to_agent

        inject_text_to_agent(agent_id, self.approve_test_input)

    def perform_long_inject(self, agent_id, text, get_tmux_cmd_func):
        """
        Default strategy for injecting long/multiline text.
        The buffer is already pasted; this method handles the 'submit' keystrokes.
        """
        import subprocess

        subprocess.run(
            get_tmux_cmd_func(agent_id) + ["send-keys", "-t", "main", "C-m"],
            check=True,
        )

    # --- v2 Detached Agent Heuristics ---

    def is_my_process(self, cmdline: list[str]) -> bool:
        """Returns True if the process command line matches this agent type."""
        return False

    def get_session_id(
        self, cwd: str, cmdline: Optional[list[str]] = None
    ) -> Optional[str]:
        """Extracts the internal session ID based on the working directory or cmdline."""
        return None

    def get_history_log_path(self, session_id: str, cwd: str) -> Optional[str]:
        """Returns the path to the internal thought/history log."""
        return None

    def read_history(
        self, session_id: str, cwd: str, num_lines: int = 50
    ) -> tuple[int, str]:
        """
        Reads the tail of the internal thought/history log.
        Returns a tuple: (total_lines_or_bytes, raw_tail_string)
        """
        return 0, "History not available."
