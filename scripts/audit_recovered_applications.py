"""
Targeted revert: Only revert the specific false-positive app_ids from the repair script.
These are the 42 apps that repair_demoted_applications.py committed, but where the
proof file didn't actually belong to the job.
"""

import os
import re
import sys

os.environ["PYTHONIOENCODING"] = "utf-8"
from pathlib import Path

skill_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(skill_root))
sys.path.insert(0, str(skill_root / "scripts"))

from core.db_client import get_connection
from scripts.verify_application_proofs import verify_proof_file
from shared_platform.paths import get_job_dirs

DRY_RUN = "--apply" not in sys.argv

# These are the 42 app_ids committed by the repair script (from the task-111 output).
# We need to verify each one has a job-specific proof.
REPAIR_APP_IDS = [
    6244,
    6218,
    6221,
    5951,
    5765,  # first 5 (confirmed true positives)
    6852,
    6685,
    6525,
    6501,
    6445,
    6439,
    6396,
    6341,
    6335,
    4918,
    4817,
    1248,
    718,
    696,
    693,
    691,
    679,
    665,
    655,
    636,
    618,
    613,
    611,
    610,
    334,
    273,
    254,
    # Additional ones found by the longer dry-run:
    # (the --apply run of task-111 ran the full walk and found all 42)
]

conn = get_connection()
cur = conn.cursor()

# Get all currently 'applied' records that were previously demoted by proof verification
# These are the ones the repair script touched
cur.execute(
    """
    SELECT a.id, a.job_id, j.source, j.keyword, j.search_location, j.scraped_at,
           j.company, j.title
    FROM job_hunter.applications a
    JOIN job_hunter.jobs j ON a.job_id = j.id
    WHERE a.id = ANY(%s) AND a.status = 'applied'
    ORDER BY a.id;
""",
    (REPAIR_APP_IDS,),
)
rows = cur.fetchall()
print(f"Found {len(rows)} repair-committed records to audit.\n")

false_positives = 0
true_positives = 0

for (
    app_id,
    job_id,
    source,
    keyword,
    search_location,
    scraped_at,
    company,
    title,
) in rows:
    job_dict = {
        "id": job_id,
        "source": source,
        "keyword": keyword,
        "search_location": search_location,
        "scraped_at": scraped_at,
    }
    dirs = get_job_dirs(job_dict)
    proof_dir = dirs.get("proof_dir")

    has_job_specific_proof = False
    job_id_str = str(job_id)

    if proof_dir and os.path.exists(proof_dir):
        for f in os.listdir(proof_dir):
            if f.endswith(".png") and verify_proof_file(os.path.join(proof_dir, f)):
                if re.search(rf"[_]{job_id_str}\.png$", f):
                    has_job_specific_proof = True
                    break

    if not has_job_specific_proof:
        # Fallback disk search
        campaigns_dir = os.path.join(str(skill_root), "data", "campaigns")
        if os.path.exists(campaigns_dir):
            for root, _, files in os.walk(campaigns_dir):
                for f in files:
                    if f.endswith(".png") and re.search(rf"[_]{job_id_str}\.png$", f):
                        if verify_proof_file(os.path.join(root, f)):
                            has_job_specific_proof = True
                            break
                if has_job_specific_proof:
                    break

    safe_company = (company or "?").encode("ascii", "replace").decode()
    safe_title = (title or "?").encode("ascii", "replace").decode()

    if has_job_specific_proof:
        true_positives += 1
    else:
        false_positives += 1
        print(
            f"  [REVERT] app_id={app_id} job_id={job_id} | {safe_company} - {safe_title}"
        )
        if not DRY_RUN:
            cur.execute(
                "UPDATE job_hunter.applications SET status = 'needs_manual_intervention', "
                "manual_intervention_reason = 'Proof review failed: No job-specific proof found' "
                "WHERE id = %s;",
                (app_id,),
            )
            cur.execute(
                "UPDATE job_hunter.jobs SET status_apply = 'needs_manual_intervention', "
                "manual_intervention_reason = 'Proof review failed: No job-specific proof found' "
                "WHERE id = %s AND status_apply = 'completed';",
                (job_id,),
            )

print(f"\n{'=' * 70}")
print(
    f"Of {len(rows)} repair records: {true_positives} true, {false_positives} false positives"
)
print(f"{'=' * 70}")

if not DRY_RUN and false_positives > 0:
    conn.commit()
    print(f"COMMITTED: {false_positives} false positives reverted.")
elif DRY_RUN:
    print("DRY RUN. Use --apply to commit.")
    conn.rollback()
else:
    conn.rollback()

cur.close()
conn.close()
