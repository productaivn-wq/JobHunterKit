"""
weworkremotely.py — We Work Remotely public RSS feeds scraper for JobHunterKit.

Extracts remote tech, product, and leadership jobs directly from WeWorkRemotely's official RSS feeds.
"""

import html
import json
import logging
import os
import re
import urllib.request
import xml.etree.ElementTree as ET

logger = logging.getLogger("JobHunter.Scrapers.WeWorkRemotely")


class WeWorkRemotelyScraper:
    """Scraper implementation for extracting jobs from We Work Remotely RSS feeds."""

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
        self.source_name = "weworkremotely"

    def _clean_html(self, raw_html: str) -> str:
        """Strips HTML tags and unescapes text for clean JD representation."""
        clean = re.sub(r"<[^>]+>", " ", raw_html)
        clean = html.unescape(clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    def run(self) -> str:
        """Fetches jobs from WWR RSS feeds."""
        print(f"[Scraper: WeWorkRemotely] Fetching RSS feeds for '{self.keyword}'...")
        jobs = []

        feed_urls = [
            "https://weworkremotely.com/categories/remote-programming-jobs.rss",
            "https://weworkremotely.com/categories/remote-product-jobs.rss",
            "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
            "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
            "https://weworkremotely.com/remote-jobs.rss",
        ]

        seen_urls = set()

        for feed_url in feed_urls:
            if len(jobs) >= self.limit:
                break
            try:
                req = urllib.request.Request(
                    feed_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "application/rss+xml, application/xml, text/xml",
                    },
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status == 200:
                        content = resp.read()
                        root = ET.fromstring(content)
                        items = root.findall("./channel/item")
                        print(f"[WeWorkRemotely] Found {len(items)} items in {feed_url}")

                        for item in items:
                            if len(jobs) >= self.limit:
                                break

                            link_elem = item.find("link")
                            job_url = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
                            if not job_url or job_url in seen_urls:
                                continue
                            seen_urls.add(job_url)

                            raw_title = item.find("title").text if item.find("title") is not None else "Unknown Title"
                            company = "Unknown Company"
                            title = raw_title

                            # WWR format is often: "Company Name: Job Title"
                            if ":" in raw_title:
                                parts = raw_title.split(":", 1)
                                company = parts[0].strip()
                                title = parts[1].strip()

                            desc_elem = item.find("description")
                            raw_desc = desc_elem.text if desc_elem is not None and desc_elem.text else ""
                            jd_text = self._clean_html(raw_desc)

                            pub_date_elem = item.find("pubDate")
                            pub_date = pub_date_elem.text.strip() if pub_date_elem is not None and pub_date_elem.text else ""

                            job_id = f"wwr_{hash(job_url) & 0xFFFFFF}"
                            jobs.append(
                                {
                                    "id": job_id,
                                    "title": title,
                                    "company": company,
                                    "location": "Worldwide / Remote",
                                    "url": job_url,
                                    "source": "weworkremotely",
                                    "jd_text": jd_text,
                                    "pub_date": pub_date,
                                }
                            )
            except Exception as e:
                logger.warning(f"[WeWorkRemotely] Error parsing {feed_url}: {e}")

        # Save output
        jobs_file = self.dirs.get("jobs_file", os.path.join(self.dirs.get("run_dir", "."), "weworkremotely_jobs.json"))
        out_dir = os.path.dirname(os.path.abspath(jobs_file))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(jobs_file, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)

        print(f"[WeWorkRemotely] Successfully saved {len(jobs)} jobs to {jobs_file}")
        return jobs_file


def scrape_jobs(
    keyword: str,
    location: str,
    dirs: dict[str, str],
    limit: int = 100,
    state_file: str | None = None,
    date_posted: str = "week",
) -> str:
    """Entry point function to execute We Work Remotely scraper workflow."""
    scraper = WeWorkRemotelyScraper(keyword, location, dirs, limit, state_file, date_posted)
    return scraper.run()
