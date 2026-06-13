"""
lookup.py — orchestrates the full tearsheet pipeline:
  1. Web-search for MST (tax code) → more reliable FiinGate match
  2. Detect company type (public / private) — DEFAULT is private → FiinGate
  3. Scrape FiinGate (default) or Vietstock (only if explicitly public)
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

# Keywords that explicitly signal a PUBLIC listed company
PUBLIC_KEYWORDS = ["public", "listed", "hose", "hnx", "upcom"]
# Keywords that explicitly signal PRIVATE
PRIVATE_KEYWORDS = ["private", "unlisted", "priv"]


def detect_type(query: str) -> Tuple[str, str]:
    """
    Returns (company_name_clean, type).
    Default is 'private' → FiinGate unless explicitly flagged as public.
    """
    q = query.lower()
    if any(w in q for w in PUBLIC_KEYWORDS):
        ctype = "public"
    else:
        # Default to private/FiinGate for everything else
        ctype = "private"
    name = re.sub(
        r"\b(private|public|listed|unlisted|priv|hose|hnx|upcom)\b", "",
        query, flags=re.I
    ).strip()
    return name, ctype


async def search_mst(company_name: str) -> Optional[str]:
    """
    Web-search for the company's Vietnamese tax code (MST).
    Returns tax code string if found, else None.
    """
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        # Try masothue.com search
        try:
            r = await client.get(
                "https://masothue.com/Search/SearchByKeyword",
                params={"keyword": company_name},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            matches = re.findall(r"\b(\d{10,13})\b", r.text)
            if matches:
                log.info(f"MST found via masothue.com: {matches[0]}")
                return matches[0]
        except Exception as e:
            log.warning(f"masothue.com lookup failed: {e}")

        # Fallback: tracuumst
        try:
            r = await client.get(
                "https://tracuumst.com.vn/",
                params={"mst": company_name},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            matches = re.findall(r"\b(\d{10,13})\b", r.text)
            if matches:
                log.info(f"MST found via tracuumst: {matches[0]}")
                return matches[0]
        except Exception as e:
            log.warning(f"tracuumst lookup failed: {e}")

    log.info("MST not found — will search by company name directly")
    return None


async def run_lookup(
    query: str,
    status_callback: Callable[[str], Awaitable[None]]
) -> Tuple[str, str, str, str]:
    """
    Full pipeline. Returns (pdf_path, company_name, source_label, note).
    """
    company_name, ctype = detect_type(query)

    # Routing:
    # - public  → Vietstock first, FiinGate fallback
    # - private → FiinGate first, no fallback needed
    # - default → FiinGate (same as private)
    primary_source   = "Vietstock" if ctype == "public" else "FiinGate"
    fallback_source  = "FiinGate"  if ctype == "public" else None

    # Step 1: find MST
    await status_callback(f"🔍 Searching tax code (MST) for *{company_name}*...")
    mst = await search_mst(company_name)
    mst_note = f"MST: {mst}" if mst else "MST not found — searching by name"
    log.info(f"Company: {company_name} | Type: {ctype} | MST: {mst} | Source: {primary_source}")

    # Step 2: scrape
    raw_data = None
    source_used = primary_source

    await status_callback(
        f"📡 Fetching from *{primary_source}*...\n_{mst_note}_"
    )

    if primary_source == "FiinGate":
        raw_data = await scrape_fiingate(company_name, mst)
    else:
        raw_data = await scrape_vietstock(company_name, mst)
        if not raw_data and fallback_source:
            await status_callback(f"⚠️ {primary_source} returned no data — trying *{fallback_source}*...")
            raw_data = await scrape_fiingate(company_name, mst)
            source_used = fallback_source

    if not raw_data:
        raise ValueError(
            f"No data found for '{company_name}' on {source_used}. "
            "Make sure FiinGate credentials are correct."
        )

    # Step 3: structure with Claude
    await status_callback(f"🤖 Structuring data with Claude...")
    structured = await structure_data(
        company_name=company_name,
        raw_text=raw_data,
        ctype=ctype,
        source=source_used,
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

    return tmp.name, display_name, source_used, note
