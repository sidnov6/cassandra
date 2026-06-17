"""Render a filing's forensic dossier to a polished, audit-grade PDF (reportlab).

The brief: "tell the exact thing this company is doing." So the document leads with the
ranked concerns — each with its evidence and the good-faith counter-argument — then the
forensic snapshot, the nearest historical analogue, and the synthesis memo. Probabilistic
language throughout; it is a triage instrument, not a verdict.
"""
from __future__ import annotations

import io
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (Flowable, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

INK = colors.HexColor("#1b1813")
MUTED = colors.HexColor("#6c675e")
GOLD = colors.HexColor("#a9801f")
LACQUER = colors.HexColor("#14120d")
CLAY = colors.HexColor("#b5472f")
AMBER = colors.HexColor("#b98328")
PATINA = colors.HexColor("#3f8c78")
HAIR = colors.HexColor("#d9d4c8")


def _band_color(band: str):
    return {"ELEVATED": CLAY, "WATCH": AMBER, "LOW": PATINA}.get(band, MUTED)


class _Header(Flowable):
    """The dark watchdog masthead band."""
    def __init__(self, width, entity, sub, score, band):
        super().__init__()
        self.width, self.height = width, 86
        self.entity, self.sub, self.score, self.band = entity, sub, score, band

    def draw(self):
        c = self.canv
        c.setFillColor(LACQUER)
        c.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        c.setFillColor(GOLD)
        c.rect(0, 0, self.width, 2.2, fill=1, stroke=0)
        # wordmark
        c.setFillColor(GOLD); c.setFont("Helvetica-Bold", 8)
        c.drawString(16, self.height - 20, "Λ  C A S S A N D R A")
        c.setFillColor(MUTED); c.setFont("Helvetica", 6.5)
        c.drawString(16, self.height - 31, "FORENSIC INTELLIGENCE  ·  POINT-IN-TIME MANIPULATION TRIAGE")
        # entity
        c.setFillColor(colors.HexColor("#ece7dd")); c.setFont("Helvetica-Bold", 15)
        c.drawString(16, 30, self.entity[:54])
        c.setFillColor(MUTED); c.setFont("Helvetica", 7.5)
        c.drawString(16, 16, self.sub)
        # score chip (right)
        bc = _band_color(self.band)
        c.setFillColor(bc)
        c.roundRect(self.width - 150, 18, 134, 50, 4, fill=1, stroke=0)
        c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 24)
        c.drawRightString(self.width - 60, 33, f"{self.score:.2f}")
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(self.width - 24, 50, self.band)
        c.setFont("Helvetica", 6)
        c.drawRightString(self.width - 24, 24, "CALIBRATED RISK")


def _styles():
    ss = getSampleStyleSheet()
    base = ss["Normal"]
    return {
        "eyebrow": ParagraphStyle("eyebrow", parent=base, fontName="Helvetica-Bold",
                                  fontSize=7.5, textColor=GOLD, spaceAfter=4, leading=10,
                                  alignment=TA_LEFT),
        "h": ParagraphStyle("h", parent=base, fontName="Helvetica-Bold", fontSize=11,
                            textColor=INK, spaceBefore=10, spaceAfter=5),
        "body": ParagraphStyle("body", parent=base, fontName="Helvetica", fontSize=9,
                              textColor=INK, leading=13, spaceAfter=4),
        "small": ParagraphStyle("small", parent=base, fontName="Helvetica", fontSize=7.5,
                               textColor=MUTED, leading=10),
        "concern": ParagraphStyle("concern", parent=base, fontName="Helvetica-Bold",
                                  fontSize=9.5, textColor=INK, spaceAfter=2),
        "rebut": ParagraphStyle("rebut", parent=base, fontName="Helvetica-Oblique",
                               fontSize=8.5, textColor=MUTED, leading=11, spaceAfter=2,
                               leftIndent=10),
        "ref": ParagraphStyle("ref", parent=base, fontName="Courier", fontSize=6.8,
                             textColor=MUTED, spaceAfter=8),
    }


def _fmt(v, d=2):
    try:
        return f"{float(v):.{d}f}"
    except (TypeError, ValueError):
        return "—"


def build_dossier_pdf(ctx, dossier: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, topMargin=0.5 * inch,
                            bottomMargin=0.55 * inch, leftMargin=0.7 * inch,
                            rightMargin=0.7 * inch, title=f"CASSANDRA Dossier — {ctx.panel.entity}")
    st = _styles()
    W = doc.width
    f = ctx.forensic.features
    score = ctx.score
    g = []

    sub = (f"CIK {ctx.ref.cik}   ·   FY{ctx.forensic.fiscal_year}   ·   accession "
           f"{ctx.accession or '—'}   ·   point-in-time {ctx.target_fye}")
    g.append(_Header(W, ctx.panel.entity, sub, score.calibrated_p, score.band))
    g.append(Spacer(1, 14))

    g.append(Paragraph("HEADLINE ASSESSMENT", st["eyebrow"]))
    conf = "high" if score.confidence >= 0.75 else ("moderate" if score.confidence >= 0.6 else "limited")
    g.append(Paragraph(
        f"Calibrated manipulation risk <b>{score.calibrated_p:.2f}</b> "
        f"(<b>{score.band}</b>, confidence {conf}). This is a triage flag, not a determination "
        "of fraud; every concern below is probabilistic and evidence-anchored.", st["body"]))
    g.append(Spacer(1, 6))

    # ---- concerns: "what this company is doing" ----
    rb = {r["flag_id"]: r for r in dossier.get("rebuttals", [])}
    flags = sorted(dossier.get("flags", []),
                   key=lambda fl: -(rb.get(fl["flag_id"], {}).get("residual_concern", 0)))
    g.append(Paragraph("WHAT THE FILING SHOWS — RANKED CONCERNS", st["eyebrow"]))
    if not flags:
        g.append(Paragraph("No specialist raised a grounded concern at the configured "
                           "thresholds. Forensic ratios, accrual quality and disclosure "
                           "language are within normal ranges for this filing.", st["body"]))
    for i, fl in enumerate(flags, 1):
        r = rb.get(fl["flag_id"], {})
        res = r.get("residual_concern", 0)
        g.append(Paragraph(f'{i}. {fl["title"]} '
                           f'<font color="#b5472f">[residual {res:.2f}]</font>', st["concern"]))
        g.append(Paragraph(f'<font color="#6c675e">{fl["agent"]} · severity '
                           f'{_fmt(fl.get("severity"))} · confidence {_fmt(fl.get("confidence"))}</font> '
                           + fl.get("rationale", ""), st["body"]))
        if r.get("benign_explanation"):
            g.append(Paragraph("Challenger (benign reading): " + r["benign_explanation"], st["rebut"]))
        g.append(Paragraph("evidence:  " + "   ".join(fl.get("evidence_refs", [])), st["ref"]))

    # ---- forensic snapshot ----
    g.append(Paragraph("FORENSIC SNAPSHOT", st["eyebrow"]))
    rows = [["Signal", "Value", "Reading"],
            ["Beneish M-Score", _fmt(f.get("beneish_m")),
             "> −1.78 likely manipulator" if (f.get("beneish_m") or -9) > -1.78 else "below threshold"],
            ["Dechow F-Score", _fmt(f.get("dechow_f")),
             "> 1 above-average risk" if (f.get("dechow_f") or 0) > 1 else "near/below normal"],
            ["Altman Z-Score", _fmt(f.get("altman_z")), "distress < 1.81" if (f.get("altman_z") or 9) < 1.81 else "—"],
            ["Accruals / Total Assets", _fmt(f.get("accruals_to_ta"), 3), "earnings vs cash"],
            ["CFO / Net Income", _fmt(f.get("cfo_ni_ratio")),
             "cash-vs-earnings divergence" if (f.get("cfo_ni_ratio") or 9) < 0.8 else "—"],
            ["DSO YoY change (days)", _fmt(f.get("dso_yoy_delta"), 1), "receivables trend"]]
    t = Table(rows, colWidths=[1.9 * inch, 1.0 * inch, W - 2.9 * inch])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
        ("FONT", (1, 1), (1, -1), "Courier", 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), GOLD),
        ("TEXTCOLOR", (2, 1), (2, -1), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, GOLD),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, HAIR),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    g.append(t)
    g.append(Spacer(1, 8))

    # ---- analogue ----
    an = dossier.get("analogues", [])
    if an:
        a = an[0]
        g.append(Paragraph("NEAREST HISTORICAL ANALOGUE", st["eyebrow"]))
        note = "" if a.get("in_distribution") else " (out-of-distribution — qualitative pattern analogue)"
        g.append(Paragraph(f'Pattern resembles <b>{a["case_name"]}</b> '
                           f'(similarity {_fmt(a.get("similarity"))}){note} — shared pattern: '
                           f'{a.get("shared_pattern", "")}.', st["body"]))

    # ---- memo ----
    if dossier.get("memo"):
        g.append(Paragraph("SYNTHESIS MEMO", st["eyebrow"]))
        for line in dossier["memo"].split("\n"):
            if line.strip():
                g.append(Paragraph(line.replace("&", "&amp;").replace("<", "&lt;"), st["small"]))

    g.append(Spacer(1, 10))
    g.append(Paragraph(
        f"Generated by CASSANDRA · agent mode: {dossier.get('llm_mode','deterministic')} · "
        f"reproducible from (model, data snapshot, accession {ctx.accession}). "
        "Triage instrument — probabilistic, evidence-anchored, not a legal determination of fraud.",
        st["small"]))

    doc.build(g)
    return buf.getvalue()
