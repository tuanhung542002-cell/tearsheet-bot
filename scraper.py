"""
scraper.py — headless browser scraping via Playwright.

FiinGate  : app.fiingate.vn  (requires login — session cookies reused)
Vietstock : finance.vietstock.vn  (public, no login needed for basic data)

The scraper returns raw text blobs; Claude structures them in claude_client.py.
"""

import os
import json
import logging
import asyncio
from typing import Optional
from playwright.async_api import async_playwright, Page, BrowserContext

log = logging.getLogger(__name__)

FIINGATE_EMAIL    = os.environ.get("FIINGATE_EMAIL", "")
FIINGATE_PASSWORD = os.environ.get("FIINGATE_PASSWORD", "")
FIINGATE_SESSION  = os.environ.get("FIINGATE_SESSION_FILE", "/tmp/fiingate_session.json")


# ─────────────────────────────────────────────
# Shared browser context (singleton per process)
# ─────────────────────────────────────────────

_browser = None
_playwright = None

async def get_browser():
    global _browser, _playwright
    if _browser is None:
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
    return _browser


async def new_context(browser) -> BrowserContext:
    ctx = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
    return ctx


# ─────────────────────────────────────────────
# FiinGate
# ─────────────────────────────────────────────

async def fiingate_login(page: Page):
    """Login to FiinGate and save session cookies."""
    if not FIINGATE_EMAIL or not FIINGATE_PASSWORD:
        raise EnvironmentError(
            "FIINGATE_EMAIL and FIINGATE_PASSWORD env vars must be set for private company lookups."
        )
    log.info("Logging into FiinGate...")
    await page.goto("https://app.fiingate.vn/login", wait_until="networkidle")
    await page.fill("input[type='email'], input[name='email']", FIINGATE_EMAIL)
    await page.fill("input[type='password']", FIINGATE_PASSWORD)
    await page.click("button[type='submit']")
    await page.wait_for_url("**/dashboard**", timeout=15000)
    log.info("FiinGate login successful")


async def fiingate_get_session(ctx: BrowserContext, page: Page):
    """Load saved session or login fresh."""
    if os.path.exists(FIINGATE_SESSION):
        try:
            with open(FIINGATE_SESSION) as f:
                cookies = json.load(f)
            await ctx.add_cookies(cookies)
            await page.goto("https://app.fiingate.vn/dashboard", wait_until="networkidle", timeout=15000)
            if "dashboard" in page.url:
                log.info("FiinGate session restored from file")
                return
        except Exception as e:
            log.warning(f"Session restore failed: {e}")

    await fiingate_login(page)
    cookies = await ctx.cookies()
    with open(FIINGATE_SESSION, "w") as f:
        json.dump(cookies, f)


async def scrape_fiingate(company_name: str, mst: Optional[str]) -> Optional[str]:
    """
    Navigate FiinGate, find the company by MST or name,
    and extract financial statements as text.
    """
    browser = await get_browser()
    ctx = await new_context(browser)
    page = await ctx.new_page()

    try:
        await fiingate_get_session(ctx, page)

        # Navigate directly by MST if available (most reliable)
        if mst:
            url = f"https://app.fiingate.vn/companyAnalysis/summary?taxCode={mst}"
            log.info(f"FiinGate: navigating by MST {mst}")
        else:
            # Use search
            url = f"https://app.fiingate.vn/dashboard"

        await page.goto(url, wait_until="networkidle", timeout=20000)

        # If using name search, type into search bar
        if not mst:
            search = page.locator("input[placeholder*='company'], input[placeholder*='Enter company']")
            await search.fill(company_name)
            await page.wait_for_timeout(2000)
            # Click first result
            first = page.locator(".search-dropdown li, [class*='suggestion']").first
            await first.click()
            await page.wait_for_load_state("networkidle")

        # Check we landed on a company page
        if "companyAnalysis" not in page.url and "organizationId" not in page.url:
            log.warning(f"FiinGate: did not land on company page. URL: {page.url}")
            return None

        org_id = ""
        match = __import__("re").search(r"organizationId=(\d+)", page.url)
        if match:
            org_id = match.group(1)

        sections = {}

        # ── Summary ──────────────────────────────────
        await page.goto(
            f"https://app.fiingate.vn/companyAnalysis/summary?organizationId={org_id}",
            wait_until="networkidle"
        ) if org_id else None
        sections["summary"] = await page.inner_text("body")

        # ── Income Statement ─────────────────────────
        await page.goto(
            f"https://app.fiingate.vn/companyAnalysis/financial/financialStatements?organizationId={org_id}",
            wait_until="networkidle"
        )
        # Click Income Statement tab
        try:
            await page.click("text=Income Statement", timeout=5000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass
        sections["income_statement"] = await page.inner_text("body")

        # ── Balance Sheet ─────────────────────────────
        try:
            await page.click("text=Balance Sheet", timeout=5000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass
        sections["balance_sheet"] = await page.inner_text("body")

        # ── Cash Flow ────────────────────────────────
        try:
            await page.click("text=Cash Flow Statement", timeout=5000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass
        sections["cash_flow"] = await page.inner_text("body")

        combined = "\n\n===SUMMARY===\n" + sections.get("summary", "") + \
                   "\n\n===INCOME STATEMENT===\n" + sections.get("income_statement", "") + \
                   "\n\n===BALANCE SHEET===\n" + sections.get("balance_sheet", "") + \
                   "\n\n===CASH FLOW===\n" + sections.get("cash_flow", "")

        log.info(f"FiinGate: extracted {len(combined)} chars for {company_name}")
        return combined

    except Exception as e:
        log.exception(f"FiinGate scrape failed for '{company_name}': {e}")
        return None
    finally:
        await ctx.close()


# ─────────────────────────────────────────────
# Vietstock
# ─────────────────────────────────────────────

async def scrape_vietstock(company_name: str, mst: Optional[str]) -> Optional[str]:
    """
    Scrape Vietstock finance pages for a public company.
    Tries ticker search first; falls back to company name search.
    """
    browser = await get_browser()
    ctx = await new_context(browser)
    page = await ctx.new_page()

    try:
        # Vietstock search
        search_url = f"https://finance.vietstock.vn/search?q={company_name.replace(' ', '+')}"
        log.info(f"Vietstock: searching '{company_name}'")
        await page.goto(search_url, wait_until="networkidle", timeout=20000)
        await page.wait_for_timeout(2000)

        # Try to find and click the first company result
        try:
            first_result = page.locator("a[href*='/company/'], .search-result a, .company-link").first
            href = await first_result.get_attribute("href")
            if href:
                if not href.startswith("http"):
                    href = "https://finance.vietstock.vn" + href
                await page.goto(href, wait_until="networkidle", timeout=20000)
        except Exception as e:
            log.warning(f"Vietstock: couldn't click result: {e}")
            # Try direct ticker URL pattern
            ticker = company_name.upper().split()[0]
            await page.goto(
                f"https://finance.vietstock.vn/{ticker}/tai-chinh.htm",
                wait_until="networkidle", timeout=15000
            )

        await page.wait_for_timeout(1500)
        sections = {}
        sections["overview"] = await page.inner_text("body")

        # Navigate to financials tab
        try:
            await page.click("text=Tài chính, text=Financials, a[href*='tai-chinh']", timeout=5000)
            await page.wait_for_timeout(2000)
            sections["financials"] = await page.inner_text("body")
        except Exception:
            pass

        combined = "\n\n===OVERVIEW===\n" + sections.get("overview", "") + \
                   "\n\n===FINANCIALS===\n" + sections.get("financials", "")

        log.info(f"Vietstock: extracted {len(combined)} chars for {company_name}")
        return combined if len(combined) > 500 else None

    except Exception as e:
        log.exception(f"Vietstock scrape failed for '{company_name}': {e}")
        return None
    finally:
        await ctx.close()
