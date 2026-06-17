"use client";
import { useEffect, useState } from "react";
import { EvalReport, ScreenResult, evalReport, fmt, screen } from "@/lib/api";

export function Portfolio() {
  const [rep, setRep] = useState<EvalReport | null>(null);
  const [scr, setScr] = useState<ScreenResult | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([evalReport(), screen(25)]).then(([r, s]) => {
      setRep(r); setScr(s); setLoading(false);
    });
  }, []);

  if (loading) return <div className="text-center py-20" style={{ color: "var(--muted)" }}>Loading evaluation…</div>;

  return (
    <div className="space-y-4">
      {/* eval / ablation */}
      <div className="panel p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="text-[11px] uppercase tracking-wider" style={{ color: "var(--muted)" }}>
            Point-in-time backtest · ablation (§7)
          </div>
          {rep && <div className="text-[11px] mono" style={{ color: "var(--muted)" }}>
            {rep.n_rows} firm-years · {rep.n_firms} firms · {rep.positives} positives · base rate {fmt(rep.base_rate, 3)}
          </div>}
        </div>
        {!rep ? <Empty msg="No eval report yet. Run scripts/train_models.py." /> : (
          <table className="w-full text-[12px]">
            <thead><tr style={{ color: "var(--muted)" }} className="text-left">
              <th className="py-1.5">Model</th><th>PR-AUC</th><th>P@10</th><th>Recall@25</th><th>Top-decile lift</th>
            </tr></thead>
            <tbody>
              {(() => {
                const best = Object.entries(rep.ablation).reduce((b, e) => e[1].pr_auc > b[1].pr_auc ? e : b);
                return Object.entries(rep.ablation).map(([name, m]) => {
                const full = name === best[0];
                return (
                  <tr key={name} style={{ borderTop: "1px solid var(--line-soft)", background: full ? "color-mix(in oklab, var(--gold) 8%, transparent)" : "transparent" }}>
                    <td className="py-1.5" style={{ color: full ? "var(--gold)" : "var(--ink)", fontWeight: full ? 500 : 400 }}>{name}{full ? "  ★" : ""}</td>
                    <td className="mono">{fmt(m.pr_auc, 3)}</td>
                    <td className="mono">{fmt(m.precision_at_k?.["10"], 2)}</td>
                    <td className="mono">{fmt(m.recall_at_k?.["25"], 2)}</td>
                    <td className="mono">{fmt(m.top_decile_lift, 2)}×</td>
                  </tr>
                );
              }); })()}
            </tbody>
          </table>
        )}
        {rep && rep.walk_forward.length > 0 && (
          <div className="mt-4">
            <div className="text-[11px] uppercase tracking-wider mb-2" style={{ color: "var(--muted)" }}>Walk-forward (expanding window)</div>
            <div className="flex gap-2 flex-wrap">
              {rep.walk_forward.map((w) => (
                <div key={w.test_year} className="panel px-3 py-2 text-[11px]">
                  <div className="mono">FY{w.test_year}</div>
                  <div style={{ color: "var(--gold)" }} className="mono">PR-AUC {fmt(w.pr_auc, 2)}</div>
                  <div style={{ color: "var(--muted)" }}>{w.positives}/{w.n_test} pos</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* cost-gated screen */}
      <div className="panel p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="text-[11px] uppercase tracking-wider" style={{ color: "var(--muted)" }}>
            Cost-gated triage screen (§6.6) · latest filing per firm
          </div>
          {scr && <div className="text-[11px] mono" style={{ color: "var(--muted)" }}>
            {scr.summary.agent_runs}/{scr.summary.universe_size} run agents · {fmt(scr.summary.cost_reduction * 100, 0)}% cost cut · via {scr.summary.cheap_source}
          </div>}
        </div>
        {!scr ? <Empty msg="No gold table. Run scripts/build_universe.py." /> : (
          <table className="w-full text-[12px]">
            <thead><tr style={{ color: "var(--muted)" }} className="text-left">
              <th className="py-1.5">#</th><th>Ticker</th><th>Company</th><th>FY</th><th>Risk</th>
              <th>Beneish M</th><th>CFO/NI</th><th>Why</th><th>Label</th>
            </tr></thead>
            <tbody>
              {scr.candidates.map((r) => (
                <tr key={`${r.ticker}-${r.rank}`} style={{ borderTop: "1px solid var(--line)" }}>
                  <td className="py-1.5 mono" style={{ color: "var(--muted)" }}>{r.rank}</td>
                  <td className="mono">{r.ticker || "—"}</td>
                  <td className="truncate max-w-[200px]">{r.name}</td>
                  <td className="mono" style={{ color: "var(--muted)" }}>{r.fiscal_year}</td>
                  <td className="mono" style={{ color: r.cheap_score >= 0.5 ? "#cf5a40" : r.cheap_score >= 0.25 ? "#d99a3a" : "#57b39c" }}>{fmt(r.cheap_score)}</td>
                  <td className="mono">{fmt(r.beneish_m)}</td>
                  <td className="mono">{fmt(r.cfo_ni_ratio)}</td>
                  <td><span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: r.selection_reason === "top_k" ? "color-mix(in oklab, var(--gold) 16%, transparent)" : "color-mix(in oklab, var(--patina) 16%, transparent)", color: r.selection_reason === "top_k" ? "var(--gold)" : "var(--patina)" }}>{r.selection_reason}</span></td>
                  <td>{r.label === 1 ? <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: "color-mix(in oklab, var(--risk-high) 16%, transparent)", color: "#e0876f" }}>known case</span> : <span style={{ color: "var(--muted)" }}>—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return <div className="text-[12px] panel p-3" style={{ color: "var(--muted)" }}>{msg}</div>;
}
