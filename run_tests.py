#!/usr/bin/env python3
"""
Run the full automated test suite.

Usage:
    python run_tests.py
    python run_tests.py -v
"""
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    project_root = Path(__file__).parent
    extra_args = sys.argv[1:] or ["-v", "--tb=short"]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/"] + extra_args,
        cwd=str(project_root)
    )
    sys.exit(result.returncode)

