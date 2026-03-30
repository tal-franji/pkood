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

        self.agent_type = "other"
        type_file = self.base_dir / "state" / f"{agent_id}_type.txt"
        if type_file.exists():
            self.agent_type = type_file.read_text().strip()

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

    def determine_status(self, content):
        """Categorizes the agent's current state based on terminal content."""
        if not content:
            return "RUNNING"

        last_lines = content.strip().splitlines()[-30:]

        # Use the AgentProduct abstraction for indicators
        from pkood.common import get_agent_product

        product = get_agent_product(self.agent_type)

        # 1. BLOCKED: Mid-task, waiting for specific user approval/confirmation.
        # Priority 1: If there's an active confirmation prompt, we are definitely BLOCKED.
        if any(
            ind in line.lower()
            for line in last_lines
            for ind in product.blocked_indicators
        ):
            return "BLOCKED"

        # 2. IDLE: At the main prompt, ready for a new task.
        # Priority 2: If no blocker is seen, check if we are at the main prompt.
        if any(
            ind in line.lower()
            for line in last_lines[-10:]
            for ind in product.idle_indicators
        ):
            return "IDLE"

        # 3. RUNNING: Actively thinking, executing tools, or streaming output.
        return "RUNNING"

    def update_state(self):
        content = self.capture_pane()
        if content is None:
            # print("DEBUG: No content, exiting.")
            sys.exit(0)

        status = self.determine_status(content)
        lines = content.splitlines()
        last_line = lines[-1] if lines else ""
        current_time = time.time()

        update_ts = current_time
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    old_meta = json.load(f)
                    if old_meta.get("status") == status:
                        update_ts = old_meta.get("update_ts", current_time)
            except Exception:
                pass

        metadata = {
            "agent_id": self.agent_id,
            "timestamp": current_time,
            "status": status,
            "update_ts": update_ts,
            "is_stuck": (status == "BLOCKED"),
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
