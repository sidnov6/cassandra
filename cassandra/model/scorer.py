"""Late-fusion risk scorer (blueprint §5.3).

Four modality "towers" each emit a 0..1 risk sub-score; a meta-combiner fuses them into a
single calibrated probability and exposes **per-modality contributions** (the UI donut).

IMPORTANT — honest scope. The production design (blueprint §5.3, §7.4) trains these towers
(LightGBM/RUSBoost tabular, FinBERT text, GNN graph, LSTM temporal) on AAER labels and
calibrates with isotonic/Platt regression on a time-respecting hold-out, proving lift over
the Beneish/Dechow/RUSBoost baselines on the §7 backtest harness. THIS class is the runnable
Phase-0 stand-in: a transparent, monotonic evidence combiner anchored to the published
forensic thresholds. It is defensible (every weight is visible and literature-grounded) and
swaps out for the trained meta-learner without changing the interface the agents/UI consume.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Any, Optional

import numpy as np


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _evidence(value: Optional[float], threshold: float, scale: float,
              higher_is_riskier: bool = True) -> Optional[float]:
    """Map a raw signal to a 0..1 risk evidence via a logistic centered on `threshold`."""
    if value is None or not math.isfinite(value):
        return None
    z = (value - threshold) / scale
    return _logistic(z if higher_is_riskier else -z)


@dataclasses.dataclass
class Signal:
    name: str
    raw: Optional[float]
    evidence: Optional[float]     # 0..1
    modality: str
    weight: float
    note: str = ""


@dataclasses.dataclass
class ModelScore:
    fused_p: float
    calibrated_p: float
    confidence: float                       # 0..1, driven by modality coverage
    towers: dict[str, Optional[float]]      # modality -> sub-score
    contributions: dict[str, float]         # modality -> share of total risk (sums to 1)
    signals: list[Signal]
    band: str

    def to_dict(self) -> dict:
        return {
            "fused_p": round(self.fused_p, 4),
            "calibrated_p": round(self.calibrated_p, 4),
            "confidence": round(self.confidence, 3),
            "band": self.band,
            "towers": {k: (None if v is None else round(v, 4)) for k, v in self.towers.items()},
            "contributions": {k: round(v, 4) for k, v in self.contributions.items()},
            "signals": [
                {"name": s.name, "raw": (None if s.raw is None or not math.isfinite(s.raw)
                                         else round(s.raw, 4)),
                 "evidence": None if s.evidence is None else round(s.evidence, 3),
                 "modality": s.modality, "weight": s.weight, "note": s.note}
                for s in self.signals
            ],
        }


class FusionScorer:
    # Modality weights. The tabular forensic tower is the workhorse and honest SOTA on
    # structured financials (Bao et al. 2020); the thin-slice text tower is a lexical proxy
    # (not the production FinBERT tower) so it corroborates rather than drives.
    MODALITY_WEIGHTS = {"tabular": 0.60, "text": 0.14, "temporal": 0.16, "benford": 0.10}

    def score(self, forensic: dict, text: Optional[dict], series=None) -> ModelScore:
        signals: list[Signal] = []
        f = forensic.get("features", forensic)

        # ---------------- tabular tower (forensic ratios; the workhorse) ----------------
        # Scales are intentionally tight: a clearly-benign value maps near 0 evidence and a
        # clearly-anomalous one near 1, so separation comes from the signals themselves rather
        # than from a fragile final squash.
        signals.append(Signal("Beneish M-Score", f.get("beneish_m"),
            _evidence(f.get("beneish_m"), -1.78, 0.55), "tabular", 0.30,
            "M > −1.78 indicates likely manipulator (Beneish 1999)."))
        signals.append(Signal("Dechow F-Score", f.get("dechow_f"),
            _evidence(f.get("dechow_f"), 1.0, 0.5), "tabular", 0.22,
            "F > 1 is above-average misstatement risk (Dechow et al. 2011)."))
        signals.append(Signal("Accruals / Total Assets", f.get("accruals_to_ta"),
            _evidence(f.get("accruals_to_ta"), 0.045, 0.035), "tabular", 0.16,
            "High positive accruals = earnings outrunning cash (Sloan 1996)."))
        cfo_ni = f.get("cfo_ni_ratio")
        signals.append(Signal("CFO / Net Income", cfo_ni,
            _evidence(cfo_ni, 0.75, 0.30, higher_is_riskier=False), "tabular", 0.16,
            "CFO well below NI (or negative) = cash-vs-earnings divergence."))
        signals.append(Signal("Altman Z-Score", f.get("altman_z"),
            _evidence(f.get("altman_z"), 1.81, 0.9, higher_is_riskier=False), "tabular", 0.08,
            "Distress (<1.81) is corroborating, not a manipulation signal per se."))
        signals.append(Signal("DSO YoY change (days)", f.get("dso_yoy_delta"),
            _evidence(f.get("dso_yoy_delta"), 9.0, 6.0), "tabular", 0.08,
            "Rising days-sales-outstanding can signal premature recognition."))

        # ---------------- benford tower ----------------
        # Threshold set high: filing-level XBRL nonconformity is near-universal, so only a
        # pronounced digit anomaly should contribute risk.
        signals.append(Signal("Benford first-digit MAD", f.get("benford_mad"),
            _evidence(f.get("benford_anomaly"), 0.62, 0.15), "benford", 1.0,
            "Digit-distribution deviation. Down-weighted: filing-level XBRL is a small, "
            "partly-rounded population vs transaction-level data."))

        # ---------------- text tower ----------------
        if text and text.get("available"):
            div = text.get("narrative_numbers_divergence")
            signals.append(Signal("Narrative–numbers divergence", div,
                _evidence(div, 0.45, 0.18), "text", 0.45,
                "Management tone rosier than the fundamentals justify."))
            signals.append(Signal("Disclosure hedging", text.get("hedging_score"),
                _evidence(text.get("hedging_score"), 0.55, 0.15), "text", 0.25,
                "Dense hedging/vagueness in the narrative."))
            signals.append(Signal("Readability (Fog index)", text.get("fog_index"),
                _evidence(text.get("fog_index"), 25.0, 2.5), "text", 0.15,
                "Obfuscation/complexity beyond the already-high 10-K baseline."))
            signals.append(Signal("YoY language shift", text.get("yoy_language_shift"),
                _evidence(text.get("yoy_language_shift"), 0.6, 0.15), "text", 0.15,
                "Sudden rewrite of MD&A vs prior year."))

        # ---------------- temporal tower (escalation trajectory) ----------------
        temporal_ev = self._temporal_escalation(series)
        if temporal_ev is not None:
            signals.append(Signal("Multi-year escalation", temporal_ev["raw"],
                temporal_ev["evidence"], "temporal", 1.0,
                "Accruals/DSO/M-score trending upward across filings (manipulation escalates "
                "before it breaks)."))

        # ---------------- fuse ----------------
        towers: dict[str, Optional[float]] = {}
        for modality in self.MODALITY_WEIGHTS:
            mods = [s for s in signals if s.modality == modality and s.evidence is not None]
            if not mods:
                towers[modality] = None
                continue
            wsum = sum(s.weight for s in mods)
            wmean = sum(s.evidence * s.weight for s in mods) / wsum if wsum else 0.0
            # Forensic red flags are partly disjunctive: a single strong tell is informative
            # and should not be washed out by neutral signals. Blend mean with the peak signal.
            peak = max(s.evidence for s in mods)
            towers[modality] = 0.68 * wmean + 0.32 * peak

        avail = {m: w for m, w in self.MODALITY_WEIGHTS.items() if towers.get(m) is not None}
        wtot = sum(avail.values()) or 1.0
        tower_mean = sum(towers[m] * w for m, w in avail.items()) / wtot
        # Top-level fusion also lets the single strongest modality lift the score (the tabular
        # tower screaming should not be averaged away by quiet text/temporal towers).
        tower_peak = max(towers[m] for m in avail)
        fused = 0.72 * tower_mean + 0.28 * tower_peak

        # Calibration. Separation now lives in the per-signal evidence, so the final squash is
        # gentle. Production replaces it with isotonic/Platt regression fit on AAER labels over
        # a time-respecting hold-out (§7).
        calibrated = _logistic((fused - 0.42) * 5.5)

        contributions = {m: (towers[m] * w / wtot) for m, w in avail.items()}
        csum = sum(contributions.values()) or 1.0
        contributions = {m: v / csum for m, v in contributions.items()}

        # confidence grows with modality coverage
        confidence = min(1.0, 0.45 + 0.16 * len(avail))

        return ModelScore(
            fused_p=fused, calibrated_p=calibrated, confidence=confidence,
            towers=towers, contributions=contributions, signals=signals,
            band=self._band(calibrated),
        )

    @staticmethod
    def _temporal_escalation(series) -> Optional[dict]:
        if series is None or len(series) < 3:
            return None
        import pandas as pd
        def slope(col):
            s = series[col].dropna()
            if len(s) < 3:
                return None
            y = s.values[-4:]
            x = np.arange(len(y))
            denom = ((x - x.mean()) ** 2).sum()
            if denom == 0:
                return None
            return float(((x - x.mean()) * (y - y.mean())).sum() / denom)
        slopes = []
        for col, norm in (("accruals_to_ta", 0.03), ("dso", 6.0), ("m_score", 0.6)):
            if col in series.columns:
                sl = slope(col)
                if sl is not None:
                    slopes.append(sl / norm)
        if not slopes:
            return None
        raw = float(np.mean(slopes))
        # Threshold high: mild upward drift is common; only a clear escalation should score.
        return {"raw": raw, "evidence": _evidence(raw, 0.65, 0.35)}

    @staticmethod
    def _band(p: float) -> str:
        if p >= 0.66:
            return "ELEVATED"
        if p >= 0.40:
            return "WATCH"
        return "LOW"
