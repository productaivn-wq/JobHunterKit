"""
LinkedIn Scraper Module Stub / Thin Wrapper.

Provides structural consistency across all scraper modules in scripts/scrapers/.
Actual scraping logic is implemented in services.scraping.live_linkedin_scrape.
"""

try:
    from scrapers.base_scraper import BaseScraper
except ImportError:
    from base_scraper import BaseScraper

from services.scraping import live_linkedin_scrape


class LinkedInScraper(BaseScraper):
    """
    LinkedIn Scraper wrapper class for interface consistency with other scrapers.
    Delegates job scraping logic to services.scraping.live_linkedin_scrape.
    """

    def __init__(
        self,
        keyword,
        location,
        dirs,
        limit=50,
        state_file=None,
        date_posted="week",
        source="linkedin",
    ):
        super().__init__(
            "LinkedIn", keyword, location, dirs, limit, state_file, date_posted
        )
        self.source = source

    def scrape(self, page, context):
        """
        Delegates to live_linkedin_scrape.
        Note: live_linkedin_scrape handles Playwright browser context initialization internally.
        """
        return live_linkedin_scrape(
            keyword=self.keyword,
            location=self.location,
            dirs=self.dirs,
            limit=self.limit,
            state_file=self.state_file,
            date_posted=self.date_posted,
            source=self.source,
        )

    def run(self):
        """
        Overrides BaseScraper.run() to directly execute live_linkedin_scrape,
        avoiding redundant Playwright context creation.
        """
        return live_linkedin_scrape(
            keyword=self.keyword,
            location=self.location,
            dirs=self.dirs,
            limit=self.limit,
            state_file=self.state_file,
            date_posted=self.date_posted,
            source=self.source,
        )


def scrape_jobs(
    keyword,
    location,
    dirs,
    limit=50,
    state_file=None,
    date_posted="week",
    source="linkedin",
    cli_mode: bool = False,
):
    """
    Module-level entry point function for LinkedIn scraping, providing structural consistency
    with other scrapers in scripts/scrapers/. Delegates to services.scraping.live_linkedin_scrape.
    """
    return live_linkedin_scrape(
        keyword=keyword,
        location=location,
        dirs=dirs,
        limit=limit,
        state_file=state_file,
        date_posted=date_posted,
        source=source,
        cli_mode=cli_mode,
    )
