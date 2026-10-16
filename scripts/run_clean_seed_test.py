"""Executes a clean-database seeding test against an isolated database to audit seed recreation."""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

test_db_path = Path(__file__).resolve().parent.parent / "data" / "test_clean_seed_audit.db"
if test_db_path.exists():
    test_db_path.unlink()

# Set clean database environment
os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"

from company_agent.config import settings
settings.DATABASE_URL = f"sqlite:///{test_db_path.as_posix()}"

from scripts.seed_profiles import seed_profiles

if __name__ == "__main__":
    t0 = time.time()
    total = seed_profiles(target_count=1000)
    elapsed = time.time() - t0
    print(f"\nCompleted clean database seed in {elapsed:.2f}s with {total} profiles.")

    # Clean up test database
    if test_db_path.exists():
        try:
            test_db_path.unlink()
        except Exception:
            pass
