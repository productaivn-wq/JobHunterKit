"""
remotive.py — Remotive public REST API job scraper for JobHunterKit.

Extracts remote tech, product, and AI jobs directly from Remotive's official public API.
"""

import json
import logging
import os
import re
import urllib.parse
import urllib.request

logger = logging.getLogger("JobHunter.Scrapers.Remotive")


class RemotiveScraper:
    """Scraper implementation for extracting jobs from Remotive API."""

    def __init__(
        self,
        keyword: str,
        location: str,
        dirs: dict[str, str],
        limit: int = 100,
        state_file: str | None = None,
        date_posted: str = "week",
    ) -> None:
        self.keyword = keyword
        self.location = location
        self.dirs = dirs
        self.limit = limit
        self.state_file = state_file
        self.date_posted = date_posted
        self.source_name = "remotive"

    def _clean_html(self, raw_html: str) -> str:
        """Strips HTML tags and unescapes text for clean JD representation."""
        clean = re.sub(r"<[^>]+>", " ", raw_html)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    def run(self) -> str:
        """Fetches jobs from Remotive API matching keyword or categories."""
        print(f"[Scraper: Remotive] Querying Remotive API for '{self.keyword}'...")
        jobs = []

        queries = [
            f"https://remotive.com/api/remote-jobs?search={urllib.parse.quote(self.keyword)}",
            "https://remotive.com/api/remote-jobs?category=product",
            "https://remotive.com/api/remote-jobs?category=software-dev",
            "https://remotive.com/api/remote-jobs?category=data",
        ]

        seen_urls = set()

        for url in queries:
            if len(jobs) >= self.limit:
                break
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status == 200:
                        payload = json.loads(resp.read().decode("utf-8"))
                        raw_jobs = payload.get("jobs", [])
                        print(f"[Remotive] Fetched {len(raw_jobs)} candidate listings from {url}")

                        for item in raw_jobs:
                            if len(jobs) >= self.limit:
                                break
                            job_url = item.get("url", "")
                            if not job_url or job_url in seen_urls:
                                continue
                            seen_urls.add(job_url)

                            title = item.get("title", "Unknown Title")
                            company = item.get("company_name", "Unknown Company")
                            raw_desc = item.get("description", "")
                            jd_text = self._clean_html(raw_desc)
                            salary = item.get("salary", "")
                            candidate_location = item.get("candidate_required_location", "Worldwide")
                            tags = item.get("tags", [])

                            # Append salary info to JD if available
                            if salary:
                                jd_text = f"Salary: {salary}\nLocation: {candidate_location}\nTags: {', '.join(tags)}\n\n{jd_text}"

                            job_id = f"remotive_{item.get('id', hash(job_url) & 0xFFFFFF)}"
                            jobs.append(
                                {
                                    "id": job_id,
                                    "title": title,
                                    "company": company,
                                    "location": candidate_location,
                                    "url": job_url,
                                    "source": "remotive",
                                    "jd_text": jd_text,
                                    "salary": salary,
                                }
                            )
            except Exception as e:
                logger.warning(f"[Remotive] Failed fetching from {url}: {e}")

        # Save output
        jobs_file = self.dirs.get("jobs_file", os.path.join(self.dirs.get("run_dir", "."), "remotive_jobs.json"))
        out_dir = os.path.dirname(os.path.abspath(jobs_file))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(jobs_file, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)

        print(f"[Remotive] Successfully saved {len(jobs)} jobs to {jobs_file}")
        return jobs_file


def scrape_jobs(
    keyword: str,
    location: str,
    dirs: dict[str, str],
    limit: int = 100,
    state_file: str | None = None,
    date_posted: str = "week",
) -> str:
    """Entry point function to execute Remotive API scraper workflow."""
    scraper = RemotiveScraper(keyword, location, dirs, limit, state_file, date_posted)
    return scraper.run()
