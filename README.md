# Pkood

Run tens of agent sessions (Claude-code / Gemini-CLI) in parallel. Monitor them and attach to them when needed. Get notified when they are blocked and await your input.

## Installation

1. **Requirements**: 
   - Python 3.10+
   - `tmux` (Available via `brew install tmux` on macOS or `sudo apt install tmux` on Linux/WSL2).

2. **Install via PyPI**:
   ```bash
   pip install pkood
   ```

3. **Install from Source**:
   Clone the repository and install in editable mode:
   ```bash
   git clone https://github.com/your-username/pkood.git
   cd pkood
   pip install -e .
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
  # or
  pkood ps
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

### Key Shortcuts (within a session)
- **Detach**: `Ctrl+B` followed by `D`
- **Scroll Mode**: `Ctrl+B` followed by `[` (Press `q` to exit)
- **Force Exit**: `Ctrl+D` (This kills the agent and closes the session)
