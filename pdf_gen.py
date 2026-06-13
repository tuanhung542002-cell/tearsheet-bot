"""
pdf_gen.py — tearsheet PDF, revised layout:
  - Header band
  - Business overview
  - Income statement with EBITDA + CAGR column
  - Balance sheet (high-level)
  - ROE / ROA
  No key metrics section, no cash flow section.
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from datetime import date

# ── Palette ──────────────────────────────────────────────────────
DARK_NAVY  = colors.HexColor("#1a1a2e")
ACCENT_RED = colors.HexColor("#E24B4A")
MID_GRAY   = colors.HexColor("#888780")
LIGHT_GRAY = colors.HexColor("#f8f7f5")
NEG_RED    = colors.HexColor("#c0392b")
POS_GREEN  = colors.HexColor("#27ae60")
WHITE      = colors.white
BLACK      = colors.HexColor("#1a1a1a")
ROW_ALT    = colors.HexColor("#f4f3f0")
CAGR_BG    = colors.HexColor("#e8f4e8")
CAGR_FG    = colors.HexColor("#1a5c1a")

PAGE_W, PAGE_H = A4
MARGIN = 14 * mm


# ── Styles ────────────────────────────────────────────────────────
def S():
    return {
        "company":  ParagraphStyle("co", fontName="Helvetica-Bold",
                                   fontSize=17, textColor=WHITE, leading=21),
        "meta":     ParagraphStyle("me", fontName="Helvetica",
                                   fontSize=7.5, textColor=colors.HexColor("#9fa3b1"), leading=11),
        "section":  ParagraphStyle("se", fontName="Helvetica-Bold",
                                   fontSize=7, textColor=ACCENT_RED,
                                   spaceBefore=6, spaceAfter=2),
        "overview": ParagraphStyle("ov", fontName="Helvetica",
                                   fontSize=8, textColor=colors.HexColor("#444441"),
                                   leading=12, spaceAfter=3),
        "note":     ParagraphStyle("no", fontName="Helvetica-Oblique",
                                   fontSize=6.5, textColor=MID_GRAY, leading=9),
        "footer":   ParagraphStyle("fo", fontName="Helvetica",
                                   fontSize=6, textColor=MID_GRAY,
                                   alignment=TA_CENTER),
    }


# ── Helpers ───────────────────────────────────────────────────────
def fmtv(val, is_pct=False) -> str:
    if val is None: return "—"
    if isinstance(val, str): return val
    try:
        f = float(val)
        if is_pct: return f"{f:.1f}%"
        return f"{f:,.1f}"
    except: return str(val)

def vcol(val) -> colors.Color:
    if val is None or isinstance(val, str): return BLACK
    try:
        return POS_GREEN if float(val) > 0 else (NEG_RED if float(val) < 0 else BLACK)
    except: return BLACK

def safe_float(v):
    if v is None: return None
    try: return float(v)
    except: return None

def cagr(start, end, years) -> str:
    """Calculate CAGR between start and end over N years."""
    s, e = safe_float(start), safe_float(end)
    if s is None or e is None or s == 0 or years <= 0: return "—"
    if s < 0 or e < 0: return "n/m"
    try:
        r = (e / s) ** (1 / years) - 1
        return f"{r*100:.0f}%"
    except: return "—"

def section_hdr(text, styles):
    return [
        Spacer(1, 3*mm),
        HRFlowable(width="100%", thickness=1.2, color=ACCENT_RED, spaceAfter=2),
        Paragraph(text.upper(), styles["section"]),
    ]


# ── Header ────────────────────────────────────────────────────────
def build_header(d, styles):
    name    = d.get("name", "—")
    ticker  = d.get("ticker") or ""
    ctype   = d.get("type", "private").upper()
    source  = d.get("source", "—")
    sector  = d.get("sector", "—")
    ccy     = d.get("currency", "USDm")
    rate    = d.get("usd_vnd_rate", 26500)
    emp     = d.get("employees", "")
    founded = d.get("founded", "")
    website = d.get("website", "")
    address = d.get("address", "")

    m1 = "  ·  ".join(filter(None, [sector, ticker, ctype, source]))
    m2 = "  ·  ".join(filter(None, [f"USD/VND {int(rate):,}", ccy,
                                     f"{emp} employees" if emp else "",
                                     f"Est. {founded}" if founded else ""]))
    m3 = "  ·  ".join(filter(None, [website, address[:55] if address else ""]))

    rows = [[Paragraph(name, styles["company"])],
            [Paragraph(m1, styles["meta"])],
            [Paragraph(m2, styles["meta"])]]
    if m3:
        rows.append([Paragraph(m3, styles["meta"])])

    t = Table(rows, colWidths=[PAGE_W - 2*MARGIN])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), DARK_NAVY),
        ("TOPPADDING",    (0,0),(-1,0),  10),
        ("BOTTOMPADDING", (0,-1),(-1,-1),10),
        ("LEFTPADDING",   (0,0),(-1,-1),10),
        ("RIGHTPADDING",  (0,0),(-1,-1),10),
    ]))
    return t


# ── Financial table with CAGR column ─────────────────────────────
def build_fin_table(row_defs, data, years, styles, show_cagr=False):
    """
    row_defs: [(label, key, is_margin)]
    data: dict key -> [v0..v4]
    years: list of year labels
    show_cagr: add a CAGR column (first non-null to last non-null)
    """
    n = len(years)
    col_w  = PAGE_W - 2*MARGIN
    lbl_w  = col_w * 0.26
    cagr_w = col_w * 0.09 if show_cagr else 0
    yr_w   = (col_w - lbl_w - cagr_w) / max(n, 1)

    # Header
    hdr_style = ParagraphStyle("yh", fontName="Helvetica-Bold",
                               fontSize=7.5, textColor=WHITE, alignment=TA_RIGHT)
    cagr_hdr  = ParagraphStyle("ch", fontName="Helvetica-Bold",
                               fontSize=7, textColor=CAGR_FG, alignment=TA_RIGHT)
    header = [Paragraph("Metric", ParagraphStyle("mh", fontName="Helvetica-Bold",
                                                  fontSize=7.5, textColor=WHITE))]
    header += [Paragraph(y, hdr_style) for y in years]
    if show_cagr:
        y0 = years[0] if years else ""
        y1 = years[-1] if years else ""
        header.append(Paragraph(f"CAGR\n{y0}–{y1}", cagr_hdr))

    table_data = [header]
    style_cmds = [
        ("BACKGROUND",    (0,0), (-1,0), DARK_NAVY),
        ("FONTSIZE",      (0,0), (-1,-1), 8),
        ("TOPPADDING",    (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING",   (0,0), (0,-1),  4),
        ("RIGHTPADDING",  (1,0), (-1,-1), 4),
        ("ALIGN",         (1,0), (-1,-1), "RIGHT"),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, ROW_ALT]),
        ("LINEBELOW",     (0,0), (-1,-1), 0.2, colors.HexColor("#e0e0e0")),
    ]
    if show_cagr:
        # Highlight CAGR column header
        style_cmds.append(("BACKGROUND", (-1,0), (-1,0), DARK_NAVY))

    row_idx = 1
    for label, key, is_margin in row_defs:
        vals = list(data.get(key, [None]*n)) + [None]*n
        vals = vals[:n]

        # Skip row if entirely empty
        has_data = any(v is not None for v in vals)
        if not has_data:
            row_idx += 1
            continue

        lbl_ps = ParagraphStyle(
            "ml", fontName="Helvetica-Oblique" if is_margin else "Helvetica-Bold",
            fontSize=7.5 if is_margin else 8,
            textColor=MID_GRAY if is_margin else BLACK,
            leftIndent=8 if is_margin else 0
        )
        row = [Paragraph(label, lbl_ps)]

        for v in vals:
            txt = fmtv(v, is_pct=is_margin)
            if is_margin:
                try:
                    num = float(str(v).replace("%","")) if v is not None else None
                    c = NEG_RED if (num is not None and num < 0) else \
                        (MID_GRAY if v is None else colors.HexColor("#2d6a2d"))
                except: c = MID_GRAY
            else:
                c = vcol(v)
            ps = ParagraphStyle("mv", fontName="Helvetica-Oblique" if is_margin else "Helvetica",
                                fontSize=7.5 if is_margin else 8,
                                textColor=c, alignment=TA_RIGHT)
            row.append(Paragraph(txt, ps))

        # CAGR column
        if show_cagr:
            if not is_margin:
                # first non-null to last non-null
                non_null = [(i,v) for i,v in enumerate(vals) if v is not None]
                if len(non_null) >= 2:
                    i0, v0 = non_null[0]
                    i1, v1 = non_null[-1]
                    yr_span = i1 - i0
                    cval = cagr(v0, v1, yr_span) if yr_span > 0 else "—"
                else:
                    cval = "—"
                cps = ParagraphStyle("cv", fontName="Helvetica-Bold",
                                     fontSize=7.5, textColor=CAGR_FG, alignment=TA_RIGHT)
                row.append(Paragraph(cval, cps))
                # Highlight CAGR cell
                style_cmds.append(("BACKGROUND", (-1, row_idx), (-1, row_idx), CAGR_BG))
            else:
                row.append(Paragraph("", ParagraphStyle("empty")))

        table_data.append(row)
        if is_margin:
            style_cmds.append(("BACKGROUND", (0,row_idx),(-1,row_idx),
                                colors.HexColor("#fafaf8")))
        row_idx += 1

    col_widths = [lbl_w] + [yr_w]*n
    if show_cagr:
        col_widths.append(cagr_w)

    t = Table(table_data, colWidths=col_widths)
    t.setStyle(TableStyle(style_cmds))
    return t


# ── Main builder ──────────────────────────────────────────────────
def build_pdf(d: dict, output_path: str):
    styles = S()
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
        title=f"{d.get('name','Company')} Tearsheet",
        author="Tearsheet Bot"
    )

    story = []
    years = d.get("years", [])
    n     = len(years)
    isd   = d.get("income_statement", {})
    bsd   = d.get("balance_sheet", {})
    cfd   = d.get("cash_flow", {})

    # ── Compute EBITDA from EBIT + D&A ───────────────────────────
    ebit_vals = isd.get("ebit", [None]*n)
    # D&A usually lives in cash flow
    da_vals   = cfd.get("da", [None]*n) if cfd else [None]*n

    ebitda_vals = []
    ebitda_m    = []
    rev_vals    = isd.get("revenue", [None]*n)

    for i in range(n):
        ebit = safe_float(ebit_vals[i] if i < len(ebit_vals) else None)
        da   = safe_float(da_vals[i]   if i < len(da_vals)   else None)
        rev  = safe_float(rev_vals[i]  if i < len(rev_vals)  else None)

        if ebit is not None and da is not None:
            eb = round(ebit + da, 1)
            ebitda_vals.append(eb)
            if rev and rev != 0:
                ebitda_m.append(f"{eb/rev*100:.1f}%")
            else:
                ebitda_m.append(None)
        else:
            # Fall back to stored ebitda if available
            stored = isd.get("ebitda", [None]*n)
            eb = safe_float(stored[i] if i < len(stored) else None)
            ebitda_vals.append(eb)
            if eb is not None and rev and rev != 0:
                ebitda_m.append(f"{eb/rev*100:.1f}%")
            else:
                ebitda_m.append(None)

    isd["ebitda_computed"]   = ebitda_vals
    isd["ebitda_m_computed"] = ebitda_m

    # ── Compute ROE / ROA from stored metrics or raw data ─────────
    m = d.get("metrics", {})

    # Header
    story.append(build_header(d, styles))
    story.append(Spacer(1, 3*mm))

    # Overview
    ov = d.get("overview", "")
    if ov:
        story += section_hdr("Business Overview", styles)
        story.append(Paragraph(ov, styles["overview"]))

    # ── Income Statement ──────────────────────────────────────────
    is_rows = [
        ("Revenue",          "revenue",          False),
        ("Rev growth %",     "rev_growth_pct",   True),
        ("Gross profit",     "gross_profit",      False),
        ("GP margin %",      "gp_margin_pct",     True),
        ("EBIT",             "ebit",              False),
        ("EBIT margin %",    "ebit_margin_pct",   True),
        ("EBITDA",           "ebitda_computed",   False),
        ("EBITDA margin %",  "ebitda_m_computed", True),
        ("PAT",              "pat",               False),
        ("PAT margin %",     "pat_margin_pct",    True),
    ]

    has_is = any(
        any(v is not None for v in (isd.get(k) or []))
        for _, k, _ in is_rows
    )
    if has_is:
        story += section_hdr(f"Income Statement (USDm)", styles)
        story.append(KeepTogether(
            build_fin_table(is_rows, isd, years, styles, show_cagr=True)
        ))

    # ── Balance Sheet ─────────────────────────────────────────────
    bs_rows = [
        ("Total assets",  "total_assets", False),
        ("Total equity",  "total_equity", False),
        ("Total debt",    "total_debt",   False),
        ("Cash",          "cash",         False),
        ("Net debt",      "net_debt",     False),
    ]
    has_bs = any(
        any(v is not None for v in (bsd.get(k) or []))
        for _, k, _ in bs_rows
    )
    if has_bs:
        story += section_hdr("Balance Sheet — Key Lines (USDm)", styles)
        story.append(KeepTogether(
            build_fin_table(bs_rows, bsd, years, styles, show_cagr=False)
        ))

    # ── ROE / ROA ─────────────────────────────────────────────────
    # Build per-year ROE = PAT / avg equity, ROA = PAT / avg assets
    pat_vals    = isd.get("pat", [None]*n)
    equity_vals = bsd.get("total_equity", [None]*n)
    asset_vals  = bsd.get("total_assets", [None]*n)

    roe_vals, roa_vals = [], []
    for i in range(n):
        pat = safe_float(pat_vals[i]    if i < len(pat_vals)    else None)
        eq  = safe_float(equity_vals[i] if i < len(equity_vals) else None)
        ast = safe_float(asset_vals[i]  if i < len(asset_vals)  else None)
        # Use average of current and prior year if available
        eq_p  = safe_float(equity_vals[i-1] if i > 0 and i-1 < len(equity_vals) else None)
        ast_p = safe_float(asset_vals[i-1]  if i > 0 and i-1 < len(asset_vals)  else None)

        avg_eq  = (eq + eq_p) / 2 if eq is not None and eq_p is not None else eq
        avg_ast = (ast + ast_p) / 2 if ast is not None and ast_p is not None else ast

        if pat is not None and avg_eq and avg_eq != 0:
            roe_vals.append(f"{pat/avg_eq*100:.1f}%")
        else:
            roe_vals.append(m.get("roe") if i == n-1 else None)

        if pat is not None and avg_ast and avg_ast != 0:
            roa_vals.append(f"{pat/avg_ast*100:.1f}%")
        else:
            roa_vals.append(m.get("roa") if i == n-1 else None)

    has_roe_roa = any(v is not None for v in roe_vals + roa_vals)
    if has_roe_roa:
        story += section_hdr("Returns", styles)
        ret_data = {"roe": roe_vals, "roa": roa_vals}
        ret_rows = [("ROE", "roe", True), ("ROA", "roa", True)]
        story.append(KeepTogether(
            build_fin_table(ret_rows, ret_data, years, styles, show_cagr=False)
        ))

    # ── Data note ─────────────────────────────────────────────────
    note = d.get("data_note", "")
    if note:
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph(f"Note: {note}", styles["note"]))

    # ── Footer ────────────────────────────────────────────────────
    story.append(Spacer(1, 4*mm))
    story.append(HRFlowable(width="100%", thickness=0.3, color=MID_GRAY))
    story.append(Spacer(1, 1*mm))
    story.append(Paragraph(
        f"Generated {date.today().strftime('%d %b %Y')}  ·  "
        f"Source: {d.get('source','—')}  ·  "
        f"USD/VND {int(d.get('usd_vnd_rate',26500)):,}  ·  "
        "Unaudited unless stated  ·  For internal research use only",
        styles["footer"]
    ))

    doc.build(story)
