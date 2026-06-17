"""Text features (blueprint §5.2) — the modern differentiator, runnable without a GPU.

The thin slice uses the Loughran-McDonald finance sentiment approach (a curated subset of
the LM master dictionary is embedded; production swaps in the full ~4k-word lists and/or a
FinBERT embedding tower). We compute:

  * LM sentiment        — negativity / uncertainty / litigious / weak-modal density
  * readability (Fog)   — obfuscation correlates with trouble
  * hedging score       — density of hedge words in the narrative
  * YoY language shift   — cosine distance between this year's and last year's MD&A
  * narrative-numbers divergence — does management's optimism diverge from the fundamentals?

Section extraction is heuristic (Item 7 MD&A, Item 1A Risk Factors) with a full-document
fallback. Character offsets are preserved so the UI can deep-link to source text.
"""
from __future__ import annotations

import dataclasses
import math
import re
from typing import Optional

# --- Curated Loughran-McDonald subsets (production: full LM master dictionary) ----------
LM_NEGATIVE = {
    "loss", "losses", "decline", "declines", "declined", "declining", "adverse", "adversely",
    "negative", "negatively", "deficit", "deficits", "weak", "weakness", "weaknesses",
    "deteriorate", "deterioration", "default", "defaults", "litigation", "investigation",
    "investigations", "restate", "restated", "restatement", "impairment", "impairments",
    "shortfall", "shortfalls", "downturn", "doubt", "doubts", "concern", "concerns",
    "fail", "failed", "failure", "failures", "breach", "breaches", "penalty", "penalties",
    "fraud", "misstatement", "delinquent", "discontinued", "writedown", "writeoff",
    "lawsuit", "lawsuits", "termination", "terminated", "unfavorable", "severe", "damages",
}
LM_UNCERTAINTY = {
    "may", "could", "might", "possible", "possibly", "uncertain", "uncertainty",
    "uncertainties", "approximate", "approximately", "assume", "assumed", "assumption",
    "assumptions", "believe", "believes", "estimate", "estimates", "estimated", "depend",
    "depends", "depending", "fluctuate", "fluctuates", "risk", "risks", "variable",
    "contingent", "contingency", "exposure", "indefinite", "predict", "unpredictable",
    "tentative", "pending", "anticipate", "anticipates",
}
LM_LITIGIOUS = {
    "litigation", "plaintiff", "plaintiffs", "defendant", "defendants", "court", "lawsuit",
    "lawsuits", "settlement", "settlements", "subpoena", "claimant", "damages", "indemnify",
    "indemnification", "appeal", "appeals", "testimony", "judicial", "statute", "regulatory",
    "enforcement", "allegation", "allegations", "sue", "sued",
}
LM_MODAL_WEAK = {
    "may", "could", "might", "possibly", "perhaps", "conceivably", "depending", "appears",
    "seems", "suggest", "suggests", "somewhat",
}
HEDGE_WORDS = {
    "generally", "typically", "usually", "largely", "substantially", "essentially",
    "relatively", "approximately", "broadly", "in general", "to some extent", "for the most part",
    "we believe", "in our opinion", "management believes", "tend to", "more or less",
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]+")
_SENT_RE = re.compile(r"[.!?]+")
_COMPLEX_RE = re.compile(r"[aeiouy]+", re.I)


def strip_html(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "table"]):
            tag.decompose()
        text = soup.get_text(" ")
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_sections(text: str) -> dict[str, tuple[str, int, int]]:
    """Best-effort Item-7 (MD&A) and Item-1A (Risk Factors) extraction with offsets."""
    out: dict[str, tuple[str, int, int]] = {}
    patterns = {
        "MDNA": (r"item[\s ]*7[\.\s].{0,40}?discussion", r"item[\s ]*7a|item[\s ]*8"),
        "RISK": (r"item[\s ]*1a[\.\s].{0,40}?risk", r"item[\s ]*1b|item[\s ]*2"),
    }
    low = text.lower()
    for name, (start_pat, end_pat) in patterns.items():
        starts = [m.start() for m in re.finditer(start_pat, low)]
        if not starts:
            continue
        s = starts[-1]  # the body occurrence, not the TOC entry, tends to be last
        ends = [m.start() for m in re.finditer(end_pat, low) if m.start() > s]
        e = ends[0] if ends else min(len(text), s + 120_000)
        if e - s > 400:
            out[name] = (text[s:e], s, e)
    return out


def _tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def _syllables(word: str) -> int:
    return max(1, len(_COMPLEX_RE.findall(word)))


def fog_index(text: str) -> Optional[float]:
    words = _WORD_RE.findall(text)
    if len(words) < 50:
        return None
    sentences = max(1, len([s for s in _SENT_RE.split(text) if s.strip()]))
    complex_words = sum(1 for w in words if _syllables(w) >= 3)
    wps = len(words) / sentences
    pct_complex = 100 * complex_words / len(words)
    return 0.4 * (wps + pct_complex)


def lm_density(tokens: list[str], lexicon: set[str]) -> float:
    if not tokens:
        return 0.0
    hits = sum(1 for t in tokens if t in lexicon)
    return hits / len(tokens)


@dataclasses.dataclass
class TextReport:
    available: bool
    sections_found: list[str]
    lm_negativity: Optional[float] = None
    lm_uncertainty: Optional[float] = None
    lm_litigious: Optional[float] = None
    lm_modal_weak: Optional[float] = None
    fog_index: Optional[float] = None
    hedging_score: Optional[float] = None
    yoy_language_shift: Optional[float] = None
    narrative_numbers_divergence: Optional[float] = None
    mdna_offsets: Optional[tuple[int, int]] = None
    note: str = ""

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["mdna_offsets"] = list(self.mdna_offsets) if self.mdna_offsets else None
        return d


def hedging_score(text: str) -> float:
    low = text.lower()
    n_words = max(1, len(_WORD_RE.findall(text)))
    hits = sum(low.count(h) for h in HEDGE_WORDS)
    return min(1.0, hits / n_words * 50)  # scaled to a readable 0..1


def yoy_language_shift(text_t: str, text_tm1: str) -> Optional[float]:
    if not text_t or not text_tm1:
        return None
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        v = TfidfVectorizer(max_features=4000, stop_words="english")
        m = v.fit_transform([text_tm1, text_t])
        sim = float(cosine_similarity(m[0], m[1])[0][0])
        return 1.0 - sim  # distance; large => sudden rewrite
    except Exception:
        return None


def analyze_text(primary_html: str,
                 prior_html: Optional[str] = None,
                 fundamentals_perf: Optional[float] = None) -> TextReport:
    """Compute the text feature block for one filing.

    `fundamentals_perf` is a signed performance signal in roughly [-1, 1] derived from the
    numbers (e.g. revenue growth & CFO/NI health). The narrative-numbers divergence is the
    gap between management's textual optimism and that fundamentals signal.
    """
    if not primary_html or len(primary_html) < 500:
        return TextReport(available=False, sections_found=[], note="No filing text available.")

    text = strip_html(primary_html)
    sections = extract_sections(text)
    mdna = sections.get("MDNA")
    narrative = mdna[0] if mdna else text[:200_000]
    tokens = _tokens(narrative)

    neg = lm_density(tokens, LM_NEGATIVE)
    unc = lm_density(tokens, LM_UNCERTAINTY)
    lit = lm_density(tokens, LM_LITIGIOUS)
    weak = lm_density(tokens, LM_MODAL_WEAK)
    fog = fog_index(narrative)
    hedge = hedging_score(narrative)

    shift = None
    if prior_html:
        prior_text = strip_html(prior_html)
        prior_sections = extract_sections(prior_text)
        prior_mdna = prior_sections.get("MDNA")
        shift = yoy_language_shift(narrative, prior_mdna[0] if prior_mdna else prior_text[:200_000])

    # Tone = deviation of narrative negativity from the typical 10-K level (~1.3%, per
    # Loughran-McDonald). Positive => rosier than typical; negative => gloomier. This is
    # centered (not saturating) so a normal filing reads ~0, unlike an absolute optimism score.
    TYPICAL_NEG = 0.013
    tone = max(-1.0, min(1.0, (TYPICAL_NEG - neg) / TYPICAL_NEG))
    divergence = None
    if fundamentals_perf is not None:
        # The fraud-relevant gap: rosy tone while the numbers are weak/declining. Only the
        # one-sided "optimism exceeds fundamentals" surplus counts, so a healthy firm whose
        # upbeat tone is *justified* by strong fundamentals reads ~0, not a false positive.
        divergence = max(0.0, min(1.0, tone - max(0.0, fundamentals_perf)))

    return TextReport(
        available=True,
        sections_found=list(sections.keys()),
        lm_negativity=neg, lm_uncertainty=unc, lm_litigious=lit, lm_modal_weak=weak,
        fog_index=fog, hedging_score=hedge, yoy_language_shift=shift,
        narrative_numbers_divergence=divergence,
        mdna_offsets=(mdna[1], mdna[2]) if mdna else None,
        note="MD&A section located." if mdna else "MD&A not isolated; used document head.",
    )
