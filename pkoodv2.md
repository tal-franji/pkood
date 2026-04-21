# pkood v2
pkood v1 features are defined in pkood.md
We want to keep supporting these features.
However we want to move from analyzing the agents-fleet status using stdio capture (allowed by tmux sessions) - to capturing the thought processes logged by the agent and thus also supporting agents not running under tmux and agents running in a integrated-environment (e.g. Antigravity or CoPilot in VSCode)

We want to support Geming CLI, Claude Code - so we need to know the specifics of how to find their session-id and log directory.

### MS Windows support
Many pkood implementation details relay on unix-specific tools (tmux, ps, etc). We want to support MS Windows as well. For start we want to have all these places marked and have an 'if' condition with a place holder for a windows implemenation that will through and exception at this stage.

# new fetures - general description
we want to allow the `pkood ls` command to find and list agent sessions by looking at the system process list.
We want to match and find the agent sessions and their log directory.
We want a new command+MCP call similar to our `pkood tail` that will give the tail of the agent's thought log.
will name it `pkood hist` or `pkood history`

Since history log may be long we may want to create a synopsys of it. Also for getting the current status of the agent we need to analyze the last lines in the history.

We now list more the features in more details
## pkood ls
`pkood ls` and the mcp: `list_agents`
currently return return agent_id, status, log_sz
We  keep those. There is a new status 'DETACH' which means this agent is not working via tmux
for all agent there is also hist_sz (title HIST) and the mcp:`list_agents` returns the session_id, agent_kind ("claude", "gemini", etc) and the thinking history path.

## pkood hist
New command and new MCP tool to accompany that. We need to make sure that if we update the installation of pkood using `pkood test` this tool is indeed added.

The `pkood hist [N_LINES]` command returns the tail of the thinking/history log

## skill `/pkood:status`
The skill infers the summary of the agent from the thinking history. The status should be "DETACH" as it cannot defer the actual status from the thinking log. 

### `/pkood:status` formatting improvements (minor)
Current implementation requests the agent to display the results in an ascii table. This results in inconsistent output for every usae of `/pkood:status` so we may want to consider a small formating python script/MCP tool and ask the agent to use it.

## not implemented
Since we cannot use `pkood inject` on agents not running in tmux - all the skills that relay on this - `/pkood:review` and `/pkood:auto` will not work on these agents and should give a warning about them.

## MS Windows Portability
One of the core goals of v2 is to enable **Observability** on MS Windows. Since v2 discovery and history tailing rely on the system process list and local log files (rather than `tmux` PTY scraping), the following commands will be supported on Windows:
- `pkood ls` (Listing active Gemini/Claude processes)
- `pkood hist` (Tailing thinking logs from history files)
- `pkood status` (Summarizing status from logs)

**Limitations on Windows:**
Features that require a persistent pseudo-terminal (PTY) or terminal multiplexer will not be supported natively on Windows:
- `pkood spawn` (detached mode)
- `pkood attach`
- `pkood inject`
- `pkood review` / `pkood auto` (as they rely on injection)

For these features, Windows users are encouraged to use **WSL (Windows Subsystem for Linux)**.

## Implementation Details & Heuristics
Through runtime testing, we have confirmed the following discovery heuristics for mapping running processes to their agent sessions without relying on `tmux`:

### Gemini CLI
1.  **Process Matching:** Find processes matching `node.*gemini` (excluding wrappers like `tmux`, `python`, or `bash`).
2.  **CWD Extraction:** Extract the Current Working Directory (CWD) of the target PID.
3.  **Session Mapping:** Look up the CWD in `~/.gemini/projects.json` to find the `project_id`. The thought history is the most recently modified `.json` file located in `~/.gemini/tmp/<project_id>/chats/`.

### Claude Code
1.  **Process Matching:** Find processes matching `claude` (excluding the desktop app `Claude.app`, `ShipIt`, and script wrappers).
2.  **CWD Extraction:** Extract the CWD of the target PID.
3.  **Session Mapping:** Read `~/.claude/history.jsonl` from bottom to top. Find the last entry where `"project"` matches the CWD. Extract the `"sessionId"`. The full thinking log consists of all lines in `history.jsonl` containing that `sessionId`.

### Cross-Platform Portability
For extracting CWD from a PID, relying on `lsof` (macOS/Linux) or `/proc` (Linux) is brittle. We will use the `psutil` library (`psutil.Process(pid).cwd()`) to ensure the agent discovery mechanism works transparently across macOS, Linux, and Windows environments.
