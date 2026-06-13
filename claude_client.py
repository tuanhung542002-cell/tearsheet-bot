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

SYSTEM = """You are a financial data extraction assistant for a Vietnamese investment research analyst.
Extract ALL available data from the raw text. Fill in as many fields as possible — leave null only if the
data is genuinely absent. Convert all VND figures to USD using the rate provided (divide VNDm by the rate).
Return ONLY valid JSON with no markdown fences."""


def prompt(company_name, raw_text, ctype, source, usd_vnd):
    trunc = raw_text[:14000] if len(raw_text) > 14000 else raw_text
    return f"""Extract a complete financial tearsheet for "{company_name}" ({ctype} company).
Source: {source}. USD/VND rate: {usd_vnd}.

Raw data:
{trunc}

Return JSON with this EXACT structure. Fill every field you can find. Use null only if truly absent.
All monetary values in USDm (VNDm ÷ {usd_vnd}), rounded to 1 decimal.
Percentages as strings e.g. "25.7%" — NOT as decimals.
Negatives as negative floats e.g. -3.1.

{{
  "name": "Full legal company name",
  "ticker": "TICKER · Exchange or null",
  "type": "{ctype}",
  "source": "{source}",
  "sector": "Sector · Subsector",
  "currency": "USDm",
  "usd_vnd_rate": {usd_vnd},
  "overview": "2-3 sentence business description",
  "employees": "number as string or null",
  "founded": "year as string or null",
  "address": "address or null",
  "website": "url or null",
  "fiscal_year_end": "e.g. 31-Dec",
  "years": ["FY21","FY22","FY23","FY24","FY25"],
  "metrics": {{
    "roe": "latest ROE % as string or null",
    "roa": "latest ROA % as string or null",
    "mktcap": null,
    "pe_trailing": null,
    "ev_ebitda": null,
    "pbv": null,
    "net_debt_latest": null,
    "contributed_capital": null
  }},
  "income_statement": {{
    "revenue":         [null,null,null,null,null],
    "rev_growth_pct":  [null,"69.7%","124.0%","86.5%","70.7%"],
    "gross_profit":    [null,null,null,null,null],
    "gp_margin_pct":   [null,null,"22.5%","23.6%","25.7%"],
    "ebit":            [null,null,null,null,null],
    "ebit_margin_pct": [null,null,null,null,null],
    "ebitda":          [null,null,null,null,null],
    "ebitda_margin_pct":[null,null,null,null,null],
    "pat":             [null,null,null,null,null],
    "pat_margin_pct":  [null,null,null,null,null]
  }},
  "balance_sheet": {{
    "total_assets": [null,null,null,null,null],
    "total_equity": [null,null,null,null,null],
    "total_debt":   [null,null,null,null,null],
    "cash":         [null,null,null,null,null],
    "net_debt":     [null,null,null,null,null]
  }},
  "cash_flow": {{
    "operating_cf": [null,null,null,null,null],
    "capex":        [null,null,null,null,null],
    "free_cf":      [null,null,null,null,null],
    "da":           [null,null,null,null,null]
  }},
  "data_note": "brief note on data quality, audit status, completeness"
}}

CRITICAL INSTRUCTIONS:
1. years array must match the actual fiscal years in the data. Use FY21/FY22/FY23/FY24/FY25 format.
2. Extract D&A (depreciation & amortisation) from cash flow section into cash_flow.da — this is used to compute EBITDA.
3. If EBITDA is not directly stated, leave it null — it will be computed from EBIT + D&A automatically.
4. Fill ALL years you find data for, not just the latest year.
5. rev_growth_pct: compute YoY % if not stated, format as "70.7%", null for first year.
6. For margins, compute from revenue if not stated: GP/Rev, EBIT/Rev, PAT/Rev.
7. Balance sheet: fill all 5 years if data available — do not leave prior years null if data exists.
8. Return ONLY the JSON object, no explanation."""


async def structure_data(company_name, raw_text, ctype, source, usd_vnd):
    p = prompt(company_name, raw_text, ctype, source, usd_vnd)

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": MODEL, "max_tokens": 2000,
                  "system": SYSTEM,
                  "messages": [{"role": "user", "content": p}]}
        )
        r.raise_for_status()

    text = r.json()["content"][0]["text"].strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Try extracting JSON from response
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise ValueError(f"Claude returned invalid JSON: {e}")
