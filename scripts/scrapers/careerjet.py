"""
careerjet.py — Careerjet job scraper implementation for JobHunterKit.

Extracts job postings from Careerjet based on search query keywords and locations.
"""

import logging
import urllib.parse
from typing import Any

from .base_scraper import BaseScraper

logger = logging.getLogger("JobHunter.Scrapers.Careerjet")


class CareerjetScraper(BaseScraper):
    """Scraper implementation for extracting jobs from Careerjet."""

    def __init__(
        self,
        keyword: str,
        location: str,
        dirs: dict[str, str],
        limit: int = 50,
        state_file: str | None = None,
        date_posted: str = "week",
    ) -> None:
        """Initializes Careerjet scraper with query parameters."""
        super().__init__(
            "careerjet",
            keyword,
            location,
            dirs,
            limit=limit,
            state_file=state_file,
            date_posted=date_posted,
        )

    def scrape(self, page: Any, context: Any) -> list[dict[str, Any]]:
        """Scrapes search results and parses individual card metadata."""
        kw_enc = urllib.parse.quote_plus(self.keyword)
        loc_enc = urllib.parse.quote_plus(self.location)
        url = f"https://www.careerjet.com/search/jobs?s={kw_enc}&l={loc_enc}"

        logger.info(f"[Careerjet] Fetching URL: {url}")
        jobs = []

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

            # Extract job cards
            cards = page.query_selector_all("article.job, div.job, article[data-url]")
            for idx, card in enumerate(cards):
                if len(jobs) >= self.limit:
                    break
                try:
                    title_el = card.query_selector("h2 a, a.title, header h2 a")
                    title = (
                        title_el.inner_text().strip() if title_el else "Unknown Title"
                    )
                    link = title_el.get_attribute("href") if title_el else ""
                    if link and not link.startswith("http"):
                        link = f"https://www.careerjet.com{link}"

                    comp_el = card.query_selector(
                        "p.company, div.company, span.company"
                    )
                    company = (
                        comp_el.inner_text().strip() if comp_el else "Unknown Company"
                    )

                    loc_el = card.query_selector(
                        "ul.location, div.location, span.location"
                    )
                    location = loc_el.inner_text().strip() if loc_el else self.location

                    desc_el = card.query_selector(
                        "div.desc, p.desc, div.advertise_compact"
                    )
                    jd_text = desc_el.inner_text().strip() if desc_el else ""

                    job_id = f"careerjet_{idx}_{hash(link) & 0xFFFFFF}"
                    jobs.append(
                        {
                            "id": job_id,
                            "title": title,
                            "company": company,
                            "location": location,
                            "url": link,
                            "source": "careerjet",
                            "jd_text": jd_text,
                        }
                    )
                except Exception as card_err:
                    logger.debug(f"[Careerjet] Error parsing card {idx}: {card_err}")

        except Exception as e:
            logger.warning(f"[Careerjet] Scraping failed or timed out: {e}")

        return jobs


def scrape_jobs(
    keyword: str,
    location: str,
    dirs: dict[str, str],
    limit: int = 50,
    state_file: str | None = None,
    date_posted: str = "week",
) -> list[dict[str, Any]]:
    """Entry point function to execute the Careerjet scraper workflow."""
    scraper = CareerjetScraper(keyword, location, dirs, limit, state_file, date_posted)
    return scraper.run()
