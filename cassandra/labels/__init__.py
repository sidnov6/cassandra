"""Ground-truth labels (blueprint §3.1, §7.1).

Positive labels are aligned to the COMMISSION period (when the books were cooked), never to
the enforcement date — a model that 'predicts' fraud the day the SEC announces it is
worthless. The clean class is treated as *unlabeled, presumed-negative* (§10 selection bias).
"""
from .known_cases import KNOWN_CASES, load_cases, CaseLabel
from .aligned import build_labels_aligned, label_for_filing

__all__ = ["KNOWN_CASES", "load_cases", "CaseLabel", "build_labels_aligned", "label_for_filing"]
