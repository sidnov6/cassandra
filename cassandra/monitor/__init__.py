"""Autonomous monitoring (blueprint §11 — real-time alerting extension).

The Sentinel continuously scans newly-filed SEC reports, scores each with the cheap towers,
gates the expensive agent review to the riskiest (cost gating §6.6), and writes irregularity
alerts to the lake — idempotently, so it can run forever on a schedule without duplicating.
"""
from .sentinel import Sentinel, ScanSummary

__all__ = ["Sentinel", "ScanSummary"]
