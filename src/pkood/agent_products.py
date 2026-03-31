from abc import ABC


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
        return "'2' (or 'y')"

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
