"""Layer 2 — Feature engineering: forensic ratios, Benford digit tests, text signals."""
from .benford import benford_analysis, BenfordResult
from .forensic import compute_forensic, ForensicReport

__all__ = ["benford_analysis", "BenfordResult", "compute_forensic", "ForensicReport"]
