"""Validates a dataset of Norwegian company profiles against Mod11 and schema rules."""

import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from company_agent.cli import validate

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate profile dataset")
    parser.add_argument("--input", "-i", type=Path, required=True, help="Path to profiles JSON file")
    args = parser.parse_args()

    validate(input_file=args.input)
