import argparse
import json
import os
import re
import sys
from pathlib import Path


# Setup path for importing shared_platform and JobHunterKit core
def _setup_sys_path():
    curr = Path(__file__).resolve()
    kit_root = str(curr.parent.parent)
    if kit_root not in sys.path:
        sys.path.insert(0, kit_root)
    for parent in curr.parents:
        if (parent / "shared_platform").is_dir():
            root_path = str(parent)
            if root_path not in sys.path:
                sys.path.insert(0, root_path)
            break


_setup_sys_path()

from core.retry_utils import retry_llm
from shared_platform.llm_client import GeminiClient

# Reconfigure standard output streams to use utf-8 encoding
if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr:
    sys.stderr.reconfigure(encoding="utf-8")

RUBRIC_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "eval_rubric.json",
)


def load_rubric():
    try:
        with open(RUBRIC_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to read eval_rubric.json at {RUBRIC_PATH}: {e}")
        sys.exit(1)


def load_prompt(name: str, fallback_template: str) -> str:
    """Loads a prompt template from config/prompts/{name}.txt, falling back to an in-code generic template."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(
        os.path.dirname(script_dir), "config", "prompts", f"{name}.txt"
    )
    if os.path.exists(prompt_path):
        try:
            with open(prompt_path, encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            print(f"[WARNING] Failed to read prompt from {prompt_path}: {e}")
    return fallback_template


DYNAMIC_RUBRIC_PROMPT_TEMPLATE_FALLBACK = """
You are an expert HR evaluation assistant. Analyze the target Job Description (JD) and produce exactly 4 custom evaluation categories (pillars) with 2-3 specific criteria items for each.
Ensure the sum of all category weights is exactly 100, and the sum of criteria weights within each category matches that category's weight.

Output MUST be ONLY valid JSON matching this schema:
{{
  "version": "1.0",
  "description": "string",
  "pass_threshold": 70,
  "categories": [
    {{
      "id": "string",
      "name": "string",
      "weight_percent": 40,
      "criteria": [
        {{
          "id": "string",
          "name": "string",
          "weight_percent": 20,
          "description": "string"
        }}
      ]
    }}
  ]
}}

JOB DESCRIPTION:
{jd_text}
"""


def _clean_markdown_json(response_text: str) -> str:
    if not response_text:
        return "{}"

    # 1. Search for all fenced code blocks (```json ... ``` or ``` ... ```)
    code_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", response_text)
    for block in code_blocks:
        candidate = block.strip()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, (dict, list)):
                return candidate
        except Exception:
            pass
        if "{" in candidate and "}" in candidate:
            s = candidate.find("{")
            e = candidate.rfind("}")
            sub = candidate[s : e + 1]
            try:
                parsed = json.loads(sub)
                if isinstance(parsed, (dict, list)):
                    return sub
            except Exception:
                pass

    # 2. Try parsing the response directly as JSON
    trimmed = response_text.strip()
    try:
        parsed = json.loads(trimmed)
        if isinstance(parsed, (dict, list)):
            return trimmed
    except Exception:
        pass

    # 3. Find candidate JSON objects via balanced brace/outermost search
    if "{" in trimmed and "}" in trimmed:
        first_brace = 0
        while True:
            first_brace = trimmed.find("{", first_brace)
            if first_brace == -1:
                break
            last_brace = len(trimmed)
            while True:
                last_brace = trimmed.rfind("}", first_brace, last_brace)
                if last_brace == -1 or last_brace <= first_brace:
                    break
                candidate = trimmed[first_brace : last_brace + 1]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, (dict, list)):
                        return candidate
                except Exception:
                    pass
                last_brace = last_brace - 1
            first_brace += 1

    # 4. Fallback extraction: look for score mention or synthesize valid structure
    score_match = re.search(
        r"(?:SCORE|Score|match_score|Final Score Awarded|Final Match Score)[\s:*=]*(\d+(?:\.\d+)?)",
        response_text,
        re.IGNORECASE,
    )
    if score_match:
        score_val = float(score_match.group(1))
        score_val = max(0.0, min(100.0, score_val))
        return json.dumps(
            {
                "breakdown": [],
                "overall_reasoning": response_text[:500].strip(),
                "top_strengths": [
                    "Demonstrated relevant technical and product background"
                ],
                "key_gaps": [],
                "match_score": score_val,
            }
        )

    # 5. Clean basic markdown markers as last resort
    cleaned = trimmed
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    if "{" in cleaned and "}" in cleaned:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        return cleaned[start : end + 1]

    return cleaned


def generate_dynamic_rubric(jd_text: str, api_key: str) -> dict:
    """
    Queries LLM to dynamically synthesize an evaluation rubric tailored specifically
    to the target job description.
    """
    prompt_template = load_prompt(
        "dynamic_rubric", DYNAMIC_RUBRIC_PROMPT_TEMPLATE_FALLBACK
    )
    prompt = prompt_template.format(jd_text=jd_text)
    try:
        response_text = _call_llm_unified(prompt, api_key, json_mode=True)
        cleaned = _clean_markdown_json(response_text)
        try:
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict) or "categories" not in parsed:
                raise KeyError("Parsed dynamic rubric does not contain 'categories'")
            return parsed
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[WARNING] Dynamic rubric validation failed: {e}", flush=True)
            print(f"[WARNING] Raw response: {repr(response_text)}", flush=True)
            print(f"[WARNING] Cleaned text: {repr(cleaned)}", flush=True)
            raise
    except Exception as e:
        print(f"[WARNING] Dynamic rubric generation LLM call failed: {e}")
        return None


def _redistribute_weights(items: list, target_total: int):
    """Redistributes weight_percent of items to sum exactly to target_total."""
    if not items or len(items) == 0:
        print(
            "[WARNING] [_redistribute_weights] Called with empty items list.",
            flush=True,
        )
        return
    total_raw = sum(item.get("weight_percent", 0) for item in items)
    if total_raw > 0:
        running_sum = 0
        for idx, item in enumerate(items):
            if idx == len(items) - 1:
                item["weight_percent"] = target_total - running_sum
            else:
                norm_w = round(
                    (item.get("weight_percent", 0) / total_raw) * target_total
                )
                item["weight_percent"] = norm_w
                running_sum += norm_w
    else:
        print(
            f"[WARNING] [_redistribute_weights] total_raw is {total_raw} <= 0. Evenly redistributing target_total {target_total} across {len(items)} items.",
            flush=True,
        )
        if len(items) == 0:
            print(
                "[ERROR] [_redistribute_weights] len(items) is zero during redistribution fallback!",
                flush=True,
            )
            return
        even_w = target_total // len(items)
        running_sum = 0
        for idx, item in enumerate(items):
            if idx == len(items) - 1:
                item["weight_percent"] = target_total - running_sum
            else:
                item["weight_percent"] = even_w
                running_sum += even_w


def _normalize_categories(categories: list):
    _redistribute_weights(categories, 100)


def _normalize_criteria(categories: list):
    for cat in categories:
        criteria = cat.get("criteria", [])
        if criteria:
            _redistribute_weights(criteria, cat["weight_percent"])


def normalize_rubric_weights(rubric_data: dict) -> dict:
    """
    Programmatically normalizes category and criteria weights to sum exactly to 100%.
    Ensures mathematical compliance and robustness.
    """
    categories = rubric_data.get("categories", [])
    if not categories:
        return rubric_data
    _normalize_categories(categories)
    _normalize_criteria(categories)
    return rubric_data


PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "applicant_profile.json",
)


def load_applicant_profile() -> dict:
    try:
        if os.path.exists(PROFILE_PATH):
            with open(PROFILE_PATH, encoding="utf-8") as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"Warning: Failed to read applicant_profile.json at {PROFILE_PATH}: {e}")
        return {}


def _save_debate_log(output_score_path: str, suffix: str, content: str):
    if not output_score_path:
        return
    base, _ = os.path.splitext(output_score_path)
    if base.endswith("_score"):
        log_path = base[:-6] + suffix
    else:
        log_path = base + suffix
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[AUDIT] Saved intermediate debate log: {log_path}")
    except Exception as e:
        print(f"Warning: Failed to save intermediate log to {log_path}: {e}")

@retry_llm
def _call_llm_unified(prompt: str, api_key: str, json_mode: bool = False) -> str:
    client = GeminiClient()
    return client.call(prompt, json_mode=json_mode)


@retry_llm
def _call_gemini(prompt: str, api_key: str, json_mode: bool = False) -> str:
    client = GeminiClient()
    return client.call(prompt, json_mode=json_mode)


RECRUITER_AUDIT_PROMPT_TEMPLATE_FALLBACK = """
You are an ATS Recruitment Auditor. Compare the candidate's CV and profile against the JD and the rubric criteria.
Identify all gaps, tool deficiencies, or missing experience relative to the requested Rubric Criteria.

JOB DESCRIPTION:
{jd_text}

CANDIDATE CV:
{cv_text}

APPLICANT PROFILE DATA:
{profile_text}

EVALUATION RUBRIC CRITERIA:
{rubric_text}

INSTRUCTIONS:
Provide a detailed markdown audit report of all gaps and suggested points deductions for each criterion.
"""

COACH_ADVOCATE_PROMPT_TEMPLATE_FALLBACK = """
You are a career advocate. Review the recruiter's gap report, candidate's CV, and applicant profile.
Highlight transferable skills and counter-arguments defending the candidate's suitability for the target JD.

JOB DESCRIPTION:
{jd_text}

CANDIDATE CV:
{cv_text}

APPLICANT PROFILE DATA:
{profile_text}

EVALUATION RUBRIC CRITERIA:
{rubric_text}

RECRUITER'S GAP REPORT:
{recruiter_report}

INSTRUCTIONS:
Output your arguments defending the candidate in a clear Markdown advocate report.
"""

JUDGE_SYNTHESIS_PROMPT_TEMPLATE_FALLBACK = """
You are an arbitrating hiring manager. Review the dialectical debate between the recruiter audit and the coach advocate report.
Decide the final deductions (upheld, reduced, or dismissed) and calculate ratings for each criterion.

JOB DESCRIPTION:
{jd_text}

CANDIDATE CV:
{cv_text}

APPLICANT PROFILE DATA:
{profile_text}

EVALUATION RUBRIC CRITERIA:
{rubric_text}

RECRUITER'S GAP REPORT:
{recruiter_report}

COACH'S ADVOCATE REPORT:
{coach_report}

Output MUST be valid JSON matching this schema:
{{
  "breakdown": [
    {{
      "category_id": "<id from rubric>",
      "category_name": "<name>",
      "criteria": [
        {{
          "criterion_id": "<id from rubric>",
          "criterion_name": "<name>",
          "is_applicable": true,
          "deductions": [
            {{
              "gap_type": "<Minor | Major | Critical>",
              "description": "<detailed gap description>",
              "jd_requirement": "<expectation from JD>",
              "cv_evidence": "<present or missing from CV/Profile>",
              "points_deducted": 1
             }}
          ],
          "reasoning": "<justification reasoning>"
        }}
      ]
    }}
  ],
  "overall_reasoning": "<overall summary>",
  "top_strengths": ["<strength 1>"],
  "key_gaps": ["<gap 1>"]
}}
"""


def _build_rubric_text(rubric_data: dict) -> str:
    rubric_text = ""
    for idx, cat in enumerate(rubric_data["categories"], 1):
        rubric_text += (
            f"{idx}. {cat['name']} (Weight: {cat['weight_percent']}% of total score)\n"
        )
        for sub_idx, crit in enumerate(cat["criteria"], 1):
            rubric_text += f"   {idx}.{sub_idx}. {crit['name']} (Weight: {crit['weight_percent']} points max): {crit['description']}\n"
        rubric_text += "\n"
    return rubric_text


def calculate_scores_with_redistribution(raw_result: dict, rubric_data: dict) -> dict:
    """
    Decouples qualitative 0-5 grading from weight calculations.
    Redistributes weight of non-applicable criteria proportionally to active criteria in the same category.
    If an entire category is non-applicable, redistributes its category weight proportionally across other categories.
    """
    if not raw_result.get("breakdown") and "match_score" in raw_result:
        return raw_result

    cat_weights = {
        cat["id"]: cat["weight_percent"] for cat in rubric_data["categories"]
    }
    crit_weights = {}
    for cat in rubric_data["categories"]:
        for crit in cat["criteria"]:
            crit_weights[crit["id"]] = crit["weight_percent"]

    final_breakdown = []
    total_match_score = 0.0

    active_categories = []
    cat_applicable_criteria = {}
    cat_total_applicable_weight = {}
    cat_non_applicable_weight = {}

    for cat_res in raw_result.get("breakdown", []):
        cat_id = cat_res.get("category_id")
        raw_criteria = cat_res.get("criteria", [])

        applicable_crits = []
        non_applicable_weight = 0
        applicable_weight = 0

        for c_res in raw_criteria:
            crit_id = c_res.get("criterion_id")
            orig_weight = crit_weights.get(crit_id, 0)
            is_app = c_res.get("is_applicable", True)

            if is_app:
                applicable_crits.append(c_res)
                applicable_weight += orig_weight
            else:
                non_applicable_weight += orig_weight

        cat_applicable_criteria[cat_id] = applicable_crits
        cat_total_applicable_weight[cat_id] = applicable_weight
        cat_non_applicable_weight[cat_id] = non_applicable_weight

        if applicable_crits:
            active_categories.append(cat_id)

    if not active_categories:
        for cat_res in raw_result.get("breakdown", []):
            cat_id = cat_res.get("category_id")
            for c_res in cat_res.get("criteria", []):
                c_res["is_applicable"] = True
            active_categories.append(cat_id)
            cat_applicable_criteria[cat_id] = cat_res.get("criteria", [])
            cat_total_applicable_weight[cat_id] = sum(
                crit_weights.get(c.get("criterion_id"), 0)
                for c in cat_res.get("criteria", [])
            )
            cat_non_applicable_weight[cat_id] = 0

    cat_redistributed_weights = {}
    if active_categories:
        if total_active_cat_weight := sum(
            cat_weights.get(cat_id, 0) for cat_id in active_categories
        ):
            running_sum = 0
            for idx, cat_id in enumerate(active_categories):
                orig_w = cat_weights.get(cat_id, 0)
                if idx == len(active_categories) - 1:
                    cat_redistributed_weights[cat_id] = 100 - running_sum
                else:
                    norm_w = round((orig_w / total_active_cat_weight) * 100)
                    cat_redistributed_weights[cat_id] = norm_w
                    running_sum += norm_w
        else:
            even_w = 100 // len(active_categories)
            running_sum = 0
            for idx, cat_id in enumerate(active_categories):
                if idx == len(active_categories) - 1:
                    cat_redistributed_weights[cat_id] = 100 - running_sum
                else:
                    cat_redistributed_weights[cat_id] = even_w
                    running_sum += even_w

    for cat_res in raw_result.get("breakdown", []):
        cat_id = cat_res.get("category_id")
        if cat_id not in active_categories:
            inactive_criteria = []
            for c_res in cat_res.get("criteria", []):
                deductions = c_res.get("deductions", [])
                if deductions:
                    total_deductions = sum(
                        int(d.get("points_deducted", 0)) for d in deductions
                    )
                    rating = max(0, 5 - total_deductions)
                else:
                    rating = c_res.get("rating", 5)
                    try:
                        rating = int(rating)
                    except Exception:
                        rating = 5
                    rating = max(0, min(5, rating))
                inactive_criteria.append(
                    {
                        "criterion_id": c_res.get("criterion_id"),
                        "criterion_name": c_res.get("criterion_name"),
                        "score": 0,
                        "max_score": 0,
                        "rating": rating,
                        "is_applicable": False,
                        "deductions": deductions,
                        "reasoning": c_res.get(
                            "reasoning",
                            "Entire category is not applicable for this role.",
                        ),
                    }
                )
            final_breakdown.append(
                {
                    "category_id": cat_id,
                    "category_name": cat_res.get("category_name"),
                    "total_score_for_category": 0,
                    "criteria": inactive_criteria,
                }
            )
            continue

        applicable_crits = cat_applicable_criteria[cat_id]
        total_app_crit_weight = cat_total_applicable_weight[cat_id]
        cat_target_weight = cat_redistributed_weights[cat_id]

        crit_redistributed_weights = {}
        if applicable_crits:
            if total_app_crit_weight > 0:
                running_sum = 0
                for idx, c_res in enumerate(applicable_crits):
                    crit_id = c_res.get("criterion_id")
                    orig_w = crit_weights.get(crit_id, 0)
                    if idx == len(applicable_crits) - 1:
                        crit_redistributed_weights[crit_id] = (
                            cat_target_weight - running_sum
                        )
                    else:
                        norm_w = round(
                            (orig_w / total_app_crit_weight) * cat_target_weight
                        )
                        crit_redistributed_weights[crit_id] = norm_w
                        running_sum += norm_w
            else:
                even_w = cat_target_weight // len(applicable_crits)
                running_sum = 0
                for idx, c_res in enumerate(applicable_crits):
                    crit_id = c_res.get("criterion_id")
                    if idx == len(applicable_crits) - 1:
                        crit_redistributed_weights[crit_id] = (
                            cat_target_weight - running_sum
                        )
                    else:
                        crit_redistributed_weights[crit_id] = even_w
                        running_sum += even_w

        calculated_criteria = []
        category_score_sum = 0.0

        for c_res in cat_res.get("criteria", []):
            crit_id = c_res.get("criterion_id")
            is_app = c_res.get("is_applicable", True)

            deductions = c_res.get("deductions", [])
            if deductions:
                total_deductions = sum(
                    int(d.get("points_deducted", 0)) for d in deductions
                )
                rating = max(0, 5 - total_deductions)
            else:
                rating = c_res.get("rating", 5)
                try:
                    rating = int(rating)
                except Exception:
                    rating = 5
                rating = max(0, min(5, rating))

            if is_app:
                max_score = crit_redistributed_weights.get(crit_id, 0)
                score = round((rating / 5.0) * max_score, 1)
                category_score_sum += score
                calculated_criteria.append(
                    {
                        "criterion_id": crit_id,
                        "criterion_name": c_res.get("criterion_name"),
                        "score": score,
                        "max_score": max_score,
                        "rating": rating,
                        "is_applicable": True,
                        "deductions": deductions,
                        "reasoning": c_res.get("reasoning", ""),
                    }
                )
            else:
                calculated_criteria.append(
                    {
                        "criterion_id": crit_id,
                        "criterion_name": c_res.get("criterion_name"),
                        "score": 0.0,
                        "max_score": 0,
                        "rating": rating,
                        "is_applicable": False,
                        "deductions": deductions,
                        "reasoning": c_res.get(
                            "reasoning",
                            "This criterion is not requested by the Job Description.",
                        ),
                    }
                )

        total_match_score += category_score_sum
        final_breakdown.append(
            {
                "category_id": cat_id,
                "category_name": cat_res.get("category_name"),
                "total_score_for_category": round(category_score_sum, 1),
                "criteria": calculated_criteria,
            }
        )

    rounded_match_score = int(round(total_match_score))

    for cat_item in final_breakdown:
        cat_item["total_score_for_category"] = int(
            round(cat_item["total_score_for_category"])
        )
        for crit_item in cat_item["criteria"]:
            crit_item["score"] = int(round(crit_item["score"]))

    return {
        "breakdown": final_breakdown,
        "match_score": rounded_match_score,
        "overall_reasoning": raw_result.get("overall_reasoning", ""),
        "top_strengths": raw_result.get("top_strengths", []),
        "key_gaps": raw_result.get("key_gaps", []),
    }


def score_job_description(
    jd_text: str, cv_text: str, rubric_data: dict, output_score: str = None
) -> dict:
    """
    Evaluates a Job Description against a Base CV using Gemini REST API and a dynamic rubric. (UC-003)
    """
    print("[UTOP|func|score_job_description|cp-fr-008]")
    if rubric_data and rubric_data.get("is_irrelevant"):
        return {
            "match_score": 0,
            "overall_reasoning": "Job did not pass the role relevance filter (not related to senior AI leadership, AI PM, or AI transformation).",
            "breakdown": [],
            "top_strengths": [],
            "key_gaps": [
                "Role mismatch: Job is not an AI Director / Head of AI / AI PM / AI Transformation role."
            ],
        }
    from dotenv import load_dotenv

    env_path = os.path.join(os.path.expanduser("~"), ".gemini", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)

    api_key = os.environ.get("GEMINI_API_KEY")

    profile_data = load_applicant_profile()
    profile_text = json.dumps(profile_data, indent=2)
    rubric_text = _build_rubric_text(rubric_data)

    print("Step 1: Running Recruiter Auditor gap audit...")
    recruiter_template = load_prompt(
        "recruiter_audit", RECRUITER_AUDIT_PROMPT_TEMPLATE_FALLBACK
    )
    recruiter_prompt = recruiter_template.format(
        jd_text=jd_text,
        cv_text=cv_text,
        profile_text=profile_text,
        rubric_text=rubric_text,
    )
    try:
        recruiter_report = _call_gemini(recruiter_prompt, api_key, json_mode=False)
    except Exception as e:
        print(f"Recruiter Auditor failed: {e}")
        return {
            "match_score": 0,
            "overall_reasoning": f"Recruiter API Error: {str(e)}",
            "breakdown": [],
            "top_strengths": [],
            "key_gaps": [],
        }

    _save_debate_log(output_score, "_recruiter_audit.md", recruiter_report)

    print("Step 2: Running Career Coach Advocate defense...")
    coach_template = load_prompt(
        "coach_defense", COACH_ADVOCATE_PROMPT_TEMPLATE_FALLBACK
    )
    coach_prompt = coach_template.format(
        jd_text=jd_text,
        cv_text=cv_text,
        profile_text=profile_text,
        rubric_text=rubric_text,
        recruiter_report=recruiter_report,
    )
    try:
        coach_report = _call_gemini(coach_prompt, api_key, json_mode=False)
    except Exception as e:
        print(f"Career Coach Advocate failed: {e}")
        return {
            "match_score": 0,
            "overall_reasoning": f"Coach API Error: {str(e)}",
            "breakdown": [],
            "top_strengths": [],
            "key_gaps": [],
        }

    _save_debate_log(output_score, "_coach_defense.md", coach_report)

    print("Step 3: Running Arbitrating Judge synthesis...")
    judge_template = load_prompt(
        "judge_synthesis", JUDGE_SYNTHESIS_PROMPT_TEMPLATE_FALLBACK
    )
    judge_prompt = judge_template.format(
        jd_text=jd_text,
        cv_text=cv_text,
        profile_text=profile_text,
        rubric_text=rubric_text,
        recruiter_report=recruiter_report,
        coach_report=coach_report,
    )
    try:
        judge_response = _call_gemini(judge_prompt, api_key, json_mode=True)
        cleaned_text = _clean_markdown_json(judge_response)
        try:
            raw_result = json.loads(cleaned_text)
        except json.JSONDecodeError as jde:
            print(
                "[ERROR] [score_jd] Arbitrating Judge returned invalid JSON.",
                flush=True,
            )
            print(
                f"[ERROR] [score_jd] Raw judge_response: {repr(judge_response)}",
                flush=True,
            )
            print(f"[ERROR] [score_jd] Cleaned text: {repr(cleaned_text)}", flush=True)
            raise RuntimeError(f"JSONDecodeError: {str(jde)}")
    except Exception as e:
        print(f"Arbitrating Judge failed: {e}")
        return {
            "match_score": 0,
            "overall_reasoning": f"Judge API Error: {str(e)}",
            "breakdown": [],
            "top_strengths": [],
            "key_gaps": [],
        }

    return calculate_scores_with_redistribution(raw_result, rubric_data)


def _validate_file_path(file_path: str) -> Path:
    p = Path(file_path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not p.is_file():
        raise ValueError(f"Path is not a file: {file_path}")
    return p


def _read_jd_file(jd_file: str) -> str:
    try:
        with open(jd_file, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"Failed to read JD file: {e}")
        sys.exit(1)


def _read_cv_file(cv_file: str) -> str:
    try:
        if cv_file.lower().endswith(".pdf"):
            import fitz

            doc = fitz.open(cv_file)
            cv_text = "".join(page.get_text() for page in doc)
            doc.close()
            return cv_text
        else:
            with open(cv_file, encoding="utf-8") as f:
                return f.read()
    except Exception as e:
        print(f"Failed to read CV file: {e}")
        sys.exit(1)


def check_role_relevance(jd_text: str, api_key: str, job_title: str = None) -> bool:
    """
    Checks if the job description is relevant to senior AI leadership,
    AI Product Management, or AI Enterprise Transformation roles.
    Enforces minimum seniority (Manager or above) and salary constraints ($3.5k net).
    """
    profile = load_applicant_profile()
    prefs = profile.get("preferences", {})
    min_level = prefs.get("min_seniority_level", "Manager").lower()
    min_salary = prefs.get("min_preferred_salary_net_usd", 3500)

    if not job_title and jd_text:
        # Fallback: try to extract job title from the first line of the JD text if it looks like one
        first_line = jd_text.split("\n")[0].strip()
        if len(first_line) > 5 and len(first_line) < 100:
            job_title = first_line

    if job_title:
        title_lower = job_title.lower()
        import re

        # Tokens split by non-alphanumeric characters
        tokens = set(re.findall(r"[a-z0-9]+", title_lower))

        # Heuristic Seniority Exclusions
        is_target_seniority = any(
            w in tokens
            for w in {
                "manager",
                "director",
                "head",
                "chief",
                "vp",
                "lead",
                "leader",
                "leadership",
                "principal",
                "cto",
            }
        )
        exclude_words = {
            "intern",
            "internship",
            "trainee",
            "fresh",
            "fresher",
            "entry",
            "junior",
            "assistant",
            "student",
            "coop",
            "co-op",
            "internships",
        }
        has_exclusion = any(w in tokens for w in exclude_words)
        has_associate = "associate" in tokens and not is_target_seniority

        # Heuristic Exclusions for Tech Lead & Developer (not suitable)
        is_tech_lead_or_dev = False
        dev_words = {
            "developer",
            "programmer",
            "coder",
            "backend",
            "frontend",
            "fullstack",
            "software",
            "engineer",
        }
        if any(w in tokens for w in dev_words):
            if "architect" not in tokens and "prompt" not in tokens:
                is_tech_lead_or_dev = True

        # Exclude tech lead / technical lead / engineering lead
        if "lead" in tokens and any(
            w in tokens for w in {"tech", "technical", "engineering", "development"}
        ):
            is_tech_lead_or_dev = True

        if has_exclusion or has_associate or is_tech_lead_or_dev:
            print(
                f"[RELEVANCE FILTER] Heuristic seniority/role exclusion found in title: '{job_title}'. Skipping.",
                flush=True,
            )
            return False

        # Heuristic Inclusions for target role fit
        ai_words = {
            "ai",
            "ml",
            "llm",
            "nlp",
            "genai",
            "generative",
            "learning",
            "intelligence",
        }
        has_ai = (
            any(w in tokens for w in ai_words)
            or "machine learning" in title_lower
            or "artificial intelligence" in title_lower
        )

        # Senior Product Manager heuristic inclusion
        pm_words = {"product"}
        has_pm = any(w in tokens for w in pm_words)

        if (has_ai or has_pm) and is_target_seniority:
            # Skip LLM check ONLY if there is no mention of salary in the JD text
            has_salary_mention = any(
                kw in jd_text.lower()
                for kw in {
                    "$",
                    "vnd",
                    "usd",
                    "salary",
                    "compensation",
                    "lương",
                    "thu nhập",
                    "triệu",
                }
            )
            if not has_salary_mention:
                print(
                    f"[RELEVANCE FILTER] Heuristic match found in title: '{job_title}' (No salary mention). Skipping LLM check.",
                    flush=True,
                )
                return True

    prompt = f"""
You are a job relevance filter. Evaluate if the target Job Description (JD) represents a role that matches the candidate's target profile and preferences.

CANDIDATE TARGET PROFILE:
Senior Product Management, AI/ML Leadership, AI/ML Product Management, AI Systems/Enterprise Architecture, or AI/ML Enterprise Transformation/Enablement.
Must be a {min_level.upper()} level or above (e.g., Manager, Senior Manager, Lead, Director, Head of, VP, Chief, CTO, Principal).
Salary preference: At least ${min_salary} net USD/month (approx. ${min_salary} net, or equivalent in VND: {min_salary * 25 / 1000}M net / {min_salary * 25 / 1000 * 1.2}M gross per month), if salary is mentioned.

JOB DESCRIPTION:
{jd_text}

INSTRUCTIONS:
Evaluate if this job description meets ALL the criteria below:
1. Seniority & Role Type Check: The role MUST be at least a Manager, Lead, Principal, Director, Head, VP, Chief, CTO, or AI Systems/Enterprise Architect. Answer "NO" if the role is a hands-on developer, coder, programmer, software engineer, ML/AI engineer, Tech Lead, Technical Lead, or Engineering Lead (even if senior or lead), as the candidate is not suitable for hands-on developer or team/tech lead roles.
2. Salary Check: If salary is explicitly mentioned in the JD or title, it must be at least ${min_salary} net USD/month (or equivalent: ~VND {min_salary * 25 / 1000}M net, or ~VND {min_salary * 25 / 1000 * 1.2}M gross). If the listed salary is lower, answer "NO". If salary is not mentioned, ignore this rule.
3. Domain & Function Check: The role must have a primary focus on product management, AI strategy, systems architecture, or digital/business transformation. Senior Product Manager roles at reputable organizations are acceptable even without explicit AI/ML focus. Answer "NO" for general software development, backend/frontend engineering, QA, DevOps, or hands-on programming roles. The candidate is a vibe coder and systems architect, not an individual contributor developer or tech lead.
4. Answer "YES" if the role meets ALL the criteria: is a Manager/Lead level or above, is related to product management or AI/ML, is not a hands-on developer or tech lead, and satisfies the salary minimum (if stated).

Output MUST be exactly "YES" or "NO" (one word, case-insensitive, no other text or explanation).
"""
    try:
        response = _call_llm_unified(prompt, api_key, json_mode=False)
        result = response.strip().upper()
        print(f"[RELEVANCE FILTER] LLM response: {result}", flush=True)
        return "YES" in result
    except Exception as e:
        print(
            f"[WARNING] Relevance check failed: {e}. Defaulting to NO (skip job).",
            flush=True,
        )
        return False


def _handle_dynamic_rubric(
    jd_text: str, output_score: str, job_title: str = None
) -> dict:
    from dotenv import load_dotenv

    env_path = os.path.join(os.path.expanduser("~"), ".gemini", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)

    api_key = os.environ.get("GEMINI_API_KEY")

    # Check role relevance first
    if not check_role_relevance(jd_text, api_key, job_title):
        print(
            "[RELEVANCE FILTER] Job does not match target profile (AI Director/Head of AI/AI PM/AI Transformation). Skipping.",
            flush=True,
        )
        return {"is_irrelevant": True}

    print("Generating dynamic rubric tailored to JD...")
    rubric_data = generate_dynamic_rubric(jd_text, api_key)
    if not rubric_data:
        print("Failed to generate dynamic rubric. Falling back to static rubric.")
        return None

    print("Successfully generated dynamic rubric. Normalizing weights...")
    rubric_data = normalize_rubric_weights(rubric_data)

    print("\n--- Normalized Dynamic Rubric Categories ---")
    total_cat_weight = 0
    for cat in rubric_data.get("categories", []):
        crit_sum = sum(
            crit.get("weight_percent", 0) for crit in cat.get("criteria", [])
        )
        print(
            f"- {cat['name']} ({cat['id']}): Weight = {cat['weight_percent']}%, Criteria Sum = {crit_sum}%"
        )
        total_cat_weight += cat["weight_percent"]
    print(f"Total Category Weight Sum = {total_cat_weight}%\n")

    if output_score:
        rubric_out_path = output_score.replace("_score.json", "_rubric.json")
        try:
            os.makedirs(os.path.dirname(rubric_out_path), exist_ok=True)
            with open(rubric_out_path, "w", encoding="utf-8") as rf:
                json.dump(rubric_data, rf, indent=2, ensure_ascii=False)
            print(f"[AUDIT] Dynamic rubric saved to: {rubric_out_path}")
        except Exception as re:
            print(f"Failed to save dynamic rubric: {re}")

    return rubric_data


def _save_score_audit(
    output_score: str,
    rubric_data: dict,
    threshold: int,
    result: dict,
    jd_file: str,
    cv_file: str,
):
    os.makedirs(os.path.dirname(output_score), exist_ok=True)
    audit_record = {
        "rubric_version": rubric_data.get("version", "unknown"),
        "pass_threshold": threshold,
        "jd_file": jd_file,
        "cv_file": cv_file,
        **result,
    }
    with open(output_score, "w", encoding="utf-8") as f:
        json.dump(audit_record, f, indent=2, ensure_ascii=False)
    print(f"\n[AUDIT] Score saved to: {output_score}")


def main():
    parser = argparse.ArgumentParser(
        description="Score a Job Description against a Base CV."
    )
    parser.add_argument(
        "--jd-file", required=True, help="Path to the Job Description text file"
    )
    parser.add_argument(
        "--cv-file", required=True, help="Path to the Base CV file (PDF or text)"
    )
    parser.add_argument(
        "--output-score",
        default=None,
        help="Optional path to save full score JSON for audit trail",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="Override pass threshold (default: read from rubric)",
    )
    parser.add_argument(
        "--dynamic-rubric",
        action="store_true",
        dest="dynamic_rubric",
        default=True,
        help="Generate scoring rubric dynamically tailored to JD",
    )
    parser.add_argument(
        "--no-dynamic-rubric",
        action="store_false",
        dest="dynamic_rubric",
        help="Disable dynamic rubric generation",
    )
    parser.add_argument(
        "--rubric-file",
        default=None,
        help="Path to a predefined rubric JSON file to skip generation",
    )

    args = parser.parse_args()
    jd_text = _read_jd_file(args.jd_file)
    cv_text = _read_cv_file(args.cv_file)

    rubric_data = None
    if args.rubric_file:
        try:
            with open(args.rubric_file, encoding="utf-8") as f:
                rubric_data = json.load(f)
            print(f"Loaded predefined rubric from {args.rubric_file}")
        except Exception as e:
            print(f"Failed to load rubric file {args.rubric_file}: {e}")
            sys.exit(1)
    elif args.dynamic_rubric:
        rubric_data = _handle_dynamic_rubric(jd_text, args.output_score)

    if rubric_data is None:
        print("Loading default static rubric...")
        rubric_data = load_rubric()

    threshold = (
        args.threshold
        if args.threshold is not None
        else rubric_data.get("pass_threshold", 70)
    )

    print(f"Evaluating '{args.jd_file}' against '{args.cv_file}'...")
    result = score_job_description(jd_text, cv_text, rubric_data, args.output_score)

    print("\n--- Evaluation Result ---")
    print(json.dumps(result, indent=2))

    if args.output_score:
        _save_score_audit(
            args.output_score,
            rubric_data,
            threshold,
            result,
            args.jd_file,
            args.cv_file,
        )

    sys.exit(0 if result.get("match_score", 0) >= threshold else 2)


if __name__ == "__main__":
    main()
