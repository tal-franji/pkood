import time
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
