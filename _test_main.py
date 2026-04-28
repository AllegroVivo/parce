import sys

import pytest
from datetime import datetime
import io
from contextlib import redirect_stdout
from zoneinfo import ZoneInfo

def run_tests(root_path: str = ".") -> int:
    """Run all tests in the specified path and return exit code."""
    ts = datetime.now(tz=ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %H:%M:%S %Z")
    log_file = "test_log.txt"
    string_io = io.StringIO()

    with redirect_stdout(string_io):
        # exit_code 0: all tests passed, 1: tests failed
        exit_code = pytest.main([root_path, "-v"])

    output_lines = string_io.getvalue().strip().splitlines()

    if exit_code != 0:
        print(f"[{ts}] Tests failed with exit code {exit_code}. See details below:")
        print("\n".join(output_lines))
        return exit_code

    # Pytest summary lines usually look like "==== 14 passed in 0.85s ===="
    # Look for the line that starts with '=' and contains 'in ' (the time)
    summary_line = "Missing summary :("
    for line in reversed(output_lines):
        if line.startswith("=") and " in " in line:
            summary_line = line.strip("=").strip()
            break

    output_message = f"[{ts}] Exit Code {exit_code}: {summary_line}\n"

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(output_message)

    print(output_message)  # Also print to console
    return exit_code

if __name__ == '__main__':
    sys.exit(run_tests())
