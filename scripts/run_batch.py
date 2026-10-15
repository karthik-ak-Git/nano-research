"""Batch execution helper script."""

import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from company_agent.cli import batch

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run batch intelligence processing")
    parser.add_argument("--input", "-i", type=Path, required=True, help="Input file of organisation numbers")
    parser.add_argument("--output", "-o", type=Path, required=True, help="Output JSON results file")
    parser.add_argument("--no-resume", action="store_true", help="Do not resume previous progress")
    args = parser.parse_args()

    batch(input_file=args.input, output_file=args.output, resume=not args.no_resume)
