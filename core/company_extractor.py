"""
Company name extraction and expired JD detection helpers for JobHunterKit.
"""

import re

from shared_platform.logging_setup import checkpointed_function

EXPIRED_KEYWORDS = [
    "job expired",
    "expired job",
    "hết hạn tuyển dụng",
    "tin tuyển dụng này đã hết hạn",
    "tin tuyển dụng đã hết hạn",
    "hạn nộp hồ sơ đã hết",
    "đã hết hạn nhận hồ sơ",
    "không còn nhận hồ sơ",
    "đã dừng nhận hồ sơ",
    "ngừng nhận hồ sơ",
    "đã đóng tuyển dụng",
    "vị trí này đã đóng",
    "this job is no longer accepting applications",
    "no longer accepting applications",
    "not accepting applications",
    "applications are no longer being accepted",
    "applications are closed",
    "applications closed",
    "job is closed",
    "posting is closed",
    "position is closed",
    "this job posting is no longer available",
    "this job is closed",
    "job posting not found",
    "hết hạn ứng tuyển",
    "đã hết hạn",
    "hết thời hạn ứng tuyển",
]


@checkpointed_function("FL-301", use_case_id="UC-001", node_name="scrape_node")
def is_jd_text_expired(jd_text: str, page_title: str = "") -> tuple[bool, str]:
    """
    Checks whether raw JD text or page title indicates that the job is expired/closed.
    Returns (is_expired, reason).
    """
    text_lower = str(jd_text or "").lower()
    title_lower = str(page_title or "").lower()

    # 1. Page title checks (highest fidelity)
    for kw in EXPIRED_KEYWORDS:
        if kw in title_lower:
            return True, f"Page title contains expired keyword: '{kw}'"

    if re.search(r"\b(expired|hết hạn|closed|đã đóng)\b", title_lower):
        return True, "Page title indicates expired status"

    # 2. Check top 10 header lines (where portal banners / badges reside)
    lines = [line.strip().lower() for line in text_lower.splitlines() if line.strip()]
    for line in lines[:10]:
        clean_line = re.sub(r"[^\w\s]", "", line).strip()
        if clean_line in (
            "expired",
            "het han",
            "job expired",
            "da het han",
            "closed",
            "da dong",
            "ngung nhan ho so",
        ):
            return True, f"Header line indicates expired status: '{line}'"
        for kw in EXPIRED_KEYWORDS:
            if kw in line:
                return True, f"Header banner indicates expired status: '{kw}'"

    # 3. Exact full-body disclaimers (distinctive phrases anywhere in JD text)
    distinctive_full_body_phrases = [
        "this job is no longer accepting applications",
        "no longer accepting applications",
        "not accepting applications",
        "applications are no longer being accepted",
        "applications are closed",
        "this job posting is no longer available",
        "this job is closed",
        "this position is no longer accepting applications",
        "posting is closed",
        "position has been filled",
        "tin tuyển dụng này đã hết hạn",
        "tin tuyển dụng đã hết hạn",
        "tin tuyển dụng đã đóng",
        "không còn nhận hồ sơ",
        "đã dừng nhận hồ sơ",
        "ngừng nhận hồ sơ",
        "đã hết hạn nhận hồ sơ",
        "đã hết hạn ứng tuyển",
        "job posting not found",
    ]
    for phrase in distinctive_full_body_phrases:
        if phrase in text_lower:
            return True, f"JD text contains definitive closed notice: '{phrase}'"

    return False, ""


@checkpointed_function("FL-302", use_case_id="UC-001", node_name="scrape_node")
def extract_company_name(
    jd_text: str = "",
    page_title: str = "",
    page_url: str = "",
    page=None,
) -> str:
    """
    Extracts company name from Playwright page DOM, page title, or JD text.
    Returns extracted company name or 'Unknown Company'.
    """
    # 1. Extract from page title (highest fidelity for ITviec, TopCV, LinkedIn)
    # e.g., "Technical Product Marketing Manager at Bosch Global Software Technologies Company Limited | ITviec"
    # e.g., "Tuyển dụng Product Manager tại Công Ty ABC - TopCV"
    # e.g., "Tuyển Chuyên Viên Product Owner làm việc tại Công ty Liên doanh Vận chuyển Quốc tế Hải Vân"
    if page_title:
        title_company = _extract_company_from_title(page_title)
        if title_company:
            return title_company

    # 2. Inspect active Playwright page DOM if available (scoped to job header/details first)
    if page:
        try:
            selectors = [
                ".job-details__sub-title a",
                ".job-details__overview a[href*='/companies/']",
                ".job-header-info a[href*='/companies/']",
                ".box-company-info__detail a.name",
                ".box-company-info a.name",
                "div.job-header__company-name",
                ".job-details__company-name",
                'a[href*="/cong-ty/"]',
                'a[href*="/companies/"]',
                "h3.company-name",
                "a.company-name",
                "div.company-name",
                "span.company-name",
                "p.company-name",
                ".employer-name",
                "div.text-rich-grey",
            ]
            for sel in selectors:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        for idx in range(min(loc.count(), 3)):
                            text = loc.nth(idx).inner_text().strip()
                            if (
                                text
                                and len(text) > 1
                                and not _is_generic_site_name(text)
                            ):
                                return _clean_company_name(text)
                except Exception:
                    pass
        except Exception:
            pass

    # 3. Extract from URL slug if available (e.g. ITviec /it-jobs/title-company-id)
    if page_url and "itviec.com/it-jobs/" in page_url:
        try:
            slug = page_url.split("/it-jobs/")[-1].split("?")[0].strip("/")
            parts = slug.split("-")
            if len(parts) >= 2 and parts[-1].isdigit():
                # Remove trailing ID and take remaining company part
                comp_slug = "-".join(parts[-3:-1]) if len(parts) >= 4 else parts[-2]
                comp_name = comp_slug.replace("-", " ").title()
                if comp_name and not _is_generic_site_name(comp_name):
                    return comp_name
        except Exception:
            pass

    # 4. Extract from JD text headers
    if jd_text:
        jd_company = _extract_company_from_jd_text(jd_text)
        if jd_company:
            return jd_company

    return "Unknown Company"


def _is_generic_site_name(name: str) -> bool:
    lower = name.lower().strip()
    return lower in (
        "itviec",
        "topcv",
        "vietnamworks",
        "glints",
        "linkedin",
        "careerjet",
        "indeed",
        "unknown company",
        "unknown title",
        "easy apply",
        "apply now",
        "ứng tuyển",
        "pro",
    )


def _clean_company_name(name: str) -> str:
    cleaned = name.strip()
    # Remove trailing site suffixes
    cleaned = re.sub(
        r"\s*[\|\-–—]\s*(ITviec|TopCV|VietnamWorks|Glints|LinkedIn|Indeed|Careerjet).*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^\s*(Company|Công ty|Employer|Nhà tuyển dụng)\s*[:=]\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


def _extract_company_from_title(title: str) -> str:
    # Pattern 1: "... at Company Name | Platform"
    at_match = re.search(r"\bat\s+([^\|\-–—\n]+)", title, re.IGNORECASE)
    if at_match:
        comp = _clean_company_name(at_match.group(1))
        if comp and not _is_generic_site_name(comp):
            return comp

    # Pattern 2: "... (làm việc) tại Company Name - Platform"
    tai_match = re.search(
        r"\b(?:làm việc\s+)?tại\s+([^\|\-–—\n]+)", title, re.IGNORECASE
    )
    if tai_match:
        comp = _clean_company_name(tai_match.group(1))
        if comp and not _is_generic_site_name(comp):
            return comp

    return ""


def _extract_company_from_jd_text(text: str) -> str:
    # Match "Company: ABC Ltd" or "Công ty: ABC"
    m = re.search(
        r"^\s*(?:Company|Công ty|Employer|Nhà tuyển dụng)\s*[:=]\s*([^\n\r]+)",
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    if m:
        comp = _clean_company_name(m.group(1))
        if comp and not _is_generic_site_name(comp):
            return comp
    return ""
