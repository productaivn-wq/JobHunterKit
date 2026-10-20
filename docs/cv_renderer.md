# CV Renderer Subsystem Documentation

## 1. Purpose & Current State
The CV Renderer subsystem is responsible for taking a base CV and a Job Description (JD), using an LLM to tailor the content into an HTML template, and finally rendering that HTML into a polished PDF document.

**⚠️ ARCHIVED PROTOTYPE / CANONICAL PATH:**  
The original Node.js prototype directory at `.\10_ACTIVE_TIMEBOUND\Project\app\tailored_cv_renderer\` was an abandoned skeleton containing only a `package.json` and `node_modules`, with no application source code. It has been moved to `.\40_ARCHIVE\tailored_cv_renderer_abandoned_prototype\`.

The canonical production CV rendering path is **100% Python-based (Python + Playwright)** and resides within the `JobHunterKit` scripts.

## 2. Architecture & Integration Point
The Python codebase does not invoke a Node.js package. Instead, the workflow operates via Python CLI subprocesses:

1. **Service Layer**: `services/tailoring.py` initiates the tailoring phase by running `scripts/tailor_jd.py` using a `ThreadPoolExecutor` for parallel processing.
2. **HTML Generation**: `scripts/tailor_jd.py` uses `ipc_utils.call_antigravity` to call an LLM. It injects the JD and base CV into a prompt to populate an HTML template.
3. **PII Injection**: Sensitive information (name, email, phone, LinkedIn) is explicitly injected into the HTML from `config/applicant_profile.json`.
4. **PDF Rendering**: `scripts/tailor_jd.py` then invokes `scripts/render_pdf.py` as a subprocess to convert the HTML file into a PDF.

## 3. Technology Stack (Actual)
Since the Node.js package is dead code, the true technology stack is:
* **Core Language:** Python 3
* **LLM Integration:** `ipc_utils` (Antigravity SDK) for structured prompt completion.
* **PDF Generation Library:** `playwright` (Python Sync API) launching headless Chromium.
* **Templates:** Vanilla HTML/CSS.

## 4. Input / Output Contract
The rendering subsystem operates through CLI arguments. 

### `tailor_jd.py` (The Orchestrator)
* **Inputs:**
  * `--job-id`: Target job ID (e.g., `job_1`)
  * `--jd-file`: Path to the JD text file.
  * `--cv-file`: Path to the candidate's Base CV.
  * `--output-pdf`: Target absolute path for the output PDF.
* **Outputs:** 
  * Writes the tailored `.html` file.
  * Generates the final `.pdf` file.

### `render_pdf.py` (The Renderer)
* **Inputs:** 
  * `input_html`: Path to the generated HTML.
  * `output_pdf`: Target PDF path.
  * `--type`: Document type (`cv`, `resume`, `cl`). This dynamically adjusts the print margins (e.g., `resume` uses 0.3in top/bottom, while `cl` uses 1.0in).
* **Outputs:** Writes the rendered PDF to disk.

## 5. Templates
HTML templates are stored in `.\templates\`:
* `cv_template.html`
* `resume_template.html`
* `cl_template.html` (Cover Letter)

**Structure:** Templates use placeholder syntax.
* **LLM Placeholders:** Examples include `{{TARGET_JOB_TITLE_OR_SIMILAR}}`, `{{2_SENTENCE_PUNCHY_SUMMARY}}`, etc., which the LLM replaces.
* **PII Placeholders:** `{FULL_NAME}`, `{EMAIL}`, `{PHONE}`, and `{LINKEDIN_URL}` are populated via hardcoded string replacement in Python using `applicant_profile.json`.

## 6. Build & Run
To run or build this subsystem, the Node.js folder can be completely ignored.

**Dependencies:**
The Python environment must have Playwright installed and the Chromium browser binaries downloaded:
```bash
pip install playwright
playwright install chromium
```

## 7. Known Limitations & Discovered Gaps
1. **Archived Node.js Prototype:** The abandoned `tailored_cv_renderer` directory has been archived to `.\40_ARCHIVE\tailored_cv_renderer_abandoned_prototype\` to clean up the active project tree and prevent developer confusion.
2. **Performance Bottleneck:** `services/tailoring.py` uses parallel threads (up to 5 workers) to trigger `tailor_jd.py`, which in turn spawns `render_pdf.py`. This means the system concurrently launches up to 5 completely separate Playwright Chromium browser instances. This is heavily taxing on CPU and RAM. A persistent browser instance or a queued rendering service would be vastly more efficient.
3. **Strict PII Fallback:** `tailor_jd.py` checks if the applicant's name is "Jane Doe" or if "jane.doe" is in the email. If detected, it assumes PII is missing/dummy data, aborts the tailoring process entirely, and exits with a hard failure. This is a secure fallback, but undocumented, meaning users failing to configure their `applicant_profile.json` will experience silent tailoring failures.
