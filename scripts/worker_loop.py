import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


def run_cmd(cmd):
    # We want to print output in real time so sandbox signals propagate
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    # Stream the output line by line to the console
    for line in process.stdout:
        print(line, end="", flush=True)
    process.wait()
    return process.returncode


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--start-idx", type=int, required=True)
    parser.add_argument("--end-idx", type=int, required=True)
    args = parser.parse_args()

    python_exe = sys.executable
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)

    print(f"Starting worker loop for indices {args.start_idx} to {args.end_idx}...")

    while True:
        # 1. Find next job
        find_cmd = [
            python_exe,
            "-u",
            os.path.join(script_dir, "apply_job_worker.py"),
            "--start-idx",
            str(args.start_idx),
            "--end-idx",
            str(args.end_idx),
            "--find-next",
        ]

        res = subprocess.run(find_cmd, capture_output=True, text=True, encoding="utf-8")
        output = res.stdout

        if "NO_JOBS_READY_TO_APPLY" in output or res.returncode != 0:
            print("No more jobs ready to apply in this range. Exiting loop.")
            break

        # Parse job details from output
        job_id = None
        company = None
        jd_file = None
        pdf_path = None

        for line in output.splitlines():
            if line.startswith("JOB_ID:"):
                job_id = line.split(":", 1)[1].strip()
            elif line.startswith("COMPANY:"):
                company = line.split(":", 1)[1].strip()
            elif line.startswith("JD_FILE:"):
                jd_file = line.split(":", 1)[1].strip()
            elif line.startswith("PDF_PATH:"):
                pdf_path = line.split(":", 1)[1].strip()

        if not all([job_id, company, jd_file, pdf_path]):
            print(f"Failed to parse job details. Output was:\n{output}")
            time.sleep(5)
            continue

        print("\n==================================================")
        print(f"Processing job {job_id} for {company}")
        print("==================================================")

        # 2. Tailor CV (Foreground, prints READY signals)
        tailor_cmd = [
            python_exe,
            "-u",
            os.path.join(script_dir, "tailor_jd.py"),
            "--job-id",
            job_id,
            "--jd-file",
            jd_file,
            "--cv-file",
            os.path.join(os.path.dirname(os.path.dirname(project_dir)), "cv_text.txt"),
            "--output-pdf",
            pdf_path,
        ]
        print("Running CV tailoring...")
        ret = run_cmd(tailor_cmd)
        if ret != 0:
            print(f"CV tailoring failed for job {job_id}. Skipping application.")
            time.sleep(5)
            continue

        # 3. Apply to job (Bypasses tailoring as pdf exists, runs Playwright)
        apply_cmd = [
            python_exe,
            "-u",
            os.path.join(script_dir, "apply_job_worker.py"),
            "--start-idx",
            str(args.start_idx),
            "--end-idx",
            str(args.end_idx),
        ]
        print("Running application (Playwright)...")
        ret = run_cmd(apply_cmd)
        print(f"Application finished with exit code {ret}")
        time.sleep(2)


if __name__ == "__main__":
    main()
