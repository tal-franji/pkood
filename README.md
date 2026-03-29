# Pkood

Run tens of agent sessions (Claude-code / Gemini-CLI) in parallel. Monitor them and attach to them when needed. Get notified when they are blocked and await your input.

## Installation

1. **Requirements**: 
   - Python 3.10+
   - `tmux` (Available via `brew install tmux` on macOS or `sudo apt install tmux` on Linux/Windows:WSL2).

2. **Install via PyPI**:
   ```bash
   pip install pkood
   ```

3. **Install from Source**:
   Clone the repository and install in editable mode:
   ```bash
   git clone https://github.com/tal-franji/pkood.git
   cd pkood
   pip install -e .
   ```

4. **Verify and Configure**:
   Run the system check to ensure Tmux is installed and to automatically configure your AI agents (Gemini CLI / Claude Code) to talk to the Pkood control plane:
   ```bash
   pkood test
   ```

## Operation

Pkood treats AI agents and long-running tasks as managed services. All state is stored in `~/.pkood/`.

### Commands

- **Start an interactive session**:
  Creates a new session running your default shell in the specified directory and attaches to it immediately.
  ```bash
  pkood start --dir ./my-project
  ```
  *Note: The session name defaults to the directory name if `--name` is omitted.*

- **Spawn a background agent**:
  Runs a specific command in a managed background session.
  ```bash
  pkood spawn --name research-task "gemini 'research the latest AgOps trends'"
  ```

- **List active agents**:
  Shows all agents, their current status (RUNNING, BLOCKED, or EXITED), and log sizes.
  ```bash
  pkood ls
  ```

- **Attach to a session**:
  Join a running agent's terminal.
  ```bash
  pkood attach research-task
  ```
  *To detach without killing the agent, press `Ctrl+B` then `D`.*

- **Kill an agent**:
  Terminates the session and cleans up associated sockets and state files.
  ```bash
  pkood kill research-task
  ```

- **Inject input**:
  Send text directly to a background agent's terminal (e.g. to unblock a prompt).
  ```bash
  pkood inject research-task "y"
  ```

### Key Shortcuts (within a session)
After attaching to the session you can use the following Tmux keys:

- **Detach**: `Ctrl+B` followed by `D`
- **Scroll Mode**: `Ctrl+B` followed by `[` (Press `q` to exit)
- **Force Exit**: `Ctrl+D` (This kills the agent and closes the session)

## Skills and Slash Commands

Pkood can install skills and slash commands for AI agents (Gemini CLI / Claude Code) to allow them to interact with the Pkood control plane.

### Install Skills and Slash Commands

```bash
pkood test
```

### Use the Skills and Slash Commands
Show all active agents and their status:
```bash
/pkood:status
```

## The AgOps Control Plane (MCP)

Pkood includes a built-in **Model Context Protocol (MCP)** server. This transforms Pkood from a simple CLI tool into an orchestration layer that your AI agents can use to manage each other.

### Starting the Control Plane
To allow agents to see and interact with the fleet, start the MCP service:
```bash
pkood mcp
```
*(Runs on `http://localhost:8000/sse` by default)*

### What Agents Can Do
Once your agents (like Gemini CLI or Claude Code) are connected to the Pkood MCP, they gain "fleet awareness." You can give them high-level commands like:

*   **Fleet Summarization**: *"Check the logs of all active agents and give me a 1-sentence status report for each."*
*   **Remote Unblocking**: *"I see the 'worker-1' agent is stuck on a confirmation. Send it a 'y' to continue."*
*   **Autonomous Spawning**: *"Once 'data-cleanup' finishes, spawn a new agent to run the 'training-job'."*
*   **Deep Log Analysis**: *"Search through all agent logs for any 'OutOfMemory' errors."*

By exposing the low-level Tmux primitives as structured MCP tools, Pkood enables a recursive, multi-agent development workflow where one "Manager" agent can coordinate a fleet of specialized workers.

## Comparison: Pkood vs. Claude `/batch`

While Claude Code's `/batch` skill is excellent for quick, sequential automation, Pkood is designed for long-running, autonomous operations.

| Feature | Claude `/batch` | Pkood |
| :--- | :--- | :--- |
| **Persistence** | Ephemeral (stops if terminal closes) | **Persistent** (runs in background via Tmux) |
| **Visibility** | Simple progress status | **Full Terminal Attachment** (`pkood attach`) |
| **Context** | Single-session focus | **Fleet-wide awareness** via MCP |
| **Control** | Stop/Start only | **Inject input**, search logs, and manage state |
| **Workflow** | Sequential local tasks | **AgOps Orchestration** (Agents manage agents) |

**Use `/batch`** when you want to automate 10 small local edits in your current session.

**Use Pkood** when you want to run a fleet of independent agents that work autonomously across different projects and require high-level coordination.
