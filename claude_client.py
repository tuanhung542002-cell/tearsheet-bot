"""
claude_client.py — sends raw scraped text to Claude API,
gets back structured tearsheet JSON.
"""

import os
import json
import logging
import re
import httpx

log = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
MODEL = "claude-sonnet-4-6"


SYSTEM_PROMPT = """You are a financial data extraction assistant for a Vietnamese investment research analyst.
You receive raw text scraped from financial data platforms (FiinGate, Vietstock) and must extract
clean structured data. Be precise. Convert VND figures to USD using the rate provided.
Return ONLY valid JSON — no markdown fences, no explanation."""


def build_user_prompt(company_name: str, raw_text: str, ctype: str, source: str, usd_vnd: float) -> str:
    # Truncate raw text to avoid token overflow
    truncated = raw_text[:12000] if len(raw_text) > 12000 else raw_text

    return f"""Extract a financial tearsheet for "{company_name}" ({ctype} company).
Source platform: {source}. USD/VND conversion rate: {usd_vnd}.

Raw scraped data:
{truncated}

Return a JSON object with this exact structure (use null for missing values):
{{
  "name": "Full legal company name",
  "ticker": "TICKER or null",
  "type": "{ctype}",
  "source": "{source}",
  "sector": "Sector description",
  "currency": "USDm",
  "usd_vnd_rate": {usd_vnd},
  "overview": "2-3 sentence business description",
  "employees": "number or null",
  "founded": "year or null",
  "address": "address or null",
  "website": "url or null",
  "fiscal_year_end": "e.g. 31-Dec",
  "years": ["FY21", "FY22", "FY23", "FY24", "FY25"],
  "metrics": {{
    "pe_trailing": null,
    "ev_ebitda": null,
    "pbv": null,
    "roe": null,
    "roa": null,
    "div_yield": null,
    "mktcap": null,
    "net_debt_latest": null,
    "contributed_capital": null
  }},
  "income_statement": {{
    "revenue":       [null, null, null, null, null],
    "rev_growth_pct":[null, null, null, null, null],
    "gross_profit":  [null, null, null, null, null],
    "gp_margin_pct": [null, null, null, null, null],
    "ebit":          [null, null, null, null, null],
    "ebit_margin_pct":[null, null, null, null, null],
    "ebitda":        [null, null, null, null, null],
    "ebitda_margin_pct":[null, null, null, null, null],
    "pat":           [null, null, null, null, null],
    "pat_margin_pct":[null, null, null, null, null]
  }},
  "balance_sheet": {{
    "total_assets":  [null, null, null, null, null],
    "total_equity":  [null, null, null, null, null],
    "total_debt":    [null, null, null, null, null],
    "cash":          [null, null, null, null, null],
    "net_debt":      [null, null, null, null, null]
  }},
  "cash_flow": {{
    "operating_cf":  [null, null, null, null, null],
    "capex":         [null, null, null, null, null],
    "free_cf":       [null, null, null, null, null]
  }},
  "data_note": "brief note on data quality, audit status, or completeness"
}}

Rules:
- All monetary values in USDm (divide VNDm by {usd_vnd})
- Round to 1 decimal place
- Negative numbers as negative floats e.g. -3.1
- Percentages as strings e.g. "25.7%" or null
- years array must match the data columns you find (use actual fiscal years)
- If fewer than 5 years available, use null for missing positions
- Return ONLY the JSON object"""


async def structure_data(
    company_name: str,
    raw_text: str,
    ctype: str,
    source: str,
    usd_vnd: float
) -> dict:
    """Call Claude API and parse the structured tearsheet JSON."""

    prompt = build_user_prompt(company_name, raw_text, ctype, source, usd_vnd)

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": MODEL,
        "max_tokens": 2000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}]
    }

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload
        )
        r.raise_for_status()
        data = r.json()

    text = data["content"][0]["text"].strip()

    # Strip any accidental markdown fences
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    text = text.strip()

    try:
        structured = json.loads(text)
    except json.JSONDecodeError as e:
        log.error(f"Claude returned invalid JSON: {e}\nRaw: {text[:500]}")
        raise ValueError(f"Claude returned invalid JSON: {e}")

    log.info(f"Structured data for '{company_name}': {list(structured.keys())}")
    return structured
