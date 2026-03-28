import subprocess
import json
import time
import sys
import os
from pathlib import Path


class PkoodWatcher:
    def __init__(self, agent_id):
        self.agent_id = agent_id
        self.base_dir = Path.home() / ".pkood"
        self.socket = self.base_dir / "sockets" / f"{agent_id}.sock"
        self.state_file = self.base_dir / "state" / f"{agent_id}_meta.json"

        # Ensure directories exist
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def capture_pane(self):
        """Captures the last 100 lines of the terminal pane."""
        try:
            cmd = ["tmux", "-S", str(self.socket), "capture-pane", "-p", "-t", "main"]
            # print(f"DEBUG: Running {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout
        except Exception:
            # print(f"DEBUG: Error capturing pane: {e}")
            return None

    def detect_blockers(self, content):
        """Identifies if the agent is waiting for user input."""
        if not content:
            return False
        last_lines = content.strip().splitlines()[-5:]
        indicators = ["(y/n)", "confirm?", "password:", "[y/n]", "approval", ">"]
        return any(ind in line.lower() for line in last_lines for ind in indicators)

    def update_state(self):
        content = self.capture_pane()
        if content is None:
            # print("DEBUG: No content, exiting.")
            sys.exit(0)

        is_blocked = self.detect_blockers(content)
        lines = content.splitlines()
        last_line = lines[-1] if lines else ""

        metadata = {
            "agent_id": self.agent_id,
            "timestamp": time.time(),
            "status": "BLOCKED" if is_blocked else "RUNNING",
            "is_stuck": is_blocked,
            "last_output_snippet": last_line,
        }

        # Use a temporary file and rename for atomicity
        temp_file = self.state_file.with_suffix(".tmp")
        with open(temp_file, "w") as f:
            json.dump(metadata, f, indent=2)
        os.replace(temp_file, self.state_file)
        # print(f"DEBUG: Updated {self.state_file}")

    def run_loop(self, interval=2):
        # print(f"DEBUG: Watcher starting for {self.agent_id}")
        while True:
            try:
                if not self.socket.exists():
                    # print("DEBUG: Socket missing, exiting.")
                    break
                self.update_state()
            except Exception:
                # print(f"DEBUG: Loop error: {e}")
                pass
            time.sleep(interval)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        watcher = PkoodWatcher(sys.argv[1])
        watcher.run_loop()
