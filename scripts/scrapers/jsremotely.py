"""
jsremotely.py — JS Remotely / Javascript.jobs scraper implementation for JobHunterKit.

Extracts JavaScript, TypeScript, React, Node, and Fullstack AI remote jobs.
"""

import json
import logging
import os
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup

logger = logging.getLogger("JobHunter.Scrapers.JSRemotely")


class JSRemotelyScraper:
    """Scraper implementation for extracting jobs from JS Remotely platform."""

    def __init__(
        self,
        keyword: str,
        location: str,
        dirs: dict[str, str],
        limit: int = 50,
        state_file: str | None = None,
        date_posted: str = "week",
    ) -> None:
        self.keyword = keyword
        self.location = location
        self.dirs = dirs
        self.limit = limit
        self.state_file = state_file
        self.date_posted = date_posted
        self.source_name = "jsremotely"

    def run(self) -> str:
        print(f"[Scraper: JS Remotely] Querying jsremotely.com for '{self.keyword}'...")
        jobs = []
        seen_urls = set()

        url = "https://jsremotely.com"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                html_doc = resp.read().decode("utf-8")
                soup = BeautifulSoup(html_doc, "html.parser")

                for a_tag in soup.find_all("a", href=True):
                    if len(jobs) >= self.limit:
                        break
                    href = a_tag["href"]
                    if "/job/" not in href:
                        continue

                    if not href.startswith("http"):
                        job_url = f"https://jsremotely.com{href}"
                    else:
                        job_url = href

                    if job_url in seen_urls:
                        continue
                    seen_urls.add(job_url)

                    lines = [line.strip() for line in a_tag.text.split("\n") if line.strip()]
                    title = lines[0] if lines else "Unknown Title"
                    company = "Unknown Company"
                    if len(lines) > 2:
                        for line_item in reversed(lines):
                            if line_item not in ["Remote", "Full Time", "Part Time", "Contract", "1W", "2W", "3W", "1D", "2D", "3D", "4D", "5D", "6D"]:
                                company = line_item
                                break

                    kw_lower = self.keyword.lower()
                    if kw_lower and kw_lower not in ["all", "any", "remote"]:
                        if kw_lower not in title.lower() and kw_lower not in company.lower() and kw_lower not in " ".join(lines).lower():
                            continue

                    job_id = f"jsremotely_{hash(job_url) & 0xFFFFFF}"
                    jobs.append(
                        {
                            "id": job_id,
                            "title": title,
                            "company": company,
                            "location": "Worldwide / Remote",
                            "url": job_url,
                            "source": "jsremotely",
                            "jd_text": f"Title: {title}\nCompany: {company}\nDetails: {' | '.join(lines)}\nJob URL: {job_url}",
                        }
                    )
        except Exception as e:
            logger.warning(f"[JSRemotely] Scraping failed: {e}")

        # Save output
        jobs_file = self.dirs.get("jobs_file", os.path.join(self.dirs.get("run_dir", "."), "jsremotely_jobs.json"))
        out_dir = os.path.dirname(os.path.abspath(jobs_file))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(jobs_file, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)

        print(f"[JS Remotely] Successfully saved {len(jobs)} jobs to {jobs_file}")
        return jobs_file


def scrape_jobs(
    keyword: str,
    location: str,
    dirs: dict[str, str],
    limit: int = 50,
    state_file: str | None = None,
    date_posted: str = "week",
) -> str:
    scraper = JSRemotelyScraper(keyword, location, dirs, limit, state_file, date_posted)
    return scraper.run()
