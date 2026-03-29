import argparse
import sys
from pathlib import Path
from mcp.server.fastmcp import FastMCP

if __name__ == "__main__":
    # Add the parent directory to sys.path to allow importing pkood
    sys.path.append(str(Path(__file__).parent.parent))

    from pkood.cli import (
        get_agents_status,
        get_all_tails,
        create_agent,
        kill_agent_by_id,
        inject_text_to_agent,
        LOGS_DIR,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--stdio", action="store_true", help="Run in stdio mode")
    args = parser.parse_args()

    # Initialize FastMCP server
    if args.stdio:
        mcp = FastMCP("Pkood")
    else:
        mcp = FastMCP("Pkood", host=args.host, port=args.port)

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
        success = create_agent(name, directory, command)
        if success:
            return f"Agent '{name}' spawned successfully."
        else:
            return f"Failed to spawn agent '{name}'."

    @mcp.tool()
    def tail_agents():
        """Get the last 50 lines of logs from all active agents."""
        return get_all_tails()

    @mcp.tool()
    def kill_agent(name: str):
        """
        Kill an active agent and clean up its state.

        Args:
            name: The unique identifier of the agent to kill.
        """
        success = kill_agent_by_id(name)
        if success:
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
        success = inject_text_to_agent(name, text)
        if success:
            return f"Successfully injected '{text}' into agent '{name}'."
        else:
            return f"Failed to inject text into agent '{name}'. Ensure it is active."

    @mcp.tool()
    def get_log_directory():
        """
        Returns the absolute path to the Pkood log directory.
        Use this to search or read the full logs of all background agents using your native shell/grep tools.
        Note: You will need to ask the user for permission to access this path if it's outside your workspace.
        """
        return str(LOGS_DIR.resolve())

    if args.stdio:
        # stdio transport for local integration (e.g. Claude Code)
        mcp.run(transport="stdio")
    else:
        print(f"Pkood MCP Server starting on {args.host}:{args.port}")
        # SSE transport for network access (e.g. Gemini CLI)
        mcp.run(transport="sse")
