"""
vietnamworks.py — VietnamWorks job scraper implementation for JobHunterKit.

Extracts job listings and detailed descriptions from VietnamWorks based on keyword and location.
"""

import time
import urllib.parse
from typing import Any

from scrapers.base_scraper import BaseScraper


class VietnamWorksScraper(BaseScraper):
    """Scraper implementation for extracting jobs from VietnamWorks."""

    def __init__(
        self,
        keyword: str,
        location: str,
        dirs: dict[str, str],
        limit: int = 50,
        state_file: str | None = None,
        date_posted: str = "week",
    ) -> None:
        """Initializes VietnamWorks scraper with search parameters."""
        super().__init__(
            "VietnamWorks", keyword, location, dirs, limit, state_file, date_posted
        )

    def scrape(self, page: Any, context: Any) -> list[dict[str, Any]]:
        """Scrapes search results and navigates to individual job postings for full JD text."""
        encoded_keyword = urllib.parse.quote(self.keyword)
        search_url = f"https://www.vietnamworks.com/tim-viec-lam?q={encoded_keyword}"

        jobs: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(4)  # allow react to load

        # Simple pagination: scroll down
        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

        # Locate job card links
        card_links = page.locator("a[href*='-jv']").all()
        print(f"Found {len(card_links)} job link candidates on VietnamWorks.")

        for link_el in card_links:
            if len(jobs) >= self.limit:
                break

            url = link_el.get_attribute("href")
            if not url:
                continue

            if not url.startswith("http"):
                url = "https://www.vietnamworks.com" + url

            # Strip tracking query params
            clean_url = url.split("?")[0]
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)

            try:
                title = link_el.inner_text().strip()
                if not title or len(title) < 4:
                    title_el = link_el.locator("h2, h3, [class*='title']")
                    if title_el.count() > 0:
                        title = title_el.first.inner_text().strip()
                    else:
                        continue

                company = "VietnamWorks Employer"
                try:
                    parent_card = link_el.locator("xpath=./ancestor::div[contains(@class, 'job') or contains(@class, 'card') or contains(@class, 'item')][1]")
                    if parent_card.count() > 0:
                        comp_el = parent_card.locator("[class*='company'], [class*='employer'], a[href*='/company/']").first
                        if comp_el.count() > 0:
                            company = comp_el.inner_text().strip()
                except Exception:
                    pass
            except Exception as parse_err:
                print(f"  [WARNING] Error parsing item metadata: {parse_err}")
                continue

            # Fast pre-filter on title to avoid unrelated sponsored jobs
            try:
                from fast_filter import should_exclude
                excluded, reason = should_exclude(title, "", self.location)
                if excluded:
                    print(f"  [VietnamWorks] Skipping unrelated job '{title}': {reason}")
                    continue
            except Exception:
                pass

            jobs.append(
                {
                    "id": f"job_vw_{len(jobs)}",
                    "title": title,
                    "company": company,
                    "url": url,
                    "source": "vietnamworks",
                    "jd_text": "",  # to be fetched next
                },
            )

        # Fetch JD text
        for j in jobs:
            print(
                f"  [VietnamWorks] Fetching JD for: {j['title']} at {j['company']}",
            )
            try:
                page.goto(j["url"], wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)

                # Usually JD is inside .job-description or .description
                jd_locator = page.locator(
                    ".job-description, .description, .box-job-info",
                )
                if jd_locator.count() > 0:
                    j["jd_text"] = jd_locator.first.inner_text().strip()
                else:
                    j["jd_text"] = page.evaluate("document.body.innerText").strip()
            except Exception as e:
                print(f"  [WARNING] Failed to fetch JD for {j['url']}: {e}")
                j["jd_text"] = "Description unavailable."

        return jobs


def scrape_jobs(
    keyword: str,
    location: str,
    dirs: dict[str, str],
    limit: int = 50,
    state_file: str | None = None,
    date_posted: str = "week",
) -> list[dict[str, Any]]:
    """Entry point function to execute the VietnamWorks scraper workflow."""
    scraper = VietnamWorksScraper(
        keyword, location, dirs, limit, state_file, date_posted
    )
    return scraper.run()
