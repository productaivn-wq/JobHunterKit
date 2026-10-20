# DOC-15: Applicant Profile Onboarding & Ingestion Audit

**Target Component**: `scripts/setup_profile.py`, `20_ACTIVE_CONTINUOUS/cv_text.txt`, `config/applicant_profile.json`  
**Evaluation Scope**: Interactive CLI onboarding wizard, PDF, HTML, and TXT CV text extraction, candidate profile structuring (`config/applicant_profile.json`), LLM retry fallback, master CV persistence.  
**Implementation Grade**: **100 / 100 (PRODUCTION GRADE SSOT)**

---

## 1. Executive Summary

`setup_profile.py` provides the onboarding engine for candidate profile initialization and ingestion. It extracts structured text from candidate documents (PDF, HTML, TXT), uses LLM extraction to infer contact details, competencies, and career history, and builds `config/applicant_profile.json` while synchronizing with the continuous career zone `20_ACTIVE_CONTINUOUS/cv_text.txt`.

---

## 2. Functions & Implementation (`FL-001` to `FL-006`)

| Function | Identifier | Responsibility |
|:---|:---|:---|
| `extract_cv_text` | `FL-001` | Parses input file formats (PyPDF2/pdfplumber for PDF, BeautifulSoup for HTML, UTF-8 text reader). |
| `extract_profile_from_cv` | `FL-002` | Queries Gemini to transform raw candidate text into structured profile JSON schema. |
| `prompt_user` / `prompt_user_number` | `FL-003`, `FL-004` | CLI prompt handlers for candidate verification. |
| `build_profile_interactive` | `FL-005` | Interactive validation loop ensuring mandatory profile keys exist. |
| `main` | `FL-006` | CLI entry point accepting `--cv-file` arguments and triggering profile builds. |

---

## 3. Candidate Profile Schema (`applicant_profile.json`)

```json
{
  "full_name": "Phương Võ",
  "email": "applicant@example.com",
  "phone": "+84 90 000 0000",
  "location": "Ha Noi, Viet Nam",
  "linkedin_url": "linkedin.com/in/applicant/",
  "parsed_cv_text": "...",
  "target_roles": ["Chief AI Officer", "Head of AI", "Product Director", "AI Solutions Architect"],
  "target_locations": ["Vietnam", "Singapore", "Remote"],
  "learned_answers": {}
}
```

---

## 4. Verification & Status

- **Traceability Mapping**: `UC-001_jobhunterkit.md`, `TC-CB-S01` to `TC-CB-S06`.
- **Verdict**: 100% Production Ready SSOT.
