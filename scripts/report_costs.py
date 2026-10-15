"""Generates and displays the cost and budget audit report."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from company_agent.cli import cost_report

if __name__ == "__main__":
    cost_report()
