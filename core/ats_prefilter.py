"""
ATS Pre-filter for JobHunterKit.
Calculates a fast, cheap heuristic score of job relevance to filter out obviously
unsuitable JDs before hitting expensive LLM call paths.
"""

import re

# Candidate preferences and profile metrics (hardcoded from config/applicant_profile.json for speed)
CANDIDATE_TOTAL_EXPERIENCE = 7

CANDIDATE_SKILL_CATEGORIES = {
    "product_management": [
        "product management",
        "product manager",
        "product lead",
        "product owner",
        "pm",
        "po",
        "product lifecycle",
        "monetization",
        "roadmap",
        "backlog",
        "quản lý sản phẩm",
        "quản trị sản phẩm",
        "chủ sản phẩm",
        "phát triển sản phẩm",
        "trưởng nhóm sản phẩm",
        "giám đốc sản phẩm",
        "chuyên viên sản phẩm",
        "chuyên viên cao cấp",
        "quản lý dự án",
        "quản trị dự án",
    ],
    "ai_ml": [
        "ai",
        "ml",
        "machine learning",
        "artificial intelligence",
        "llm",
        "genai",
        "generative",
        "prompt engineering",
        "nlp",
        "deep learning",
        "transformer",
        "trí tuệ nhân tạo",
        "học máy",
        "xử lý ngôn ngữ tự nhiên",
        "dữ liệu lớn",
    ],
    "saas": ["saas", "software as a service", "b2b", "subscription", "nền tảng số", "giải pháp phần mềm"],
    "leadership": [
        "leadership",
        "manager",
        "director",
        "head of",
        "people management",
        "stakeholder management",
        "chief",
        "vp",
        "trưởng phòng",
        "giám đốc",
        "trưởng nhóm",
        "quản lý đội ngũ",
        "quản lý nhân sự",
        "chuyên gia",
        "lãnh đạo",
    ],
    "data_analysis": [
        "data analysis",
        "analytics",
        "experimentation",
        "ab testing",
        "metrics",
        "phân tích dữ liệu",
        "thử nghiệm a/b",
        "chỉ số kpi",
    ],
}

RESUME_KEYWORDS = {
    "product",
    "ai",
    "ml",
    "management",
    "leadership",
    "strategy",
    "saas",
    "enterprise",
    "transformation",
    "systems",
    "architecture",
    "agile",
    "scrum",
    "data",
    "experimentation",
    "monetization",
    "growth",
    "roadmap",
    "lifecycle",
    "stakeholder",
    "analytics",
    "llm",
    "generative",
}


def calculate_ats_score(jd_text: str) -> float:
    """
    Calculates a weighted ATS pre-filter score from 0.0 to 1.0 based on:
    - Skill categories matched: 40%
    - Experience requirement check: 30%
    - Education match: 20%
    - Resume keyword overlap: 10%

    Note: the weighted-average scoring concept (skill/experience/education/keyword buckets)
    was adapted from reviewing the AutoApply-AI public repository during initial design.
    """
    if not jd_text:
        return 0.0

    from core.company_extractor import is_jd_text_expired

    is_expired, _ = is_jd_text_expired(jd_text)
    if is_expired:
        return 0.0

    jd_lower = jd_text.lower()
    jd_tokens = set(re.findall(r"[a-z0-9]+", jd_lower))

    # 1. Skill Score (40%)
    matched_categories = 0
    for category, keywords in CANDIDATE_SKILL_CATEGORIES.items():
        # Check if any keyword in the category is in the JD text with word boundaries
        if any(re.search(r"\b" + re.escape(kw) + r"\b", jd_lower) for kw in keywords):
            matched_categories += 1
    skill_score = (
        matched_categories / len(CANDIDATE_SKILL_CATEGORIES)
        if CANDIDATE_SKILL_CATEGORIES
        else 1.0
    )

    # 2. Experience Score (30%)
    # Find patterns like "5+ years", "3-5 years", "7 years of experience"
    exp_matches = re.findall(
        r"(\d+)\s*(?:\+|-|\s*to\s*\d+)?\s*years?(?:\s+of\s+experience)?",
        jd_lower,
    )
    if exp_matches:
        try:
            req_years = max(int(m) for m in exp_matches)
        except ValueError:
            req_years = 0
    else:
        req_years = 0

    if req_years == 0:
        experience_score = 1.0
    elif CANDIDATE_TOTAL_EXPERIENCE >= req_years:
        experience_score = 1.0
    else:
        # Penalize if they require more than the candidate's total experience
        experience_score = CANDIDATE_TOTAL_EXPERIENCE / req_years

    # 3. Education Score (20%)
    # Candidate highest degree: Bachelor
    has_phd = "phd" in jd_lower or "ph.d" in jd_lower or "doctorate" in jd_lower
    has_master = (
        "master" in jd_lower or "mba" in jd_lower or "graduate degree" in jd_lower
    )
    has_bachelor = "bachelor" in jd_lower or "undergraduate" in jd_lower

    if has_phd and not has_bachelor:
        education_score = 0.5
    elif has_master and not has_bachelor:
        education_score = 0.8
    else:
        education_score = 1.0

    # 4. Keyword Score (10%)
    intersection = RESUME_KEYWORDS.intersection(jd_tokens)
    keyword_score = len(intersection) / len(RESUME_KEYWORDS) if RESUME_KEYWORDS else 1.0

    # If there are zero matched categories, the job is completely irrelevant
    if skill_score == 0.0:
        return 0.0

    # Otherwise, calculate score and scale it by skill_score to emphasize domain match
    total_score = skill_score * (
        0.5 * experience_score + 0.3 * education_score + 0.2 * keyword_score
    )
    return total_score


def should_skip_jd(jd_text: str, threshold: float = 0.10) -> tuple[bool, float]:
    """
    Returns a tuple of (should_skip, score).
    """
    score = calculate_ats_score(jd_text)
    return score < threshold, score
