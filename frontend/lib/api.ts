// Backend base URL. Direct (CORS-enabled) so the SSE stream is not buffered by a proxy.
export const BASE =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8011";

export type SearchResult = { cik: string; ticker: string; name: string };

export type Signal = {
  name: string; raw: number | null; evidence: number | null;
  modality: string; weight: number; note: string;
};
export type Score = {
  fused_p: number; calibrated_p: number; confidence: number; band: string;
  towers: Record<string, number | null>;
  contributions: Record<string, number>;
  signals: Signal[];
};
export type Benford = {
  n: number; digits: number[]; observed: number[]; expected: number[];
  mad: number; conformity: string; two_digit_conformity: string | null; anomaly_score: number;
};
export type ForensicSeries = Record<string, (number | null)[]>;
export type Summary = {
  company: { cik: string; ticker: string; name: string };
  filing: { accession: string | null; fiscal_year: number; point_in_time: string;
            fiscal_years_available: number[] };
  score: Score;
  forensic: { features: Record<string, number | string | null>;
              interpretations: Record<string, string>;
              series: ForensicSeries; benford: Benford | null };
  text: Record<string, unknown> | null;
};
export type Flag = {
  flag_id: string; agent: string; title: string; severity: number; confidence: number;
  rationale: string; evidence_refs: string[];
};
export type Rebuttal = { flag_id: string; benign_explanation: string; residual_concern: number };
export type Analogue = {
  case_name: string; similarity: number; shared_pattern: string;
  in_distribution: boolean; note: string;
};
export type Dossier = {
  entity: string; fiscal_year: number; calibrated_score: number; band: string;
  flags: Flag[]; rebuttals: Rebuttal[]; analogues: Analogue[]; memo: string; llm_mode: string;
};

export async function search(q: string): Promise<SearchResult[]> {
  const r = await fetch(`${BASE}/api/search?q=${encodeURIComponent(q)}&limit=8`);
  const d = await r.json();
  return d.results ?? [];
}

export async function health(): Promise<{ llm_mode: string; llm_model: string | null }> {
  return (await fetch(`${BASE}/api/health`)).json();
}

export async function evalReport(): Promise<EvalReport | null> {
  const r = await fetch(`${BASE}/api/eval`);
  if (!r.ok) return null;
  return r.json();
}

export async function screen(k = 25): Promise<ScreenResult | null> {
  const r = await fetch(`${BASE}/api/screen?k=${k}`);
  if (!r.ok) return null;
  return r.json();
}

export type Metrics = {
  pr_auc: number; roc_auc: number; precision_at_k: Record<string, number>;
  recall_at_k: Record<string, number>; top_decile_lift: number; brier: number; ece: number;
};
export type EvalReport = {
  n_rows: number; n_firms: number; positives: number; base_rate: number;
  towers: string[]; fused: Metrics; ablation: Record<string, Metrics>;
  walk_forward: { test_year: number; n_test: number; positives: number; pr_auc: number }[];
  tower_oof_pr_auc: Record<string, number>;
};
export type ScreenRow = {
  ticker: string; name: string; fiscal_year: number; cheap_score: number;
  selection_reason: string; rank: number; beneish_m: number | null;
  dechow_f: number | null; cfo_ni_ratio: number | null; label: number;
};
export type ScreenResult = {
  summary: { universe_size: number; agent_runs: number; cost_reduction: number;
             top_k: number; audit_sample: number; cheap_source: string };
  candidates: ScreenRow[];
};

// Semantic risk ramp — desaturated, the only place color encodes data meaning.
export type AlertRow = {
  accession: string; cik: string; ticker: string; company: string; form: string;
  filing_date: string; fiscal_year: number; score: number; band: string;
  beneish_m: number | null; cfo_ni_ratio: number | null; top_flags: string;
  agent_reviewed: boolean; index_date: string; detected_at: string;
};
export type ScanSummary = {
  index_date: string; source: string; candidates: number; scored: number;
  flagged: number; agent_reviewed: number; new_alerts: number; elevated: number;
};

export async function getAlerts(limit = 100): Promise<AlertRow[]> {
  const r = await fetch(`${BASE}/api/alerts?limit=${limit}`);
  if (!r.ok) return [];
  return (await r.json()).alerts ?? [];
}
export async function runScan(source: "daily" | "watchlist", limit = 20): Promise<ScanSummary | { error: string }> {
  const r = await fetch(`${BASE}/api/sentinel/scan?source=${source}&limit=${limit}&topk=6`);
  return r.json();
}

export const riskColor = (p: number) =>
  p >= 0.66 ? "#cf5a40" : p >= 0.4 ? "#d99a3a" : "#57b39c";
export const GOLD = "#e6b24a";
export const fmt = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : (+v).toFixed(d);
