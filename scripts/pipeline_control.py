"""
pipeline_control.py — CLI management utility for pipeline pause/resume states.

Provides operator commands to pause, resume, or check the operational state of the job hunting pipeline.
"""

import argparse
import sys
from pathlib import Path


def _setup_sys_path() -> None:
    """Configures sys.path to locate shared_platform modules."""
    curr = Path(__file__).resolve()
    for parent in curr.parents:
        if (parent / "shared_platform").is_dir():
            root_path = str(parent)
            if root_path not in sys.path:
                sys.path.insert(0, root_path)
            break


_setup_sys_path()

import shared_platform.pipeline_state as pipeline_state


def main() -> None:
    """CLI dispatcher for pipeline state pause, resume, and check commands."""
    parser = argparse.ArgumentParser(description="Pipeline Pause/Resume Control")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pause", action="store_true", help="Pause the pipeline")
    group.add_argument("--resume", action="store_true", help="Resume the pipeline")
    group.add_argument(
        "--check", action="store_true", help="Check pipeline pause status"
    )

    args = parser.parse_args()

    if args.pause:
        print("Pausing pipeline...")
        pipeline_state.set_paused(True, actor="gateway_control")
        print("Pipeline paused successfully.")
    elif args.resume:
        print("Resuming pipeline...")
        pipeline_state.set_paused(False, actor="gateway_control")
        print("Pipeline resumed successfully.")
    elif args.check:
        paused = pipeline_state.is_paused()
        print(f"Pipeline paused state: {paused}")


if __name__ == "__main__":
    main()
