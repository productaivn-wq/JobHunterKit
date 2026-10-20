import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Ensure GmailSync can be resolved
GMAIL_SYNC_DIR = str(Path.home() / "GmailSync")
if GMAIL_SYNC_DIR not in sys.path:
    sys.path.append(GMAIL_SYNC_DIR)

try:
    from src.gmail_client import GmailClient
except ImportError:
    GmailClient = None


class JobrightGmailScraper:
    def __init__(self, user_email: str = "applicant@example.com"):
        self.user_email = user_email
        if GmailClient is None:
            raise ImportError("GmailClient not available from GmailSync")
        old_cwd = os.getcwd()
        try:
            os.chdir(GMAIL_SYNC_DIR)
            self.client = GmailClient(email_address=user_email)
        finally:
            os.chdir(old_cwd)

    def scrape_recent_digest(
        self, keyword: str = "", location: str = "", max_emails: int = 5
    ) -> list[dict[str, Any]]:
        """Scrapes job recommendations from recent Jobright email digests in Gmail."""
        print(
            f"[JobrightGmailScraper] Searching Gmail ({self.user_email}) for Jobright digests..."
        )
        try:
            query = "from:eric@jobright.com"
            results = (
                self.client.service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_emails)
                .execute()
            )
            messages = results.get("messages", [])
        except Exception as e:
            print(f"[JobrightGmailScraper] Failed to fetch messages: {e}")
            return []

        all_jobs = []
        kw_lower = keyword.lower() if keyword else ""

        for msg in messages:
            try:
                msg_data = (
                    self.client.service.users()
                    .messages()
                    .get(userId="me", id=msg["id"], format="full")
                    .execute()
                )

                def get_html_body(part):
                    if "parts" in part:
                        for p in part["parts"]:
                            res = get_html_body(p)
                            if res:
                                return res
                    elif part.get("mimeType") == "text/html":
                        data = part.get("body", {}).get("data", "")
                        if data:
                            return base64.urlsafe_b64decode(data).decode(
                                "utf-8", errors="ignore"
                            )
                    return ""

                html = get_html_body(msg_data.get("payload", {}))
                if not html:
                    continue

                soup = BeautifulSoup(html, "html.parser")

                # Extract links and titles
                links = soup.find_all("a")
                for a in links:
                    text = a.get_text(strip=True)
                    href = a.get("href", "")
                    if (
                        href
                        and "jobright.ai/jobs/info/" in href
                        and text
                        and text != "APPLY NOW"
                    ):
                        # Optional: filter by keyword/location if provided
                        if (
                            kw_lower
                            and kw_lower not in text.lower()
                            and kw_lower not in html.lower()
                        ):
                            continue
                        all_jobs.append(
                            {
                                "id": f"job_jrg_{len(all_jobs)}",
                                "source": "jobright_gmail",
                                "title": text,
                                "url": href,
                                "jobright_url": href,
                                "company": "Unknown Company",  # Will extract next
                                "scraped_from": "Gmail Email Digest",
                            }
                        )
            except Exception as e:
                print(
                    f"[JobrightGmailScraper] Failed processing message {msg['id']}: {e}"
                )

        # Follow-through to fetch JD detail and company
        print(
            f"[JobrightGmailScraper] Extracted {len(all_jobs)} links. Fetching JD details..."
        )
        try:
            with sync_playwright() as p:
                browser = None
                try:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    for j in all_jobs:
                        try:
                            page.goto(
                                j["url"], wait_until="domcontentloaded", timeout=30000
                            )
                            time.sleep(2)

                            # Try extracting company name from page title or elements
                            title_text = page.title()
                            if " at " in title_text:
                                j["company"] = (
                                    title_text.split(" at ")[-1].split("|")[0].strip()
                                )
                            else:
                                # Jobright might have .company-name class
                                comp_el = page.locator(
                                    ".company-name, [class*='Company']"
                                )
                                if comp_el.count() > 0:
                                    j["company"] = comp_el.first.inner_text().strip()

                            jd_loc = page.locator(
                                "main, .job-description, .jd-content, body"
                            )
                            if jd_loc.count() > 0:
                                j["jd_text"] = jd_loc.first.inner_text().strip()
                            else:
                                j["jd_text"] = "JD not found"

                        except Exception as e:
                            print(f"Failed to fetch JD for {j['url']}: {e}")
                            j["jd_text"] = "JD fetch failed"
                finally:
                    if browser:
                        try:
                            browser.close()
                        except Exception:
                            pass
        except Exception as e:
            print(f"[JobrightGmailScraper] Playwright error: {e}")

        print(
            f"[JobrightGmailScraper] Successfully extracted {len(all_jobs)} jobs from Jobright email digests!"
        )
        return all_jobs


def scrape_jobs(keyword, location, dirs, limit=30, state_file=None, date_posted="week"):
    """Standard flow_scrape adapter function."""
    jobs_file = dirs["jobs_file"]

    try:
        scraper = JobrightGmailScraper()
        jobs = scraper.scrape_recent_digest(
            keyword=keyword, location=location, max_emails=min(limit, 10)
        )
    except ImportError:
        print(
            "[JobrightGmailScraper] Skipping: GmailSync/GmailClient is not configured or unavailable."
        )
        jobs = []
    except Exception as e:
        print(f"[JobrightGmailScraper] Scraper execution notice: {e}")
        jobs = []

    os.makedirs(os.path.dirname(jobs_file), exist_ok=True)
    with open(jobs_file, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)

    return jobs_file


if __name__ == "__main__":
    try:
        scraper = JobrightGmailScraper()
        jobs = scraper.scrape_recent_digest()
        for j in jobs[:5]:
            print(j)
    except Exception as e:
        print(f"Error running standalone scraper: {e}")
