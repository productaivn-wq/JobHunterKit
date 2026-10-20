import argparse
import subprocess
import sys
from pathlib import Path

sources = [
    "linkedin",
    "linkedin-recommended",
    "linkedin-top-applicant",
    "linkedin-human-resources",
    "linkedin-it-services-and-it-consulting",
    "linkedin-easy-apply",
    "linkedin-remote-jobs",
    "remotive",
    "weworkremotely",
    "remoteok",
    "jsremotely",
    "itviec",
    "topcv",
    "indeed",
    "careerjet",
    "vietnamworks",
    "glints",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", default="Product Manager")
    parser.add_argument("--location", default="Ho Chi Minh")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--threshold", type=int, default=0)
    args = parser.parse_args()

    pipeline_script = Path(__file__).resolve().parent / "scripts" / "pipeline.py"
    base_cmd = [
        sys.executable,
        str(pipeline_script),
        "--keyword",
        args.keyword,
        "--location",
        args.location,
    ]

    if args.threshold > 0:
        base_cmd.extend(["--threshold", str(args.threshold)])

    if args.dry_run:
        base_cmd.append("--dry-run")
    if args.force:
        base_cmd.append("--force")

    print(f"Starting massive scrape for {args.keyword} in {args.location}...")

    for source in sources:
        print("\n=============================================")
        print(f"EXECUTING SOURCE: {source.upper()}")
        print("=============================================")

        cmd = base_cmd + ["--source", source]
        print(f"Running: {' '.join(cmd)}")

        try:
            # We don't check=True so that one failing source doesn't stop the whole script
            subprocess.run(cmd)
            print(f"[{source.upper()}] Pipeline phase finished.")
        except KeyboardInterrupt:
            print("Aborted by user.")
            sys.exit(1)
        except Exception as e:
            print(f"[ERROR] {source.upper()} failed: {e}")


if __name__ == "__main__":
    main()
