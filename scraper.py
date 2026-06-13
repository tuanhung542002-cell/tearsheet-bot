"""
scraper.py — FiinGate scraper using OIDC auth + direct HTML scraping.

FiinGate uses OpenID Connect via https://auth.fiingroup.vn
Auth flow: Resource Owner Password Credentials (ROPC) grant
Pages are server-side rendered — data is in the HTML body.
"""

import httpx
import logging
import os
import re
import json
from typing import Optional
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

FIINGATE_EMAIL    = os.environ.get("FIINGATE_EMAIL", "")
FIINGATE_PASSWORD = os.environ.get("FIINGATE_PASSWORD", "")
USD_VND           = float(os.environ.get("USD_VND_RATE", "26500"))

BASE_URL   = "https://app.fiingate.vn"
AUTH_URL   = "https://auth.fiingroup.vn"
CLIENT_ID  = "FiinGroup.FiinGate.Client"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Auth ──────────────────────────────────────────────────────────

async def get_access_token(client: httpx.AsyncClient) -> Optional[str]:
    """
    Get Bearer token via OIDC Resource Owner Password Credentials grant.
    """
    if not FIINGATE_EMAIL or not FIINGATE_PASSWORD:
        raise EnvironmentError("FIINGATE_EMAIL and FIINGATE_PASSWORD env vars required.")

    # Try ROPC grant against FiinGroup auth server
    token_endpoints = [
        f"{AUTH_URL}/connect/token",
        f"{AUTH_URL}/oauth/token",
        f"{BASE_URL}/api/auth/token",
        f"{BASE_URL}/connect/token",
    ]

    for endpoint in token_endpoints:
        try:
            r = await client.post(endpoint, data={
                "grant_type": "password",
                "username": FIINGATE_EMAIL,
                "password": FIINGATE_PASSWORD,
                "client_id": CLIENT_ID,
                "scope": "openid FiinGroup.FiinGate offline_access",
            }, headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"}, timeout=15)

            if r.status_code == 200:
                data = r.json()
                token = data.get("access_token")
                if token:
                    log.info(f"OIDC token obtained via {endpoint}")
                    return token
            else:
                log.debug(f"Token endpoint {endpoint}: {r.status_code}")
        except Exception as e:
            log.debug(f"Token endpoint {endpoint} failed: {e}")

    # Fallback: try cookie-based login via the web app
    log.info("ROPC failed — trying cookie-based login")
    return await cookie_login(client)


async def cookie_login(client: httpx.AsyncClient) -> Optional[str]:
    """
    Login via the web login form and get session cookies.
    Returns a dummy sentinel so we know to use cookies instead of Bearer.
    """
    try:
        # Get login page first (for CSRF token if any)
        r = await client.get(f"{BASE_URL}/login",
                             headers=HEADERS, timeout=10, follow_redirects=True)

        # Try the login form
        login_data = {
            "Email": FIINGATE_EMAIL,
            "Password": FIINGATE_PASSWORD,
        }
        r2 = await client.post(f"{BASE_URL}/api/Account/Login",
                               json=login_data,
                               headers={**HEADERS, "Content-Type": "application/json"},
                               timeout=15)
        if r2.status_code in (200, 302):
            log.info(f"Cookie login: {r2.status_code}")
            return "COOKIE_AUTH"  # sentinel

        # Try alternative login endpoint
        r3 = await client.post(f"{BASE_URL}/api/auth/login",
                               json={"email": FIINGATE_EMAIL, "password": FIINGATE_PASSWORD},
                               headers={**HEADERS, "Content-Type": "application/json"},
                               timeout=15)
        if r3.status_code == 200:
            data = r3.json()
            token = data.get("token") or data.get("access_token")
            if token:
                log.info("Got token via /api/auth/login")
                return token
            return "COOKIE_AUTH"

    except Exception as e:
        log.warning(f"Cookie login failed: {e}")
    return None


# ── Company search ────────────────────────────────────────────────

async def find_org_id(client: httpx.AsyncClient, company_name: str,
                      mst: Optional[str]) -> Optional[str]:
    """Find FiinGate organizationId by MST or name."""

    search_headers = dict(client.headers)

    # Try search API endpoints
    search_attempts = []
    if mst:
        search_attempts += [
            f"{BASE_URL}/api/v1/search?taxCode={mst}",
            f"{BASE_URL}/api/search?taxCode={mst}&type=company",
            f"{BASE_URL}/api/v2/company/search?taxCode={mst}",
        ]
    search_attempts += [
        f"{BASE_URL}/api/v1/search?keyword={httpx.URL(company_name)}&type=company",
        f"{BASE_URL}/api/search?keyword={company_name}&limit=5",
        f"{BASE_URL}/domesticSearch?text={company_name}",
    ]

    for url in search_attempts:
        try:
            r = await client.get(url, timeout=10)
            if r.status_code == 200:
                text = r.text
                # Try to parse JSON
                try:
                    data = r.json()
                    items = (data.get("data") or data.get("items") or
                             data.get("result") or data.get("companies") or [])
                    if isinstance(items, list) and items:
                        org_id = (items[0].get("organizationId") or
                                  items[0].get("id") or
                                  items[0].get("orgId"))
                        if org_id:
                            log.info(f"Found orgId {org_id} via {url}")
                            return str(org_id)
                except Exception:
                    pass
                # Try to extract org ID from HTML/text
                match = re.search(r'"organizationId"\s*:\s*(\d+)', text)
                if match:
                    log.info(f"Found orgId {match.group(1)} in response text")
                    return match.group(1)
        except Exception as e:
            log.debug(f"Search {url}: {e}")

    # Try navigating the search page and parsing the redirect URL
    try:
        r = await client.get(
            f"{BASE_URL}/domesticSearch",
            params={"text": mst or company_name},
            timeout=10, follow_redirects=True
        )
        match = re.search(r'organizationId[=:](\d+)', r.url.path + r.url.query)
        if not match:
            match = re.search(r'organizationId[=:](\d+)', r.text)
        if match:
            log.info(f"Found orgId {match.group(1)} from search redirect")
            return match.group(1)
    except Exception as e:
        log.debug(f"Search page: {e}")

    return None


# ── Page scraping ─────────────────────────────────────────────────

async def scrape_page_text(client: httpx.AsyncClient, url: str) -> str:
    """Fetch a FiinGate page and return clean text."""
    try:
        r = await client.get(url, timeout=20, follow_redirects=True)
        if r.status_code != 200:
            log.warning(f"Page {url}: {r.status_code}")
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        log.info(f"Scraped {url}: {len(text)} chars")
        return text
    except Exception as e:
        log.warning(f"Scrape {url} failed: {e}")
        return ""


# ── Main FiinGate scraper ─────────────────────────────────────────

async def scrape_fiingate(company_name: str, mst: Optional[str]) -> Optional[str]:
    """
    Main entry point. Returns combined financial text blob.
    """
    async with httpx.AsyncClient(
        headers=HEADERS, follow_redirects=True, timeout=30,
        cookies={}, verify=True
    ) as client:

        # 1. Authenticate
        token = await get_access_token(client)
        if token and token != "COOKIE_AUTH":
            client.headers["Authorization"] = f"Bearer {token}"
        elif not token:
            log.warning("No auth token — trying unauthenticated scrape")

        # 2. Find org ID
        org_id = None
        if mst:
            # Direct URL by tax code — most reliable
            log.info(f"Trying direct orgId lookup by MST {mst}")
            test_url = f"{BASE_URL}/companyAnalysis/summary?taxCode={mst}"
            r = await client.get(test_url, timeout=15)
            match = re.search(r'organizationId[=:](\d+)', str(r.url) + r.text[:2000])
            if match:
                org_id = match.group(1)
                log.info(f"Got orgId {org_id} from taxCode URL")

        if not org_id:
            org_id = await find_org_id(client, company_name, mst)

        if not org_id:
            log.warning(f"Could not find orgId for '{company_name}' — trying known ID for Kingfoodmart")
            # Hardcode known working org IDs as last resort
            known = {"king food": "261279", "kingfoodmart": "261279", "king food market": "261279"}
            for k, v in known.items():
                if k in company_name.lower():
                    org_id = v
                    log.info(f"Using known orgId {org_id}")
                    break

        if not org_id:
            log.error(f"No orgId found for '{company_name}'")
            return None

        # 3. Scrape all financial pages
        base = f"{BASE_URL}/companyAnalysis"
        pages = {
            "summary":  f"{base}/summary?organizationId={org_id}",
            "income":   f"{base}/financial/financialStatements?organizationId={org_id}",
            "balance":  f"{base}/financial/financialStatements?organizationId={org_id}",
            "cashflow": f"{base}/financial/financialStatements?organizationId={org_id}",
        }

        texts = {}
        for key, url in pages.items():
            texts[key] = await scrape_page_text(client, url)

        combined = (
            f"\n===SUMMARY===\n{texts.get('summary','')}"
            f"\n===INCOME STATEMENT===\n{texts.get('income','')}"
        )

        if len(combined) < 500:
            log.error("FiinGate scrape returned too little data — auth may have failed")
            return None

        log.info(f"FiinGate total: {len(combined)} chars")
        return combined


# ── Vietstock ─────────────────────────────────────────────────────

async def scrape_vietstock(company_name: str, mst: Optional[str]) -> Optional[str]:
    """Scrape Vietstock for public company (ticker required)."""
    ticker = company_name.upper().split()[0]
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20) as client:
        sections = {}
        try:
            r = await client.get(f"https://finance.vietstock.vn/{ticker}/tai-chinh.htm")
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer"]):
                    tag.decompose()
                sections["overview"] = soup.get_text(separator="\n", strip=True)[:5000]
        except Exception as e:
            log.warning(f"Vietstock failed: {e}")

        combined = f"\n===VIETSTOCK===\n{sections.get('overview','')}"
        return combined if len(combined) > 300 else None
