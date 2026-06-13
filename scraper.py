"""
scraper.py — lightweight HTTP scraper using httpx + BeautifulSoup.
No Playwright / headless browser needed on the server.

Strategy:
- FiinGate: uses their internal JSON API endpoints (no browser needed)
- Vietstock: scrapes finance.vietstock.vn HTML + JSON endpoints
- MST lookup: masothue.com
"""

import httpx
import logging
import os
import re
from typing import Optional
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

FIINGATE_EMAIL    = os.environ.get("FIINGATE_EMAIL", "")
FIINGATE_PASSWORD = os.environ.get("FIINGATE_PASSWORD", "")
USD_VND           = float(os.environ.get("USD_VND_RATE", "26500"))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


# ─────────────────────────────────────────────
# FiinGate — API-based (no browser)
# ─────────────────────────────────────────────

async def fiingate_login(client: httpx.AsyncClient) -> bool:
    """Login to FiinGate API and get auth token."""
    if not FIINGATE_EMAIL or not FIINGATE_PASSWORD:
        raise EnvironmentError("FIINGATE_EMAIL and FIINGATE_PASSWORD must be set.")
    try:
        r = await client.post(
            "https://app.fiingate.vn/api/auth/login",
            json={"email": FIINGATE_EMAIL, "password": FIINGATE_PASSWORD},
            headers={**HEADERS, "Content-Type": "application/json"},
            timeout=15
        )
        if r.status_code == 200:
            data = r.json()
            token = data.get("token") or data.get("access_token") or data.get("data", {}).get("token")
            if token:
                client.headers["Authorization"] = f"Bearer {token}"
                log.info("FiinGate API login successful")
                return True
        log.warning(f"FiinGate login returned {r.status_code}: {r.text[:300]}")
        return False
    except Exception as e:
        log.warning(f"FiinGate API login failed: {e}")
        return False


async def fiingate_search_org(client: httpx.AsyncClient, name: str, mst: Optional[str]) -> Optional[str]:
    """Search FiinGate for organization ID."""
    # Try by tax code first
    if mst:
        try:
            r = await client.get(
                f"https://app.fiingate.vn/api/company/search",
                params={"taxCode": mst, "limit": 5},
                timeout=10
            )
            if r.status_code == 200:
                items = r.json().get("data", []) or r.json().get("items", [])
                if items:
                    org_id = items[0].get("organizationId") or items[0].get("id")
                    if org_id:
                        log.info(f"FiinGate org found by MST: {org_id}")
                        return str(org_id)
        except Exception as e:
            log.warning(f"FiinGate search by MST failed: {e}")

    # Try by name
    try:
        r = await client.get(
            f"https://app.fiingate.vn/api/company/search",
            params={"keyword": name, "limit": 5},
            timeout=10
        )
        if r.status_code == 200:
            items = r.json().get("data", []) or r.json().get("items", [])
            if items:
                org_id = items[0].get("organizationId") or items[0].get("id")
                if org_id:
                    log.info(f"FiinGate org found by name: {org_id}")
                    return str(org_id)
    except Exception as e:
        log.warning(f"FiinGate search by name failed: {e}")

    return None


async def fiingate_fetch_financials(client: httpx.AsyncClient, org_id: str) -> dict:
    """Pull financial data from FiinGate API endpoints."""
    results = {}
    endpoints = {
        "summary":  f"https://app.fiingate.vn/api/company/{org_id}/summary",
        "income":   f"https://app.fiingate.vn/api/company/{org_id}/financial/income-statement",
        "balance":  f"https://app.fiingate.vn/api/company/{org_id}/financial/balance-sheet",
        "cashflow": f"https://app.fiingate.vn/api/company/{org_id}/financial/cash-flow",
    }
    for key, url in endpoints.items():
        try:
            r = await client.get(url, timeout=15)
            if r.status_code == 200:
                results[key] = r.text
                log.info(f"FiinGate {key}: {len(r.text)} chars")
            else:
                log.warning(f"FiinGate {key}: {r.status_code}")
                results[key] = ""
        except Exception as e:
            log.warning(f"FiinGate {key} failed: {e}")
            results[key] = ""
    return results


async def scrape_fiingate(company_name: str, mst: Optional[str]) -> Optional[str]:
    """Main FiinGate scraper — returns combined text blob."""
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        logged_in = await fiingate_login(client)
        if not logged_in:
            # Try without login for public endpoints
            log.info("Proceeding without FiinGate login")

        org_id = await fiingate_search_org(client, company_name, mst)
        if not org_id:
            log.warning(f"FiinGate: no org found for '{company_name}'")
            # Return whatever we scraped from masothue as fallback context
            return await scrape_masothue_profile(company_name, mst)

        data = await fiingate_fetch_financials(client, org_id)

        combined = (
            f"\n===SUMMARY===\n{data.get('summary','')}"
            f"\n===INCOME STATEMENT===\n{data.get('income','')}"
            f"\n===BALANCE SHEET===\n{data.get('balance','')}"
            f"\n===CASH FLOW===\n{data.get('cashflow','')}"
        )
        log.info(f"FiinGate total: {len(combined)} chars")
        return combined if len(combined) > 200 else None


# ─────────────────────────────────────────────
# Masothue fallback — company profile
# ─────────────────────────────────────────────

async def scrape_masothue_profile(company_name: str, mst: Optional[str]) -> Optional[str]:
    """Scrape basic company profile from masothue.com."""
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
        try:
            query = mst if mst else company_name
            r = await client.get(
                f"https://masothue.com/Search/SearchByKeyword?keyword={query}",
                timeout=10
            )
            soup = BeautifulSoup(r.text, "html.parser")
            text = soup.get_text(separator="\n", strip=True)
            log.info(f"masothue.com: {len(text)} chars")
            return f"===COMPANY PROFILE (masothue.com)===\n{text[:5000]}" if text else None
        except Exception as e:
            log.warning(f"masothue scrape failed: {e}")
            return None


# ─────────────────────────────────────────────
# Vietstock — public company data
# ─────────────────────────────────────────────

async def scrape_vietstock(company_name: str, mst: Optional[str]) -> Optional[str]:
    """Scrape Vietstock for public company financials."""
    ticker = company_name.upper().split()[0]  # e.g. "MSN" from "MSN public"

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20) as client:
        sections = {}

        # 1. Stock overview
        try:
            r = await client.get(
                f"https://finance.vietstock.vn/{ticker}/tai-chinh.htm",
                timeout=15
            )
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                # Remove scripts/styles
                for tag in soup(["script", "style", "nav", "footer"]):
                    tag.decompose()
                sections["overview"] = soup.get_text(separator="\n", strip=True)[:4000]
                log.info(f"Vietstock overview: {len(sections['overview'])} chars")
        except Exception as e:
            log.warning(f"Vietstock overview failed: {e}")

        # 2. Try Vietstock API for financial data
        try:
            r = await client.post(
                "https://finance.vietstock.vn/data/financeinfo",
                data={"Code": ticker, "ReportType": "BCTC", "ReportTermType": "1", "Unit": "1000000"},
                headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded",
                         "Referer": f"https://finance.vietstock.vn/{ticker}/tai-chinh.htm"},
                timeout=15
            )
            if r.status_code == 200:
                sections["financials_api"] = r.text[:5000]
                log.info(f"Vietstock financials API: {len(r.text)} chars")
        except Exception as e:
            log.warning(f"Vietstock financials API failed: {e}")

        # 3. Cafef as additional source
        try:
            r = await client.get(
                f"https://cafef.vn/thi-truong-chung-khoan/ket-qua-kinh-doanh-{ticker.lower()}-1.chn",
                timeout=12
            )
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                sections["cafef"] = soup.get_text(separator="\n", strip=True)[:4000]
                log.info(f"Cafef: {len(sections['cafef'])} chars")
        except Exception as e:
            log.warning(f"Cafef failed: {e}")

        combined = (
            f"\n===VIETSTOCK OVERVIEW===\n{sections.get('overview','')}"
            f"\n===FINANCIAL DATA===\n{sections.get('financials_api','')}"
            f"\n===CAFEF DATA===\n{sections.get('cafef','')}"
        )
        return combined if len(combined) > 300 else None
