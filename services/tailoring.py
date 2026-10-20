import os
import sys

from services.common import run_command, safe_filename


def tailor_cvs(passed_jobs, cv_file, dirs, script_dir, force=False):
    """
    Triggers ResumeTailorKit for passed jobs.
    Saves output as: tailored/{Company}__{job_id}.pdf
    Returns a dict mapping job_id to the tailored PDF path.
    """
    print("[Phase 3: Tailor] Generating tailored CVs for passed jobs...")
    print("[UTOP|func|tailor_cvs|cp-fr-012]")
    tailored_cvs = {}

    jobs_to_tailor = []
    for job in passed_jobs:
        company_safe = safe_filename(job["company"])
        pdf_name = f"{company_safe}__{job['id']}.pdf"
        pdf_path = os.path.join(dirs["tailored_dir"], pdf_name)

        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0 and not force:
            tailored_cvs[job["id"]] = pdf_path
            print(f"  [CACHED SUCCESS] Using existing tailored CV: {pdf_path}")
            continue

        temp_jd = os.path.join(dirs["local_scratch"], f"{job['id']}_jd.txt")
        jobs_to_tailor.append((job, temp_jd, pdf_path))

    def tailor_single_job(item):
        job, temp_jd, pdf_path = item
        print(f"  Generating tailored CV for {job['title']} at {job['company']}...")
        tailor_cmd = [
            sys.executable,
            os.path.join(script_dir, "tailor_jd.py"),
            "--job-id",
            job["id"],
            "--jd-file",
            temp_jd,
            "--cv-file",
            cv_file,
            "--output-pdf",
            pdf_path,
        ]
        try:
            result = run_command(tailor_cmd)
            return job["id"], pdf_path, result.returncode == 0, result
        except Exception as e:
            print(f"  [ERROR] Parallel CV tailoring failed for {job['company']}: {e}")
            return job["id"], pdf_path, False, None

    if jobs_to_tailor:
        from concurrent.futures import ThreadPoolExecutor

        print(f"  Tailoring {len(jobs_to_tailor)} CVs in parallel...")
        with ThreadPoolExecutor(max_workers=5) as executor:
            results = executor.map(tailor_single_job, jobs_to_tailor)
            for job_id, pdf_path, success, result in results:
                if success:
                    tailored_cvs[job_id] = pdf_path
                    print(
                        f"  [SUCCESS] Saved tailored CV for job ID {job_id} to: {pdf_path}"
                    )
                else:
                    print(f"  [ERROR] Failed to tailor CV for job ID {job_id}")
                    if result:
                        if result.stdout:
                            print(f"    Stdout: {result.stdout.strip()}")
                        if result.stderr:
                            print(f"    Stderr: {result.stderr.strip()}")

    print("[Phase 3: Tailor] Completed tailoring phase.\n")
    return tailored_cvs
