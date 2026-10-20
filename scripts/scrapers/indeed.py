"""
indeed.py — Indeed job scraper implementation for JobHunterKit.

Extracts job listings and detailed descriptions from Indeed based on query keywords and locations.
"""

import urllib.parse
from typing import Any

from scrapers.base_scraper import BaseScraper


class IndeedScraper(BaseScraper):
    """Scraper implementation for extracting jobs from Indeed platform."""

    def __init__(
        self,
        keyword: str,
        location: str,
        dirs: dict[str, str],
        limit: int = 50,
        state_file: str | None = None,
        date_posted: str = "week",
    ) -> None:
        """Initializes Indeed scraper with search parameters."""
        super().__init__(
            "Indeed", keyword, location, dirs, limit, state_file, date_posted
        )

    def scrape(self, page: Any, context: Any) -> list[dict[str, Any]]:
        """Scrapes search results and extracts descriptions from Indeed cards."""
        jobs = []
        start = 0
        while len(jobs) < self.limit:
            url = f"https://vn.indeed.com/jobs?q={urllib.parse.quote(self.keyword)}&l={urllib.parse.quote(self.location)}&start={start}"
            page.goto(url)
            page.wait_for_timeout(3000)

            # Check for Cloudflare / captcha
            if (
                "cloudflare" in page.title().lower()
                or "hcaptcha" in page.content().lower()
                or "verify you are human" in page.content().lower()
            ):
                print("Captcha/Cloudflare detected, stopping Indeed scraper.")
                break

            job_cards = page.locator("div.job_seen_beacon").all()
            if not job_cards:
                print("No more job cards found or blocked.")
                break

            for card in job_cards:
                if len(jobs) >= self.limit:
                    break
                try:
                    title_elem = card.locator(
                        "h2.jobTitle span, h3.jobTitle span, a.jcs-JobTitle span"
                    ).first
                    title = (
                        title_elem.inner_text().strip()
                        if title_elem.count() > 0
                        else "Unknown Title"
                    )
                    if title == "Unknown Title":
                        title_elem = card.locator(
                            "h2.jobTitle, h3.jobTitle, a.jcs-JobTitle"
                        ).first
                        title = (
                            title_elem.inner_text().strip()
                            if title_elem.count() > 0
                            else "Unknown Title"
                        )

                    company_elem = card.locator('[data-testid="company-name"]').first
                    company = (
                        company_elem.inner_text().strip()
                        if company_elem.count() > 0
                        else "Unknown Company"
                    )

                    link_elem = card.locator(
                        "h2.jobTitle a, h3.jobTitle a, a.jcs-JobTitle"
                    ).first
                    href = (
                        link_elem.get_attribute("href") if link_elem.count() > 0 else ""
                    )
                    if href and not href.startswith("http"):
                        url_job = "https://vn.indeed.com" + href
                    else:
                        url_job = href

                    # Click to load JD in the side panel
                    try:
                        if not card.is_visible():
                            print("Skipping invisible card")
                            continue
                        card.scroll_into_view_if_needed(timeout=2000)
                        card.click(timeout=2000)
                        page.wait_for_timeout(2000)
                    except Exception as e:
                        print(f"Failed to click card: {e}")

                    jd_locator = page.locator(
                        "div#jobsearch-ViewjobPaneWrapper div#jobDescriptionText",
                    )
                    if jd_locator.count() > 0:
                        jd_text = jd_locator.inner_text().strip()
                    else:
                        jd_text = ""

                    jobs.append(
                        {
                            "id": f"job_indeed_{len(jobs) + 1}",
                            "title": title,
                            "company": company,
                            "jd_text": jd_text,
                            "url": url_job,
                            "source": "indeed",
                        },
                    )
                except Exception as e:
                    print(f"Error extracting an indeed job: {e}")

            start += 10
        return jobs


def scrape_jobs(
    keyword: str,
    location: str,
    dirs: dict[str, str],
    limit: int = 50,
    state_file: str | None = None,
    date_posted: str = "week",
) -> list[dict[str, Any]]:
    """Entry point function to execute the Indeed scraper workflow."""
    scraper = IndeedScraper(keyword, location, dirs, limit, state_file, date_posted)
    return scraper.run()
