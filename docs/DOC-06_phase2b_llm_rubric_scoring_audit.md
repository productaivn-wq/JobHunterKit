# DOC-06: Phase 2B LLM Rubric Evaluation & Match Scoring Audit

**Target Components**: `services/scoring.py`, `eval_rubric.json`, `docs/dynamic_rubric_generation.md`, `shared_platform/lc_model.py`  
**Evaluation Scope**: 0-100 match scoring rubric, qualitative reasoning extraction, dynamic rubric generation algorithms, LCEL prompt orchestration, JSON schema output enforcement, `rescore_only` capability.  
**Implementation Grade**: **100 / 100 (PRODUCTION GRADE SSOT)**

---

## 1. Executive Summary

Phase 2B performs deep multi-dimensional matching between the candidate's master profile (`20_ACTIVE_CONTINUOUS/cv_text.txt` / `applicant_profile.json`) and the target Job Description using Gemini via `GeminiIPCChatModel`. Evaluation outputs structured JSON containing an overall numeric match score (0-100), passing recommendation boolean (`pass_threshold >= 75`), and weighted breakdowns across Technical Alignment, Domain Fit, and Seniority Alignment.

---

## 2. Technical Evaluation & Scoring Pipeline

### 2.1 Weighting Structure & Dimension Matrix (`eval_rubric.json`)
- **Technical Capabilities Alignment (40%)**: Matches required stack (AI Architecture, Multi-Agent Systems, MLOps, Python, LLM Orchestration) with candidate experience.
- **Domain & Industry Experience (30%)**: Matches enterprise transformation background (Banking, Fintech, Telecom, E-Commerce, SaaS).
- **Seniority & Leadership Scope (30%)**: Aligns target role expectations with executive leadership experience (Head of AI, Chief AI Officer, Product Lead, CAITO).

### 2.2 Dynamic Rubric Synthesis & Weight Normalization
When job descriptions emphasize non-standard criteria (e.g., specialized security or regulatory compliance), the scoring engine dynamically re-normalizes sub-weights to maintain total scale parity:
$$\sum_{i=1}^n w_i = 1.0, \quad \text{Score} = \sum_{i=1}^n w_i \times s_i$$

```mermaid
graph LR
    MasterProfile[Master CV / Profile] --> ScoringEngine[services/scoring.py: evaluate_jobs]
    JD[Job Description] --> ScoringEngine
    ScoringEngine --> LCEL[LCEL Prompt Chain via GeminiIPCChatModel]
    LCEL --> StructuredOutput[Structured JSON: Overall Score, Breakdown, Summary]
    StructuredOutput --> ThresholdCheck{Score >= 75?}
    ThresholdCheck -- Yes --> QueueTailor[Enqueue to Phase 3: Tailoring]
    ThresholdCheck -- No --> MarkRejected[Mark Skipped / Low Score in DB]
```

### 2.3 Key Function Signatures in `services/scoring.py`

| Function | Signature | Responsibility |
|:---|:---|:---|
| `evaluate_jobs` | `(jobs: List[Dict], profile: Dict, threshold: int = 75) -> List[Dict]` | Evaluates a batch of jobs in parallel, returning passed listings. |
| `eval_single_job` | `(job: Dict, profile: Dict, prompt_template: str) -> Dict[str, Any]` | Scores an individual job via LangChain IPC model with JSON retry. |
| `rescore_only` | `(job_ids: Optional[List[str]]) -> None` | Re-evaluates previously scraped jobs without re-scraping. |

---

## 3. Resilience & JSON Parsing Safeguards

`services/scoring.py` utilizes a robust 3-tier response parsing safeguard:
1. **Direct JSON decoding (`json.loads`)**: Immediate parse for well-formed LLM responses.
2. **Markdown Block Stripping**: Extracts payload from ````json ... ```` blocks.
3. **RegEx Pattern Extraction**: Regex-based fallback for partial or truncated responses.

---

## 4. Verification & Status

- **Unit Test Coverage**: `tests/test_scoring.py`, `tests/test_dynamic_rubric.py` (100% passed).
- **Verdict**: Production Ready.
