# Project Pkood (פקודה)
**An Agentic Operations (AgOps) Orchestrator for Recursive, Parallel Development.**

## 1. Vision
Pkood is a laptop-native orchestration layer designed to manage tens of parallel, long-running agentic software processes. It treats AI agents like managed microservices, providing observability, hierarchical control, and searchable command history.

### Core Principles
* **Persistence:** Agents run in isolated Tmux sockets. If the controller or the UI crashes, the agent continues.
* **Identity Proxy:** Agents run as the local user, inheriting SSH keys, Git credentials, and environment variables.
* **Recursion:** Any agent can spawn "child" agents, becoming a manager of its own sub-tree.
* **Observability:** Every byte of terminal output is captured, indexed, and searchable.

---

## 2. Technical Architecture
The system uses a **Man-in-the-Middle Terminal** approach.

* **The Shell:** `tmux` sessions mapped to unique Unix sockets in `~/.pkood/sockets/`.
* **The Watcher:** A sidecar Python process for every agent that "scrapes" the PTY for status and blockers.
* **The Registry:** A filesystem-based state (JSON) or SQLite DB tracking parent/child relationships.
* **The Protocol:** A standardized `status.json` contract that agents use to report semantic progress.

---

## 3. Initial Implementation: The Watcher Script
Save this as `pkood_watcher.py`. This script is the "Mechanical Metadata" layer.

```python
import subprocess
import json
import time
import os
from pathlib import Path

class PkoodWatcher:
    """
    Monitors a specific Tmux-based agent session.
    Scrapes output, detects 'stuck' states, and updates global metadata.
    """
    def __init__(self, agent_id):
        self.agent_id = agent_id
        self.base_dir = Path.home() / ".pkood"
        self.socket = self.base_dir / "sockets" / f"{agent_id}.sock"
        self.state_file = self.base_dir / "state" / f"{agent_id}_meta.json"
        self.log_file = self.base_dir / "logs" / f"{agent_id}.log"

        # Ensure directories exist
        for d in [self.socket.parent, self.state_file.parent, self.log_file.parent]:
            d.mkdir(parents=True, exist_ok=True)

    def capture_pane(self):
        """Captures the last 50 lines of the terminal pane."""
        try:
            cmd = ["tmux", "-S", str(self.socket), "capture-pane", "-p", "-t", "main"]
            return subprocess.check_output(cmd).decode('utf-8')
        except subprocess.CalledProcessError:
            return None

    def detect_blockers(self, content):
        """Identifies if the agent is waiting for user input (y/n, password, etc)."""
        if not content: return False
        last_lines = content.strip().splitlines()[-3:]
        indicators = ["(y/n)", "confirm?", "password:", "[y/n]", "approval"]
        return any(ind in line.lower() for line in last_lines for ind in indicators)

    def update_state(self):
        content = self.capture_pane()
        is_blocked = self.detect_blockers(content)

        metadata = {
            "agent_id": self.agent_id,
            "timestamp": time.time(),
            "status": "BLOCKED" if is_stuck else "RUNNING",
            "is_stuck": is_blocked,
            "last_output_snippet": content.splitlines()[-1] if content else ""
        }

        with open(self.state_file, 'w') as f:
            json.dump(metadata, f, indent=2)

    def run_loop(self, interval=2):
        print(f"[*] Monitoring {self.agent_id}...")
        while True:
            try:
                self.update_state()
            except Exception as e:
                print(f"[!] Error updating {self.agent_id}: {e}")
            time.sleep(interval)

if __name__ == "__main__":
    # Example usage: python pkood_watcher.py my_project_1
    import sys
    if len(sys.argv) > 1:
        watcher = PkoodWatcher(sys.argv[1])
        watcher.run_loop()
```

---

## 4. Dependencies (`requirements.txt`)
The initial environment should include:
* `python-dotenv`: For managing agent-specific environment variables.
* `libtmux`: Python library to interact with Tmux sessions programmatically.
* `pydantic`: For strictly validating the `status.json` protocol between agents.
* `click`: For building the `pkood` CLI.
* `psutil`: For monitoring CPU/Memory usage of specific agent PIDs.

---

## 5. Next Steps for Antigravity
1.  **Repository Setup:** Initialize a Git repo named `pkood`.
2.  **CLI Entry Point:** Create a `pkood.py` that handles `spawn`, `list`, `attach`, and `kill`.
3.  **Search Engine:** Implement a basic `pkood search <query>` using `ripgrep` (rg) to scan the `~/.pkood/logs/` directory.
4.  **The Interceptor:** Add logic to `send-keys` to a Tmux socket to allow remote unblocking.

---

**Would you like me to also draft the specific "Pkood Protocol" system prompt that you'll need to give to the agents so they know how to interact with this file-based hierarchy?**