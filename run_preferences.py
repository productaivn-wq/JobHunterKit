import argparse
import json
import os
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(
        description="JobHunterKit Preferred Campaigns Runner"
    )
    parser.add_argument(
        "--profile",
        default=os.path.join("config", "applicant_profile.json"),
        help="Path to applicant profile JSON file",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Forward --dry-run to pipeline.py"
    )
    parser.add_argument(
        "--force", action="store_true", help="Forward --force to pipeline.py"
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="Forward --threshold override to pipeline.py",
    )
    parser.add_argument(
        "--cv", default=None, help="Forward --cv override to pipeline.py"
    )
    args = parser.parse_args()

    # Resolve paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    profile_path = args.profile
    if not os.path.isabs(profile_path):
        profile_path = os.path.join(script_dir, profile_path)

    if not os.path.exists(profile_path):
        print(f"[ERROR] Profile file not found: {profile_path}")
        sys.exit(1)

    print(f"Loading applicant profile and preferences from: {profile_path}")
    try:
        with open(profile_path, encoding="utf-8") as f:
            profile_data = json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to parse profile JSON: {e}")
        sys.exit(1)

    preferences = profile_data.get("preferences", {}).get("campaigns", [])
    if not preferences:
        print("[WARN] No campaigns found in preferences.")
        return

    pipeline_path = os.path.join(script_dir, "scripts", "pipeline.py")
    if not os.path.exists(pipeline_path):
        print(f"[ERROR] pipeline.py not found at: {pipeline_path}")
        sys.exit(1)

    base_cmd = [sys.executable, pipeline_path]
    if args.dry_run:
        base_cmd.append("--dry-run")
    if args.force:
        base_cmd.append("--force")
    if args.threshold is not None:
        base_cmd.extend(["--threshold", str(args.threshold)])
    if args.cv is not None:
        base_cmd.extend(["--cv", args.cv])

    failures = []
    success_count = 0

    print(f"Starting execution of preferred campaigns (Total: {len(preferences)})")

    for i, pref in enumerate(preferences, 1):
        job_title = pref.get("job_title")
        places = pref.get("places", [])
        channels = pref.get("channels", [])

        if not job_title or not places or not channels:
            print(f"[{i}/{len(preferences)}] Skipping invalid preference: {pref}")
            continue

        print("\n==================================================")
        print(f"PREFERENCE {i}/{len(preferences)}: {job_title}")
        print(f"Places: {places}")
        print(f"Channels: {channels}")
        print("==================================================")

        for place in places:
            for channel in channels:
                print(
                    f"\n>>> Executing Campaign: Title='{job_title}' | Place='{place}' | Channel='{channel}'"
                )
                cmd = base_cmd + [
                    "--keyword",
                    job_title,
                    "--location",
                    place,
                    "--source",
                    channel,
                ]
                print(f"Running command: {' '.join(cmd)}")

                try:
                    subprocess.run(cmd, check=True)
                    print("[SUCCESS] Campaign completed successfully.")
                    success_count += 1
                except subprocess.CalledProcessError as e:
                    print(f"[ERROR] Campaign failed with exit code {e.returncode}")
                    failures.append(
                        {
                            "job_title": job_title,
                            "place": place,
                            "channel": channel,
                            "error": f"Exit code {e.returncode}",
                        }
                    )
                except KeyboardInterrupt:
                    print("\nAborted by user.")
                    sys.exit(1)
                except Exception as e:
                    print(f"[ERROR] Campaign execution encountered exception: {e}")
                    failures.append(
                        {
                            "job_title": job_title,
                            "place": place,
                            "channel": channel,
                            "error": str(e),
                        }
                    )

    print("\n==================================================")
    print("Preferred campaigns execution finished.")
    print(f"Successful campaigns: {success_count}")
    print(f"Failed campaigns: {len(failures)}")
    if failures:
        print("Failures breakdown:")
        for fail in failures:
            print(
                f"  - Title: {fail['job_title']} | Place: {fail['place']} | Channel: {fail['channel']} | Error: {fail['error']}"
            )
    print("==================================================")

    if failures:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
