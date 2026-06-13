"""
pdf_gen.py — generates a clean tearsheet PDF from structured data dict.
Uses ReportLab Platypus for layout.
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
from typing import Optional

# ── Colour palette ────────────────────────────────────────────────
DARK_NAVY   = colors.HexColor("#1a1a2e")
ACCENT_RED  = colors.HexColor("#E24B4A")
ACCENT_TEAL = colors.HexColor("#5bc8a8")
MID_GRAY    = colors.HexColor("#888780")
LIGHT_GRAY  = colors.HexColor("#f1efe8")
NEG_RED     = colors.HexColor("#c0392b")
POS_GREEN   = colors.HexColor("#27ae60")
WHITE       = colors.white
BLACK       = colors.HexColor("#1a1a1a")
ROW_ALT     = colors.HexColor("#f8f7f5")

PAGE_W, PAGE_H = A4
MARGIN = 16 * mm


# ── Styles ────────────────────────────────────────────────────────
def make_styles():
    return {
        "company": ParagraphStyle("company", fontName="Helvetica-Bold",
                                  fontSize=18, textColor=WHITE, leading=22),
        "meta":    ParagraphStyle("meta", fontName="Helvetica",
                                  fontSize=8, textColor=colors.HexColor("#9fa3b1"), leading=12),
        "section": ParagraphStyle("section", fontName="Helvetica-Bold",
                                  fontSize=7.5, textColor=ACCENT_RED,
                                  spaceBefore=8, spaceAfter=2),
        "body":    ParagraphStyle("body", fontName="Helvetica",
                                  fontSize=8.5, textColor=BLACK, leading=13),
        "overview":ParagraphStyle("overview", fontName="Helvetica",
                                  fontSize=8, textColor=colors.HexColor("#444441"),
                                  leading=12, spaceAfter=4),
        "note":    ParagraphStyle("note", fontName="Helvetica-Oblique",
                                  fontSize=7, textColor=MID_GRAY, leading=10),
        "footer":  ParagraphStyle("footer", fontName="Helvetica",
                                  fontSize=6.5, textColor=MID_GRAY,
                                  alignment=TA_CENTER),
    }


# ── Helpers ───────────────────────────────────────────────────────
def fmt(val, is_pct=False, is_growth=False) -> str:
    """Format a value for display."""
    if val is None:
        return "—"
    if isinstance(val, str):
        return val
    if is_pct:
        return f"{val:.1f}%"
    return f"{val:,.1f}"


def color_val(val) -> colors.Color:
    """Return green/red/black depending on sign."""
    if val is None or isinstance(val, str):
        return BLACK
    return POS_GREEN if float(val) > 0 else (NEG_RED if float(val) < 0 else BLACK)


def section_header(text: str, styles: dict):
    return [
        Spacer(1, 3 * mm),
        HRFlowable(width="100%", thickness=1.2, color=ACCENT_RED, spaceAfter=2),
        Paragraph(text.upper(), styles["section"]),
    ]


# ── Top header band ───────────────────────────────────────────────
def build_header_table(d: dict, styles: dict):
    name = d.get("name", "—")
    ticker = d.get("ticker") or ""
    ctype = d.get("type", "private").upper()
    source = d.get("source", "—")
    sector = d.get("sector", "—")
    currency = d.get("currency", "USDm")
    rate = d.get("usd_vnd_rate", 26500)
    employees = d.get("employees")
    founded = d.get("founded")
    website = d.get("website", "")
    address = d.get("address", "")

    meta_parts = [sector]
    if ticker:
        meta_parts.append(ticker)
    meta_parts += [ctype, source]
    meta_line1 = "  ·  ".join(filter(None, meta_parts))

    meta_parts2 = [f"USD/VND {int(rate):,}", currency]
    if employees:
        meta_parts2.append(f"{employees} employees")
    if founded:
        meta_parts2.append(f"Est. {founded}")
    meta_line2 = "  ·  ".join(filter(None, meta_parts2))

    meta_parts3 = []
    if website:
        meta_parts3.append(website)
    if address:
        meta_parts3.append(address[:60])
    meta_line3 = "  ·  ".join(filter(None, meta_parts3))

    header_content = [
        [Paragraph(name, styles["company"])],
        [Paragraph(meta_line1, styles["meta"])],
        [Paragraph(meta_line2, styles["meta"])],
    ]
    if meta_line3:
        header_content.append([Paragraph(meta_line3, styles["meta"])])

    tbl = Table(header_content, colWidths=[PAGE_W - 2 * MARGIN])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), DARK_NAVY),
        ("TOPPADDING",    (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [DARK_NAVY]),
    ]))
    return tbl


# ── Key metrics grid ──────────────────────────────────────────────
def build_metrics_table(d: dict, styles: dict):
    m = d.get("metrics", {})
    ys = d.get("years", [])
    is_data = d.get("income_statement", {})
    bs_data = d.get("balance_sheet", {})

    # Latest year revenue
    rev = is_data.get("revenue", [])
    latest_rev = next((v for v in reversed(rev) if v is not None), None)

    items = [
        ("Market cap (USDm)", m.get("mktcap")),
        ("Revenue latest (USDm)", latest_rev),
        ("P/E (trailing)", m.get("pe_trailing")),
        ("EV/EBITDA", m.get("ev_ebitda")),
        ("P/BV", m.get("pbv")),
        ("ROE", m.get("roe")),
        ("ROA", m.get("roa")),
        ("Div yield", m.get("div_yield")),
        ("Net debt (USDm)", m.get("net_debt_latest")),
        ("Contributed cap (USDm)", m.get("contributed_capital")),
    ]
    items = [(k, v) for k, v in items if v is not None]

    rows = []
    for i in range(0, len(items), 2):
        left = items[i]
        right = items[i + 1] if i + 1 < len(items) else ("", "")
        rows.append([
            Paragraph(left[0], styles["note"]),
            Paragraph(fmt(left[1]), ParagraphStyle("mv", fontName="Helvetica-Bold",
                                                    fontSize=8.5, textColor=BLACK)),
            Paragraph(right[0], styles["note"]) if right[0] else Paragraph("", styles["note"]),
            Paragraph(fmt(right[1]), ParagraphStyle("mv", fontName="Helvetica-Bold",
                                                     fontSize=8.5, textColor=BLACK)) if right[1] else Paragraph("", styles["note"]),
        ])

    if not rows:
        return None

    col_w = (PAGE_W - 2 * MARGIN) / 4
    tbl = Table(rows, colWidths=[col_w * 1.4, col_w * 0.6, col_w * 1.4, col_w * 0.6])
    tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#dddddd")),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE, ROW_ALT]),
    ]))
    return tbl


# ── Financial statement table ─────────────────────────────────────
def build_fin_table(rows_def: list, data: dict, years: list, styles: dict, highlight_margins=True):
    """
    rows_def: list of (display_label, data_key, is_margin)
    data: dict of key -> [v0, v1, ...]
    """
    avail_years = [y for y in years]
    n = len(avail_years)

    # Header row
    col_w = (PAGE_W - 2 * MARGIN)
    label_w = col_w * 0.28
    yr_w = (col_w - label_w) / max(n, 1)

    header = [Paragraph("Metric", styles["note"])] + \
             [Paragraph(y, ParagraphStyle("yh", fontName="Helvetica-Bold",
                                          fontSize=7.5, textColor=WHITE,
                                          alignment=TA_RIGHT)) for y in avail_years]

    table_data = [header]
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK_NAVY),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (0, -1), 4),
        ("RIGHTPADDING", (1, 0), (-1, -1), 4),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, ROW_ALT]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.2, colors.HexColor("#e0e0e0")),
    ]

    row_idx = 1
    for label, key, is_margin in rows_def:
        vals = data.get(key, [None] * n)
        # Pad/trim to n
        vals = list(vals) + [None] * n
        vals = vals[:n]

        if is_margin:
            label_para = Paragraph(
                f"<i>{label}</i>",
                ParagraphStyle("ml", fontName="Helvetica-Oblique",
                               fontSize=7.5, textColor=MID_GRAY, leftIndent=8)
            )
        else:
            label_para = Paragraph(label, ParagraphStyle("ml", fontName="Helvetica-Bold",
                                                          fontSize=8, textColor=BLACK))

        row = [label_para]
        for v in vals:
            txt = fmt(v, is_pct=is_margin)
            if is_margin:
                c = NEG_RED if (v is not None and not isinstance(v, str) and float(str(v).replace("%","")) < 0) else \
                    (MID_GRAY if v is None else colors.HexColor("#3B6D11"))
                para = Paragraph(txt, ParagraphStyle("mv", fontName="Helvetica-Oblique",
                                                      fontSize=7.5, textColor=c, alignment=TA_RIGHT))
            else:
                c = color_val(v)
                para = Paragraph(txt, ParagraphStyle("mv", fontName="Helvetica",
                                                      fontSize=8, textColor=c, alignment=TA_RIGHT))
            row.append(para)

        table_data.append(row)
        if is_margin:
            style_cmds.append(("BACKGROUND", (0, row_idx), (-1, row_idx), colors.HexColor("#fafaf8")))
        row_idx += 1

    colWidths = [label_w] + [yr_w] * n
    tbl = Table(table_data, colWidths=colWidths)
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


# ── Main builder ──────────────────────────────────────────────────
def build_pdf(d: dict, output_path: str):
    styles = make_styles()
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
        title=f"{d.get('name', 'Company')} Tearsheet",
        author="Tearsheet Bot"
    )

    story = []
    years = d.get("years", [])
    n = len(years)

    # ── Header ────────────────────────────────────────────────────
    story.append(build_header_table(d, styles))
    story.append(Spacer(1, 3 * mm))

    # ── Overview ──────────────────────────────────────────────────
    overview = d.get("overview", "")
    if overview:
        story += section_header("Business Overview", styles)
        story.append(Paragraph(overview, styles["overview"]))

    # ── Key Metrics ───────────────────────────────────────────────
    metrics_tbl = build_metrics_table(d, styles)
    if metrics_tbl:
        story += section_header("Key Metrics", styles)
        story.append(metrics_tbl)

    # ── Income Statement ──────────────────────────────────────────
    is_data = d.get("income_statement", {})
    if any(v for v in is_data.values() if any(x is not None for x in (v or []))):
        story += section_header(f"Income Statement (USDm)", styles)
        is_rows = [
            ("Revenue",         "revenue",          False),
            ("Rev growth %",    "rev_growth_pct",   True),
            ("Gross profit",    "gross_profit",      False),
            ("GP margin %",     "gp_margin_pct",     True),
            ("EBIT",            "ebit",              False),
            ("EBIT margin %",   "ebit_margin_pct",   True),
            ("EBITDA",          "ebitda",            False),
            ("EBITDA margin %", "ebitda_margin_pct", True),
            ("PAT",             "pat",               False),
            ("PAT margin %",    "pat_margin_pct",    True),
        ]
        story.append(KeepTogether(build_fin_table(is_rows, is_data, years, styles)))

    # ── Balance Sheet (high-level only) ───────────────────────────
    bs_data = d.get("balance_sheet", {})
    if any(v for v in bs_data.values() if any(x is not None for x in (v or []))):
        story += section_header("Balance Sheet — Key Lines (USDm)", styles)
        bs_rows = [
            ("Total assets",  "total_assets", False),
            ("Total equity",  "total_equity", False),
            ("Total debt",    "total_debt",   False),
            ("Cash",          "cash",         False),
            ("Net debt",      "net_debt",     False),
        ]
        story.append(KeepTogether(build_fin_table(bs_rows, bs_data, years, styles)))

    # ── Cash Flow ─────────────────────────────────────────────────
    cf_data = d.get("cash_flow", {})
    if any(v for v in cf_data.values() if any(x is not None for x in (v or []))):
        story += section_header("Cash Flow (USDm)", styles)
        cf_rows = [
            ("Operating CF", "operating_cf", False),
            ("Capex",        "capex",        False),
            ("Free CF",      "free_cf",      False),
        ]
        story.append(KeepTogether(build_fin_table(cf_rows, cf_data, years, styles)))

    # ── Data note ─────────────────────────────────────────────────
    note = d.get("data_note", "")
    if note:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(f"Note: {note}", styles["note"]))

    # ── Footer ────────────────────────────────────────────────────
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=0.3, color=MID_GRAY))
    story.append(Spacer(1, 1 * mm))
    footer_txt = (
        f"Generated {date.today().strftime('%d %b %Y')}  ·  "
        f"Source: {d.get('source', '—')}  ·  "
        f"USD/VND {int(d.get('usd_vnd_rate', 26500)):,}  ·  "
        "Unaudited unless stated  ·  For internal research use only"
    )
    story.append(Paragraph(footer_txt, styles["footer"]))

    doc.build(story)
