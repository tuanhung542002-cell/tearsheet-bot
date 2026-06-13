"""
lookup.py — orchestrates the full tearsheet pipeline:
  1. Detect company type (public / private)
  2. Web-search for MST (tax code) → more reliable FiinGate match
  3. Scrape FiinGate (private) or Vietstock (public)
  4. Send raw data to Claude API for structuring
  5. Generate PDF and return path
"""

import asyncio
import re
import os
import logging
import tempfile
from typing import Callable, Awaitable, Optional, Tuple

import httpx
from scraper import scrape_fiingate, scrape_vietstock
from claude_client import structure_data
from pdf_gen import build_pdf

log = logging.getLogger(__name__)

USD_VND = float(os.environ.get("USD_VND_RATE", "26500"))


def detect_type(query: str) -> Tuple[str, str]:
    """Returns (company_name_clean, type) where type is 'public' or 'private'."""
    q = query.lower()
    if any(w in q for w in ["private", "unlisted", "priv"]):
        ctype = "private"
    elif any(w in q for w in ["public", "listed", "hose", "hnx", "upcom"]):
        ctype = "public"
    else:
        ctype = "public"  # default
    name = re.sub(r"\b(private|public|listed|unlisted|priv|hose|hnx|upcom)\b", "", query, flags=re.I).strip()
    return name, ctype


async def search_mst(company_name: str) -> Optional[str]:
    """
    Web-search for the company's Vietnamese tax code (MST/mã số thuế).
    Returns the tax code string if found, else None.
    """
    search_query = f"{company_name} mã số thuế MST Vietnam"
    url = f"https://www.google.com/search?q={httpx.URL(search_query)}"

    # Use DuckDuckGo instant answer API (no auth needed)
    ddg_url = "https://api.duckduckgo.com/"
    params = {
        "q": f"{company_name} tax code Vietnam site:masothue.com OR site:tracuumst.com.vn",
        "format": "json",
        "no_redirect": "1",
        "no_html": "1",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Try masothue.com search
            r = await client.get(
                "https://masothue.com/Search/SearchByKeyword",
                params={"keyword": company_name},
                headers={"User-Agent": "Mozilla/5.0"},
                follow_redirects=True
            )
            text = r.text
            # Extract 10-13 digit tax code from response
            matches = re.findall(r"\b(\d{10,13})\b", text)
            if matches:
                log.info(f"MST found via masothue.com: {matches[0]}")
                return matches[0]
    except Exception as e:
        log.warning(f"masothue.com lookup failed: {e}")

    # Fallback: try tracuumst
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://tracuumst.com.vn/",
                params={"mst": company_name},
                headers={"User-Agent": "Mozilla/5.0"},
                follow_redirects=True
            )
            matches = re.findall(r"\b(\d{10,13})\b", r.text)
            if matches:
                log.info(f"MST found via tracuumst: {matches[0]}")
                return matches[0]
    except Exception as e:
        log.warning(f"tracuumst lookup failed: {e}")

    log.info("MST not found via web search — will use company name directly")
    return None


async def run_lookup(
    query: str,
    status_callback: Callable[[str], Awaitable[None]]
) -> Tuple[str, str, str, str]:
    """
    Full pipeline. Returns (pdf_path, company_name, source_label, note).
    """
    company_name, ctype = detect_type(query)
    source = "FiinGate" if ctype == "private" else "Vietstock"

    # Step 1: find MST
    await status_callback(f"🔍 Searching tax code for *{company_name}*...")
    mst = await search_mst(company_name)
    mst_note = f"MST: {mst}" if mst else "MST not found — searching by name"
    log.info(f"Company: {company_name} | Type: {ctype} | MST: {mst}")

    # Step 2: scrape source
    await status_callback(
        f"📡 Fetching data from *{source}*...\n_{mst_note}_"
    )

    if ctype == "private":
        raw_data = await scrape_fiingate(company_name, mst)
        if not raw_data and mst:
            # retry without MST
            raw_data = await scrape_fiingate(company_name, None)
    else:
        raw_data = await scrape_vietstock(company_name, mst)
        if not raw_data:
            # Fallback to FiinGate for public companies too
            await status_callback(f"⚠️ Vietstock lookup failed — trying *FiinGate*...")
            raw_data = await scrape_fiingate(company_name, mst)
            source = "FiinGate (fallback)"

    if not raw_data:
        raise ValueError(f"No data found for '{company_name}' on {source}. Make sure you are logged in.")

    # Step 3: structure with Claude
    await status_callback(f"🤖 Structuring data with Claude...")
    structured = await structure_data(
        company_name=company_name,
        raw_text=raw_data,
        ctype=ctype,
        source=source,
        usd_vnd=USD_VND
    )

    # Step 4: generate PDF
    await status_callback(f"📄 Generating PDF tearsheet...")
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    build_pdf(structured, tmp.name)

    display_name = structured.get("name", company_name)
    note = structured.get("data_note", "")
    if mst:
        note = f"MST {mst} · " + note if note else f"MST {mst}"

    return tmp.name, display_name, source, note
