import argparse
import sys
from pathlib import Path
from mcp.server.fastmcp import FastMCP

from typing import Optional

if __name__ == "__main__":
    # Add the parent directory to sys.path to allow importing pkood
    sys.path.append(str(Path(__file__).parent.parent))

    from pkood.common import (
        create_agent,
        kill_agent_by_id,
        inject_text_to_agent,
        LOGS_DIR,
    )
    from pkood.cli import (
        get_agents_status,
        get_all_tails,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--stdio", action="store_true")
    args = parser.parse_args()

    mcp = FastMCP("pkood")

    @mcp.tool()
    def start(objective: str, name: Optional[str] = None, directory: str = "."):
        """
        Start a new Gemini session to perform a specific objective.

        Args:
            objective: The free-text description of what the agent should do.
            name: Optional unique identifier for the agent. If omitted, one will be generated based on the objective.
            directory: Working directory for the agent.
        """
        import uuid
        import re

        if not name:
            # Generate a name from the objective
            clean_name = re.sub(r"[^a-zA-Z0-9]+", "-", objective[:20].lower()).strip("-")
            name = f"{clean_name}-{str(uuid.uuid4())[:4]}"

        command = f'gemini -i "{objective}"'
        if create_agent(name, directory, command):
            return f"Gemini agent '{name}' started with objective: {objective}"
        else:
            return f"Failed to start Gemini agent '{name}'."

    @mcp.tool()
    def list_agents():
        """List all active Pkood agents and their status."""
        return get_agents_status()

    @mcp.tool()
    def spawn_agent(name: str, directory: str, command: str):
        """
        Spawn a new background agent.

        Args:
            name: Unique identifier for the agent.
            directory: Working directory for the agent.
            command: The shell command to execute.
        """
        if create_agent(name, directory, command):
            return f"Agent '{name}' spawned successfully."
        else:
            return f"Failed to spawn agent '{name}'."

    @mcp.tool()
    def tail_agents(name: Optional[str] = None):
        """
        Get the last 50 lines of logs from active agents.

        Args:
            name: Optional unique identifier of the agent. If omitted, returns logs for all active agents.
        """
        return get_all_tails(filter_id=name)

    @mcp.tool()
    def kill_agent(name: str):
        """
        Kill an active agent and clean up its state.

        Args:
            name: The unique identifier of the agent to kill.
        """
        if kill_agent_by_id(name):
            return f"Agent '{name}' killed successfully."
        else:
            return f"Agent '{name}' not found or could not be killed."

    @mcp.tool()
    def inject_to_agent(name: str, text: str):
        """
        Inject text input into an active agent session (e.g. to answer a prompt or unblock it).

        Args:
            name: The unique identifier of the agent.
            text: The text to send to the agent's terminal.
        """
        if inject_text_to_agent(name, text):
            return f"Successfully injected text into agent '{name}'."
        else:
            return f"Failed to inject text into agent '{name}' (agent not found or inactive)."

    @mcp.tool()
    def get_log_directory():
        """
        Returns the absolute path to the Pkood log directory.
        Use this to search or read the full logs of all background agents using your native shell/grep tools.
        Note: You will need to ask the user for permission to access this path if it's outside your workspace.
        """
        return str(LOGS_DIR.resolve())

    if args.stdio:
        mcp.run()
    else:
        mcp.run(transport="sse")
