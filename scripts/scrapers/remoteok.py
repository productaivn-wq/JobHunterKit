"""
remoteok.py — RemoteOK public JSON API scraper for JobHunterKit.

Extracts remote tech, product, and AI jobs with salary metadata directly from RemoteOK's public API.
"""

import html
import json
import logging
import os
import re
import urllib.parse
import urllib.request

logger = logging.getLogger("JobHunter.Scrapers.RemoteOK")


class RemoteOKScraper:
    """Scraper implementation for extracting jobs from RemoteOK API."""

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
        self.source_name = "remoteok"

    def _clean_html(self, raw_html: str) -> str:
        """Strips HTML tags and unescapes text for clean JD representation."""
        clean = re.sub(r"<[^>]+>", " ", raw_html)
        clean = html.unescape(clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    def run(self) -> str:
        """Fetches jobs from RemoteOK API."""
        print(f"[Scraper: RemoteOK] Querying RemoteOK API for '{self.keyword}'...")
        jobs = []

        url = "https://remoteok.com/api"
        seen_urls = set()

        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status == 200:
                    payload = json.loads(resp.read().decode("utf-8"))
                    # First element in RemoteOK JSON response is legal / metadata
                    items = [item for item in payload if isinstance(item, dict) and "position" in item]
                    print(f"[RemoteOK] Fetched {len(items)} total job postings")

                    kw_lower = self.keyword.lower()
                    for item in items:
                        if len(jobs) >= self.limit:
                            break

                        position = item.get("position", "Unknown Title")
                        company = item.get("company", "Unknown Company")
                        raw_desc = item.get("description", "")
                        jd_text = self._clean_html(raw_desc)
                        tags = item.get("tags", [])
                        job_url = item.get("url", "")
                        if not job_url and item.get("id"):
                            job_url = f"https://remoteok.com/remote-jobs/{item.get('id')}"

                        if not job_url or job_url in seen_urls:
                            continue

                        # If keyword provided, filter by position, tags, or description
                        if kw_lower and kw_lower not in ["all", "any", "remote"]:
                            matches_title = kw_lower in position.lower()
                            matches_tags = any(kw_lower in str(t).lower() for t in tags)
                            matches_desc = kw_lower in jd_text.lower()
                            if not (matches_title or matches_tags or matches_desc):
                                continue

                        seen_urls.add(job_url)

                        salary_min = item.get("salary_min", "")
                        salary_max = item.get("salary_max", "")
                        salary = ""
                        if salary_min or salary_max:
                            salary = f"${salary_min:,} - ${salary_max:,} USD/yr" if isinstance(salary_min, int) and isinstance(salary_max, int) else f"{salary_min} - {salary_max}"

                        location_req = item.get("location", "Worldwide / Remote")
                        if salary:
                            jd_text = f"Salary Band: {salary}\nLocation: {location_req}\nTags: {', '.join(tags)}\n\n{jd_text}"

                        job_id = f"remoteok_{item.get('id', hash(job_url) & 0xFFFFFF)}"
                        jobs.append(
                            {
                                "id": job_id,
                                "title": position,
                                "company": company,
                                "location": location_req,
                                "url": job_url,
                                "source": "remoteok",
                                "jd_text": jd_text,
                                "salary": salary,
                                "tags": tags,
                            }
                        )
        except Exception as e:
            logger.warning(f"[RemoteOK] Failed querying API: {e}")

        # Save output
        jobs_file = self.dirs.get("jobs_file", os.path.join(self.dirs.get("run_dir", "."), "remoteok_jobs.json"))
        out_dir = os.path.dirname(os.path.abspath(jobs_file))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(jobs_file, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)

        print(f"[RemoteOK] Successfully saved {len(jobs)} jobs to {jobs_file}")
        return jobs_file


def scrape_jobs(
    keyword: str,
    location: str,
    dirs: dict[str, str],
    limit: int = 100,
    state_file: str | None = None,
    date_posted: str = "week",
) -> str:
    """Entry point function to execute RemoteOK API scraper workflow."""
    scraper = RemoteOKScraper(keyword, location, dirs, limit, state_file, date_posted)
    return scraper.run()
