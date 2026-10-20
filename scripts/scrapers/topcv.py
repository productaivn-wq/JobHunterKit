"""
topcv.py — TopCV job scraper implementation for JobHunterKit.

Extracts job listings and Vietnamese job descriptions from TopCV based on keyword and location.
"""

import time
import urllib.parse
from typing import Any

from scrapers.base_scraper import BaseScraper


class TopCVScraper(BaseScraper):
    """Scraper implementation for extracting jobs from TopCV platform."""

    def __init__(
        self,
        keyword: str,
        location: str,
        dirs: dict[str, str],
        limit: int = 50,
        state_file: str | None = None,
        date_posted: str = "week",
    ) -> None:
        """Initializes TopCV scraper with search parameters."""
        super().__init__(
            "TopCV", keyword, location, dirs, limit, state_file, date_posted
        )

    def scrape(self, page: Any, context: Any) -> list[dict[str, Any]]:
        """Scrapes job search results and detailed job descriptions from TopCV."""
        import re

        kw_slug = re.sub(r"[^a-zA-Z0-9]+", "-", self.keyword.strip().lower()).strip("-")
        search_url = f"https://www.topcv.vn/tim-viec-lam-{kw_slug}"

        jobs = []
        seen_urls = set()

        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(2)
            for _ in range(3):
                page.evaluate("window.scrollBy(0, 1000)")
                time.sleep(0.8)
        except Exception as e:
            print(
                f"[TopCV] Slug search URL error: {e}. Trying query parameter fallback."
            )
            search_url_query = f"https://www.topcv.vn/tim-viec-lam-moi-nhat?keyword={urllib.parse.quote_plus(self.keyword)}"
            page.goto(search_url_query, wait_until="domcontentloaded", timeout=45000)
            time.sleep(2)
            for _ in range(3):
                page.evaluate("window.scrollBy(0, 1000)")
                time.sleep(0.8)

        # Multi-tier job card selectors
        card_selectors = [
            "div.job-item-search-result",
            "div.job-item-2",
            "div.job-item-default",
            "div.box-job-total .job-item",
            "div.job-item",
            ".box-item-search",
            "[data-box='box-job'] .job-item",
            ".job-list-search-result > div",
        ]
        job_cards = []
        for sel in card_selectors:
            try:
                cards = page.locator(sel).all()
                if cards:
                    job_cards = cards
                    print(f"[TopCV] Found {len(cards)} job cards using selector '{sel}'.")
                    break
            except Exception:
                continue

        if not job_cards:
            print(
                "[TopCV] No job cards matched known selectors, attempting fallback link extraction."
            )
            links = page.locator("a[href*='/viec-lam/']").all()
            for link_item in links:
                href = link_item.get_attribute("href")
                if (
                    href
                    and href not in seen_urls
                    and not any(x in href for x in ["/cong-ty", "/brand", "/login"])
                ):
                    if not href.startswith("http"):
                        href = "https://www.topcv.vn" + href
                    seen_urls.add(href)
                    t = link_item.inner_text().strip()
                    if t and len(t) > 5:
                        jobs.append(
                            {
                                "id": f"job_tcv_{len(jobs)}",
                                "title": t,
                                "company": "TopCV Employer",
                                "url": href.split("?")[0],
                                "source": "topcv",
                                "jd_text": "",
                            }
                        )
                        if len(jobs) >= self.limit:
                            break

        for card in job_cards:
            if len(jobs) >= self.limit:
                break

            title_el = card.locator(
                "h3.title a, h3 a, h2.title a, .job-title a, a.job_title, a[href*='/viec-lam/'], .title a"
            )
            if title_el.count() == 0:
                continue

            url = title_el.first.get_attribute("href")
            if not url:
                continue

            url = url.split("?")[0]
            if not url.startswith("http"):
                url = "https://www.topcv.vn" + url

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = ""
            # Try tooltip/attribute first
            for attr in ["data-original-title", "title", "aria-label"]:
                attr_val = title_el.first.get_attribute(attr)
                if attr_val and len(attr_val.strip()) > 3:
                    title = attr_val.strip()
                    break

            if not title:
                span_el = title_el.locator("span, strong, h3, h2")
                if span_el.count() > 0:
                    title = span_el.first.inner_text().strip()
                else:
                    title = title_el.first.inner_text().strip()

            company_el = card.locator(
                "a.company span.company-name, a.company, .company-name, .text-silver, span.name, a[href*='/brand/'], a.text-dark-blue, .company-title"
            )
            company = (
                company_el.first.inner_text().strip()
                if company_el.count() > 0
                else "Unknown Company"
            )

            jobs.append(
                {
                    "id": f"job_tcv_{len(jobs)}",
                    "title": title or "Unknown Title",
                    "company": company or "Unknown Company",
                    "url": url,
                    "source": "topcv",
                    "jd_text": "",
                },
            )

        print(f"[TopCV] Extracted {len(jobs)} unique job URLs. Fetching JDs and resolving metadata...")
        for j in jobs:
            try:
                page.goto(j["url"], wait_until="domcontentloaded", timeout=25000)
                time.sleep(1.5)

                # Fallback title extraction from JD page if missing
                if not j["title"] or j["title"] == "Unknown Title" or len(j["title"]) < 3:
                    page_title_el = page.locator("h1.job-title, h1.title, .job-header-info h1, h1, .header-job h1")
                    if page_title_el.count() > 0:
                        j["title"] = page_title_el.first.inner_text().strip()

                # Fallback company extraction from JD page if missing
                if not j["company"] or j["company"] == "Unknown Company":
                    page_company_el = page.locator(".company-title a, .company-name a, .job-header-info a, a[href*='/brand/'], .company-name")
                    if page_company_el.count() > 0:
                        j["company"] = page_company_el.first.inner_text().strip()

                jd_locator = page.locator(
                    ".job-data, .job-detail-content, .job-description, #job-description, .box-job-description, .job-detail__body, .job-body"
                )
                if jd_locator.count() > 0:
                    j["jd_text"] = jd_locator.first.inner_text().strip()
                else:
                    j["jd_text"] = page.evaluate("document.body.innerText").strip()
            except Exception:
                j["jd_text"] = "Description unavailable."

        # Filter out items that still have completely empty titles
        valid_jobs = [j for j in jobs if j.get("title") and j["title"] != "Unknown Title"]
        print(f"[TopCV] Successfully scraped {len(valid_jobs)} valid jobs.")
        return valid_jobs


def scrape_jobs(
    keyword: str,
    location: str,
    dirs: dict[str, str],
    limit: int = 50,
    state_file: str | None = None,
    date_posted: str = "week",
) -> list[dict[str, Any]]:
    """Entry point function to execute the TopCV scraper workflow."""
    scraper = TopCVScraper(keyword, location, dirs, limit, state_file, date_posted)
    return scraper.run()
