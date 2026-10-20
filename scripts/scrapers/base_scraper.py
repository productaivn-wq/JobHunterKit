"""
base_scraper.py — Abstract base scraper class for JobHunterKit platform integrations.

Handles Playwright browser lifecycle, stealth configuration, storage state injection,
and structured output recording.
"""

import json
import os
import sys
from typing import Any

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth


class BaseScraper:
    """Abstract base scraper orchestrating Playwright context, stealth, and lifecycle."""

    def __init__(
        self,
        source_name: str,
        keyword: str,
        location: str,
        dirs: dict[str, str],
        limit: int = 50,
        state_file: str | None = None,
        date_posted: str = "week",
    ) -> None:
        """Initializes base scraper with search constraints and execution directories."""
        self.source_name = source_name
        self.keyword = keyword
        self.location = location
        self.dirs = dirs
        self.limit = limit
        self.state_file = state_file
        self.date_posted = date_posted

        # Configure standard output streams to handle UTF-8 printing safely
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass
        if hasattr(sys.stderr, "reconfigure"):
            try:
                sys.stderr.reconfigure(encoding="utf-8")
            except Exception:
                pass

    def run(self) -> list[dict[str, Any]]:
        """Executes browser setup, stealth configuration, and delegates to the scrape implementation."""
        print(
            f"[Scraper: {self.source_name}] Searching for '{self.keyword}' in '{self.location}'..."
        )
        jobs = []

        with sync_playwright() as p:
            # Set headless based on environment variable, default to False for visibility/stealth
            headless_env = os.environ.get("JOBHUNTER_HEADLESS", "false").lower()
            headless = headless_env not in ("false", "0")

            browser = p.chromium.launch(headless=headless, channel="chrome")
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

            if self.state_file and os.path.exists(self.state_file):
                context = browser.new_context(
                    storage_state=self.state_file,
                    user_agent=user_agent,
                )
            else:
                context = browser.new_context(user_agent=user_agent)

            page = context.new_page()
            Stealth().apply_stealth_sync(page)

            try:
                jobs = self.scrape(page, context)
            except Exception as e:
                print(f"[{self.source_name}] Scraper error: {e}")
            finally:
                browser.close()

        # Save output
        jobs_file = self.dirs.get("jobs_file", f"{self.source_name}_jobs.json")
        out_dir = os.path.dirname(os.path.abspath(jobs_file))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(jobs_file, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)

        print(
            f"[{self.source_name}] Successfully saved {len(jobs)} jobs to {jobs_file}"
        )
        return jobs_file

    def scrape(self, page, context):
        """Must be implemented by sub-scrapers. Should return a list of job dicts."""
        raise NotImplementedError("Subclasses must implement scrape()")
