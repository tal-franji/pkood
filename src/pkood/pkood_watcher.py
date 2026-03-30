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

        if self.agent_type == "gemini":
            # 1. IDLE: At the main prompt, ready for a new task.
            # The string "type your message" only appears when the main input box is focused and empty.
            idle_indicators = ["type your message"]
            if any(
                ind in line.lower()
                for line in last_lines[-10:]
                for ind in idle_indicators
            ):
                return "IDLE"

            # 2. BLOCKED: Mid-task, waiting for specific user approval/confirmation.
            indicators = [
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
            ]
            if any(ind in line.lower() for line in last_lines for ind in indicators):
                return "BLOCKED"

        elif self.agent_type == "claude":
            # 1. IDLE: At the main prompt, ready for a new task.
            # Claude usually has a persistent Ctrl+C hint when at the prompt
            idle_indicators = ["(ctrl+c to exit)", "? for shortcuts"]
            if any(
                ind in line.lower()
                for line in last_lines[-10:]
                for ind in idle_indicators
            ):
                return "IDLE"

            # 2. BLOCKED: Mid-task, waiting for specific user approval/confirmation.
            indicators = [
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
            if any(ind in line.lower() for line in last_lines for ind in indicators):
                return "BLOCKED"

        else:
            # Generic fallback
            idle_indicators = ["> ", "$ "]
            if any(
                ind in line.lower()
                for line in last_lines[-5:]
                for ind in idle_indicators
            ):
                return "IDLE"
            indicators = ["(y/n)", "confirm?", "password:", "[y/n]", "approval"]
            if any(ind in line.lower() for line in last_lines for ind in indicators):
                return "BLOCKED"

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

        metadata = {
            "agent_id": self.agent_id,
            "timestamp": time.time(),
            "status": status,
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
