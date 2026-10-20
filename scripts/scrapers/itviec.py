import time
import urllib.parse

from scrapers.base_scraper import BaseScraper


class ITviecScraper(BaseScraper):
    def __init__(
        self, keyword, location, dirs, limit=50, state_file=None, date_posted="week"
    ):
        super().__init__(
            "ITviec", keyword, location, dirs, limit, state_file, date_posted
        )

    def scrape(self, page, context):
        encoded_keyword = urllib.parse.quote(self.keyword)
        kw_slug = self.keyword.strip().lower().replace(" ", "-")
        # Primary search URL with query parameter
        search_url = f"https://itviec.com/it-jobs?q={encoded_keyword}"

        jobs = []
        seen_urls = set()

        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(3)
        except Exception as e:
            print(f"[ITviec] Primary search URL error: {e}. Trying slug fallback.")
            search_url_slug = f"https://itviec.com/it-jobs/{kw_slug}"
            page.goto(search_url_slug, wait_until="domcontentloaded", timeout=45000)
            time.sleep(3)

        card_selectors = [
            "div.job-card",
            "div[data-search--job-selection-target='job']",
            "div.job",
            ".job_content",
            "div.search-job-item",
        ]
        job_cards = []
        for sel in card_selectors:
            cards = page.locator(sel).all()
            if cards:
                job_cards = cards
                print(f"[ITviec] Found {len(cards)} job cards using selector '{sel}'.")
                break

        if not job_cards:
            print("[ITviec] Fallback: Searching direct job links.")
            links = page.locator("a[href*='/it-jobs/']").all()
            for link_item in links:
                href = link_item.get_attribute("href")
                if (
                    href
                    and href not in seen_urls
                    and not any(
                        x in href for x in ["/companies", "/blog", "/salaries", "?"]
                    )
                ):
                    if not href.startswith("http"):
                        href = "https://itviec.com" + href
                    seen_urls.add(href)
                    t = link_item.inner_text().strip()

                    if t and len(t) > 5:
                        jobs.append(
                            {
                                "id": f"job_itv_{len(jobs)}",
                                "title": t,
                                "company": "ITviec Employer",
                                "url": href,
                                "source": "itviec",
                                "jd_text": "",
                            }
                        )
                        if len(jobs) >= self.limit:
                            break

        for card in job_cards:
            if len(jobs) >= self.limit:
                break

            slug = card.get_attribute("data-search--job-selection-job-slug-value")
            url = None
            if slug:
                url = f"https://itviec.com/it-jobs/{slug}"
            else:
                link_el = card.locator("h3 a, a[href*='/it-jobs/']")
                if link_el.count() > 0:
                    href = link_el.first.get_attribute("href")
                    if href:
                        url = (
                            href
                            if href.startswith("http")
                            else f"https://itviec.com{href}"
                        )

            if not url:
                continue

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title_el = card.locator(
                'h3[data-search--job-selection-target="jobTitle"], h3.title a, h3 a, h2 a, a.job-title'
            )
            title = (
                title_el.first.inner_text().strip()
                if title_el.count() > 0
                else "Unknown Title"
            )

            company_el = card.locator(
                "a.text-rich-grey, span.ims-2 a, .employer-name, .company-name, a.text-body"
            )
            company = (
                company_el.first.inner_text().strip()
                if company_el.count() > 0
                else "Unknown Company"
            )

            jobs.append(
                {
                    "id": f"job_itv_{len(jobs)}",
                    "title": title,
                    "company": company,
                    "url": url,
                    "source": "itviec",
                    "jd_text": "",
                },
            )

        print(
            f"[ITviec] Extracted {len(jobs)} unique job postings. Fetching JD details..."
        )
        for j in jobs:
            try:
                page.goto(j["url"], wait_until="domcontentloaded", timeout=25000)
                time.sleep(1.5)

                # Fallback title extraction from JD page if missing
                if not j["title"] or j["title"] == "Unknown Title" or len(j["title"]) < 3:
                    page_title_el = page.locator("h1.job-details__title, h1.title, h1, .header-job h1")
                    if page_title_el.count() > 0:
                        j["title"] = page_title_el.first.inner_text().strip()

                # Fallback company extraction from JD page if missing
                if not j["company"] or j["company"] == "Unknown Company":
                    page_company_el = page.locator(".employer-name a, .employer-info a, a.text-rich-grey, .employer-name")
                    if page_company_el.count() > 0:
                        j["company"] = page_company_el.first.inner_text().strip()

                jd_locator = page.locator(
                    ".job-details, .job-description, .job-details__paragraph, .jd-content, .job-details__overview, .paragraph, .job-detail"
                )
                if jd_locator.count() > 0:
                    j["jd_text"] = jd_locator.first.inner_text().strip()
                else:
                    j["jd_text"] = page.evaluate("document.body.innerText").strip()
            except Exception:
                j["jd_text"] = "Description unavailable."

        valid_jobs = [j for j in jobs if j.get("title") and j["title"] != "Unknown Title"]
        print(f"[ITviec] Scraped {len(valid_jobs)} valid jobs.")
        return valid_jobs


def scrape_jobs(keyword, location, dirs, limit=50, state_file=None, date_posted="week"):
    scraper = ITviecScraper(keyword, location, dirs, limit, state_file, date_posted)
    return scraper.run()
