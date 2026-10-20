"""
apply_chunk.py — Subtask executor for batched parallel job applications.

Reads a serialized chunk payload containing candidate jobs, CV path, and configuration,
and delegates execution to the pipeline auto_apply engine.
"""

import json
import os
import sys

# Ensure the scripts directory is in the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from pipeline import auto_apply


def main() -> None:
    """Entry point to execute batch job application from a JSON chunk descriptor."""
    if len(sys.argv) < 2:
        print("Usage: python apply_chunk.py <chunk_json_path>")
        sys.exit(1)

    chunk_json_path = sys.argv[1]
    with open(chunk_json_path, encoding="utf-8") as f:
        data = json.load(f)

    passed_jobs = data["passed_jobs"]
    cv_file = data["cv_file"]
    dirs = data["dirs"]
    tailored_cvs = data.get("tailored_cvs")
    state_file = data.get("state_file")
    dry_run = data.get("dry_run", False)

    auto_apply(
        passed_jobs,
        cv_file,
        dirs,
        tailored_cvs=tailored_cvs,
        state_file=state_file,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    main()
