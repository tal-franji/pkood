import time
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
