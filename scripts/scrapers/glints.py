"""
glints.py — Glints job scraper implementation for JobHunterKit.

Extracts job listings and detailed descriptions from Glints based on keyword and location.
"""

import time
from typing import Any

from scrapers.base_scraper import BaseScraper


def extract_company_from_title(title: str | None) -> str:
    """Extracts company name from standardized Glints page titles."""
    if not title:
        return "Unknown Company"
    title_clean = title.strip()
    for separator in [" at ", " tại ", " @ "]:
        if separator in title_clean:
            parts = title_clean.split(separator)
            company_part = parts[-1].split("|")[0].strip()
            if company_part:
                return company_part
    return "Unknown Company"


class GlintsScraper(BaseScraper):
    """Scraper implementation for extracting jobs from Glints."""

    def __init__(
        self,
        keyword: str,
        location: str,
        dirs: dict[str, str],
        limit: int = 50,
        state_file: str | None = None,
        date_posted: str = "week",
    ) -> None:
        """Initializes Glints scraper with search parameters."""
        super().__init__(
            "Glints", keyword, location, dirs, limit, state_file, date_posted
        )

    def scrape(self, page: Any, context: Any) -> list[dict[str, Any]]:
        """Scrapes Glints search results and details page."""
        search_url = "https://glints.com/vn/opportunities/jobs"
        jobs: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        # Navigate to the Glints search homepage
        page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(4)

        # Locate search input and submit keyword
        inputs = page.locator("input").all()
        filled = False
        for inp in inputs:
            try:
                placeholder = (inp.get_attribute("placeholder") or "").lower()
                id_val = (inp.get_attribute("id") or "").lower()
                name_val = (inp.get_attribute("name") or "").lower()
                if (
                    any(
                        x in placeholder
                        for x in ["job title", "keywords", "tìm kiếm", "vị trí"]
                    )
                    or name_val == "keyword"
                    or "search" in id_val
                ):
                    inp.fill(self.keyword)
                    inp.press("Enter")
                    filled = True
                    break
            except Exception as inp_err:
                print(f"  [DEBUG] Input inspect skipped: {inp_err}")

        if not filled:
            # Fallback to general selector
            try:
                page.locator(
                    'input[placeholder*="Job title"], input[placeholder*="Tìm kiếm"]'
                ).first.fill(self.keyword)
                page.locator(
                    'input[placeholder*="Job title"], input[placeholder*="Tìm kiếm"]'
                ).first.press("Enter")
            except Exception as e:
                print(f"  [WARNING] Could not fill search query: {e}")

        time.sleep(5)  # Wait for results page to load

        # Scroll multiple times to fetch job listings
        for _ in range(4):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

        # Extract job links
        links = page.locator("a").all()
        for link in links:
            if len(seen_urls) >= self.limit:
                break
            try:
                href = link.get_attribute("href")
                if href and "/opportunities/jobs/" in href:
                    # Normalize url to absolute path
                    if href.startswith("/"):
                        url = "https://glints.com" + href
                    else:
                        url = href

                    clean_url = url.split("?")[0].strip()
                    if clean_url not in seen_urls:
                        title_text = link.inner_text().strip().split("\n")[0]
                        seen_urls.add(clean_url)
                        jobs.append(
                            {
                                "id": f"job_glints_{len(jobs)}",
                                "title": title_text,
                                "company": "Unknown Company",  # Will resolve on detail page
                                "url": clean_url,
                                "source": "glints",
                                "jd_text": "",
                            }
                        )
            except Exception as link_err:
                print(f"  [DEBUG] Link parsing skipped: {link_err}")

        print(f"  Found {len(jobs)} Glints job candidates. Fetching descriptions...")

        # Visit each detail page to fetch JD and resolve company names
        for j in jobs:
            if not j["url"]:
                continue
            try:
                print(f"  [Glints] Fetching details for: {j['title']}...")
                page.goto(j["url"], wait_until="domcontentloaded", timeout=30000)
                time.sleep(2.5)

                # Extract company name from page title or header
                page_title = page.title()
                j["company"] = extract_company_from_title(page_title)

                # If still unknown, check specific DOM selectors
                if j["company"] == "Unknown Company":
                    for sel in [
                        '[class*="CompanyName"]',
                        '[class*="CompanyNameContainer"]',
                        'a[href*="/companies/"]',
                    ]:
                        try:
                            loc = page.locator(sel)
                            if loc.count() > 0:
                                j["company"] = loc.first.inner_text().strip()
                                break
                        except Exception as sel_err:
                            print(f"  [DEBUG] Selector {sel} failed: {sel_err}")

                # Extract JD text
                jd_selector = 'main, div[class*="JobDescription"], div[class*="DescriptionContainer"], [id="job-description"]'
                try:
                    jd_el = page.locator(jd_selector).first
                    if jd_el.count() > 0:
                        j["jd_text"] = jd_el.inner_text().strip()
                except Exception as jd_err:
                    print(f"  [DEBUG] JD locator failed: {jd_err}")

                if not j["jd_text"] or len(j["jd_text"]) < 50:
                    j["jd_text"] = page.evaluate("document.body.innerText").strip()

            except Exception as e:
                print(f"  [WARNING] Failed to fetch details for {j['url']}: {e}")
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
    """Entry point function to execute the Glints scraper workflow."""
    scraper = GlintsScraper(keyword, location, dirs, limit, state_file, date_posted)
    return scraper.run()
