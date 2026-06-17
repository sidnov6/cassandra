"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  BASE, Dossier, Summary, SearchResult, fmt, riskColor, health, search,
} from "@/lib/api";
import { RiskGauge, ContributionDonut, BenfordChart, TrendChart } from "./Charts";
import { AgentGraph, NodeStatus } from "./AgentGraph";
import { Portfolio } from "./Portfolio";
import { Sentinel } from "./Sentinel";

type View = "analysis" | "portfolio" | "sentinel";

const ALL_NODES = ["router", "revenue", "accruals", "cashflow", "benford", "governance",
  "language", "collector", "challenger", "analogue", "synthesis"];

type Trace = { node: string; msg: string };

export default function Workstation() {
  const [view, setView] = useState<View>("analysis");
  const [q, setQ] = useState("");
  const [year, setYear] = useState("");
  const [ac, setAc] = useState<SearchResult[]>([]);
  const [mode, setMode] = useState("…");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [states, setStates] = useState<Record<string, NodeStatus>>({});
  const [traces, setTraces] = useState<Trace[]>([]);
  const [dossier, setDossier] = useState<Dossier | null>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState("");
  const esRef = useRef<EventSource | null>(null);
  const traceRef = useRef<HTMLDivElement>(null);

  useEffect(() => { health().then((h) => setMode(h.llm_mode === "llm" ? `LLM · ${h.llm_model}` : "deterministic agents")).catch(() => setMode("offline")); }, []);
  useEffect(() => { traceRef.current?.scrollTo({ top: 1e6 }); }, [traces]);

  const onSearch = useCallback((v: string) => {
    setQ(v);
    if (v.length < 1) { setAc([]); return; }
    search(v).then(setAc).catch(() => setAc([]));
  }, []);

  const run = useCallback((query: string, yr: string) => {
    if (!query) return;
    esRef.current?.close();
    setAc([]); setErr(""); setDossier(null); setTraces([]); setSummary(null);
    setStates(Object.fromEntries(ALL_NODES.map((n) => [n, "idle"])));
    setRunning(true);
    const url = `${BASE}/api/score/stream?q=${encodeURIComponent(query)}${yr ? `&year=${yr}` : ""}`;
    const es = new EventSource(url); esRef.current = es;
    es.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.node === "__error__") { setErr(d.msg); setRunning(false); es.close(); return; }
      if (d.node === "__summary__") { setSummary(d.payload); return; }
      if (d.node === "__final__") { setDossier(d.payload.dossier); setRunning(false); es.close(); return; }
      setStates((s) => ({ ...s, [d.node]: d.payload?.flags?.length ? "flagged" : (d.status as NodeStatus) }));
      if (d.msg) setTraces((t) => [...t, { node: d.node, msg: d.msg }].slice(-60));
    };
    es.onerror = () => { setRunning(false); es.close(); };
  }, []);

  const demo = (t: string, y: string) => { setQ(t); setYear(y); run(t, y); };

  return (
    <div className="min-h-screen">
      <Header q={q} onSearch={onSearch} ac={ac} pick={(t) => { setQ(t); setAc([]); run(t, year); }}
        year={year} setYear={setYear} years={summary?.filing.fiscal_years_available ?? []}
        onGo={() => run(q, year)} mode={mode} view={view} setView={setView} />

      {view === "sentinel" ? (
        <main className="max-w-[1500px] mx-auto px-5 py-5">
          <Sentinel onOpen={(t, y) => { setView("analysis"); setQ(t); setYear(y); run(t, y); }} />
        </main>
      ) : view === "portfolio" ? (
        <main className="max-w-[1500px] mx-auto px-5 py-5"><Portfolio /></main>
      ) : (
        <main className="max-w-[1500px] mx-auto px-5 py-5">
          {!summary && !err && (
            <div className="max-w-2xl mx-auto py-24 rise">
              <div className="eyebrow mb-3">point-in-time triage</div>
              <h1 className="text-[28px] leading-tight tracking-tight mb-3" style={{ fontWeight: 500 }}>
                Read a company&apos;s books the way a forensic analyst would.
              </h1>
              <p style={{ color: "var(--muted-solid)", lineHeight: 1.7 }} className="text-[15px]">
                As-filed SEC financials run through the forensic battery — Beneish, Altman, Dechow F,
                accruals, Benford — into a calibrated risk score and an agent review that argues both
                sides and cites every claim.
              </p>
              <div className="flex gap-2.5 mt-6">
                <button className="tap text-[13px] px-3.5 py-2 panel" style={{ color: "var(--gold)" }}
                  onClick={() => demo("UAA", "2015")}>Under Armour · FY2015 <span style={{ color: "var(--faint)" }}>SEC-charged</span></button>
                <button className="tap text-[13px] px-3.5 py-2 panel" style={{ color: "var(--ink)" }}
                  onClick={() => demo("AAPL", "")}>Apple · latest</button>
              </div>
            </div>
          )}
          {err && <div className="panel p-4 text-[13px]" style={{ color: "var(--risk-watch)" }}>{err}</div>}
          {summary && <Analysis summary={summary} states={states} traces={traces} dossier={dossier} running={running} traceRef={traceRef} />}
        </main>
      )}
    </div>
  );
}

function Header(p: {
  q: string; onSearch: (v: string) => void; ac: SearchResult[]; pick: (t: string) => void;
  year: string; setYear: (y: string) => void; years: number[]; onGo: () => void; mode: string;
  view: View; setView: (v: View) => void;
}) {
  return (
    <header className="sticky top-0 z-30" style={{ background: "color-mix(in oklab, var(--bg) 88%, transparent)",
      borderBottom: "1px solid var(--line-soft)", backdropFilter: "blur(10px)" }}>
      <div className="max-w-[1500px] mx-auto px-5 h-14 flex items-center gap-4">
        <div className="flex items-center gap-2.5 shrink-0">
          <div className="w-7 h-7 flex items-center justify-center text-[15px]"
            style={{ background: "var(--gold)", color: "#1c1505", borderRadius: 5, fontWeight: 500 }}>Λ</div>
          <div className="leading-none">
            <div className="tracking-[0.16em] text-[13px]" style={{ fontWeight: 500 }}>CASSANDRA</div>
            <div className="eyebrow mt-1" style={{ fontSize: 9 }}>forensic intelligence</div>
          </div>
        </div>
        <div className="relative flex-1 max-w-xl">
          <input value={p.q} onChange={(e) => p.onSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && p.onGo()} autoComplete="off"
            placeholder="Search ticker, company, or CIK"
            className="w-full px-3.5 py-2 text-sm outline-none"
            style={{ background: "var(--panel)", border: "1px solid var(--line-soft)", borderRadius: 6 }} />
          {p.ac.length > 0 && (
            <div className="absolute mt-1.5 w-full panel overflow-hidden z-40 rise divide-rule">
              {p.ac.map((x) => (
                <div key={x.cik} onClick={() => p.pick(x.ticker || x.cik)}
                  className="px-3.5 py-2 cursor-pointer flex justify-between items-center tap hover:bg-[color:var(--panel-2)]">
                  <span className="text-[13px]">{x.name}</span>
                  <span className="mono text-[11px]" style={{ color: "var(--faint)" }}>{x.ticker || `CIK ${x.cik}`}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <select value={p.year} onChange={(e) => p.setYear(e.target.value)}
          className="px-3 py-2 text-sm outline-none"
          style={{ background: "var(--panel)", border: "1px solid var(--line-soft)", borderRadius: 6 }}>
          <option value="">Latest FY</option>
          {[...p.years].reverse().map((y) => <option key={y} value={y}>FY{y}</option>)}
        </select>
        <button onClick={p.onGo} className="btn btn-gold px-4 py-2 text-sm" style={{ borderRadius: 6, fontWeight: 500 }}>Analyze</button>
        <div className="flex overflow-hidden text-[12px]" style={{ border: "1px solid var(--line-soft)", borderRadius: 6 }}>
          {(["analysis", "sentinel", "portfolio"] as const).map((v) => (
            <button key={v} onClick={() => p.setView(v)} className="px-3 py-2 capitalize tap"
              style={{ background: p.view === v ? "var(--panel-2)" : "transparent",
                color: p.view === v ? "var(--gold)" : "var(--faint)" }}>{v}</button>
          ))}
        </div>
        <span className="eyebrow hidden lg:flex items-center gap-1.5 px-2.5 py-1.5" style={{ border: "1px solid var(--line-soft)", borderRadius: 6 }}>
          <i style={{ width: 5, height: 5, borderRadius: 99, background: "var(--patina)", display: "inline-block" }} />{p.mode}
        </span>
      </div>
    </header>
  );
}

function Analysis({ summary, states, traces, dossier, running, traceRef }: {
  summary: Summary; states: Record<string, NodeStatus>; traces: Trace[];
  dossier: Dossier | null; running: boolean; traceRef: React.RefObject<HTMLDivElement | null>;
}) {
  const s = summary.score;
  const f = summary.forensic.features;
  const metrics: [string, number | string | null, string, string][] = [
    ["Beneish M", f.beneish_m as number, "Beneish M-Score", (f.beneish_m as number) > -1.78 ? "> −1.78 ⚠" : "< −1.78"],
    ["Dechow F", f.dechow_f as number, "Dechow F-Score", (f.dechow_f as number) > 1 ? "> 1 ⚠" : "≤ 1"],
    ["Altman Z", f.altman_z as number, "Altman Z-Score", ""],
    ["Accruals/TA", f.accruals_to_ta as number, "Accruals / Total Assets", ""],
    ["CFO / NI", f.cfo_ni_ratio as number, "CFO / Net Income", (f.cfo_ni_ratio as number) < 0.8 ? "divergence ⚠" : ""],
    ["DSO Δ days", f.dso_yoy_delta as number, "DSO YoY change (days)", ""],
  ];
  const evOf: Record<string, number | null> = {};
  s.signals.forEach((sig) => (evOf[sig.name] = sig.evidence));
  const rb: Record<string, number> = {};
  dossier?.rebuttals.forEach((r) => (rb[r.flag_id] = r.residual_concern));
  const pairs = (dossier?.flags ?? []).slice().sort((a, b) => (rb[b.flag_id] ?? 0) - (rb[a.flag_id] ?? 0));

  return (
    <>
      <div className="flex items-end justify-between mb-4 flex-wrap gap-3">
        <div>
          <div className="text-xl font-semibold tracking-tight">{summary.company.name}{summary.company.ticker ? `  ·  ${summary.company.ticker}` : ""}</div>
          <div className="text-[12px] mono" style={{ color: "var(--muted)" }}>
            CIK {summary.company.cik} · FY{summary.filing.fiscal_year} · accession {summary.filing.accession ?? "—"}
          </div>
        </div>
        <div className="text-[11px]" style={{ color: "var(--muted)" }}>point-in-time: {summary.filing.point_in_time} · as-filed (amendments excluded)</div>
      </div>

      <div className="grid grid-cols-12 gap-4">
        <section className="col-span-12 lg:col-span-4 space-y-4">
          <Card title="Calibrated manipulation risk">
            <RiskGauge value={s.calibrated_p} band={s.band} confidence={s.confidence} />
            <div className="text-[11px] text-center" style={{ color: "var(--muted)" }}>Triage flag, not a determination.</div>
          </Card>
          <Card title="Modality contribution"><ContributionDonut contributions={s.contributions} /></Card>
          <Card title="Forensic battery">
            <div className="grid grid-cols-2 gap-2.5">
              {metrics.map(([k, v, key, note]) => {
                const ev = evOf[key]; const c = ev == null ? "#5b6b80" : ev > 0.6 ? "#cf5a40" : ev > 0.4 ? "#d99a3a" : "#57b39c";
                return (
                  <div key={k} className="panel p-2.5">
                    <div className="flex justify-between items-baseline">
                      <span className="text-[11px]" style={{ color: "var(--muted)" }}>{k}</span>
                      <span className="mono text-sm" style={{ color: c }}>{fmt(v as number)}</span>
                    </div>
                    <div className="h-1.5 mt-1.5 rounded-full overflow-hidden" style={{ background: "#211e18" }}>
                      <div style={{ width: `${ev == null ? 0 : Math.round(ev * 100)}%`, height: "100%", background: c }} />
                    </div>
                    <div className="text-[10px] mt-1" style={{ color: "var(--muted)" }}>{note || " "}</div>
                  </div>
                );
              })}
            </div>
          </Card>
        </section>

        <section className="col-span-12 lg:col-span-5 space-y-4">
          <Card title="Agentic reasoning journey" right={running ? "running…" : dossier ? "complete" : ""}>
            <AgentGraph states={states} />
            <div ref={traceRef} className="mono text-[11.5px] leading-5 rounded-xl p-3 h-32 overflow-auto mt-2"
              style={{ background: "#0a0907", border: "1px solid var(--line-soft)" }}>
              {traces.map((t, i) => (
                <div key={i} className="rise"><span className="mono" style={{ color: "var(--gold)" }}>{t.node}</span> <span style={{ color: "var(--muted-solid)" }}>{t.msg}</span></div>
              ))}
            </div>
          </Card>
          <Card title="Evidence dossier · flags & challenger">
            {pairs.length === 0 ? (
              <div className="text-[12px] panel p-3" style={{ color: "var(--muted)" }}>
                {dossier ? "No specialist raised a grounded concern at the configured thresholds. Continue routine monitoring." : "Awaiting agent run…"}
              </div>
            ) : pairs.map((fl, i) => {
              const res = rb[fl.flag_id] ?? 0; const c = res > 0.5 ? "#cf5a40" : res > 0.3 ? "#d99a3a" : "#6c675e";
              const reb = dossier?.rebuttals.find((r) => r.flag_id === fl.flag_id);
              return (
                <details key={fl.flag_id} className="panel p-3 rise mb-2" style={{ animationDelay: `${i * 60}ms` }}>
                  <summary className="flex items-center justify-between gap-2 cursor-pointer list-none">
                    <span className="text-[13px] font-medium">{fl.title}</span>
                    <span className="mono text-[11px] px-2 py-0.5 rounded" style={{ background: `${c}22`, color: c }}>res {fmt(res)}</span>
                  </summary>
                  <div className="text-[11px] mt-1" style={{ color: "var(--muted)" }}>{fl.agent} · severity {fmt(fl.severity)} · confidence {fmt(fl.confidence)}</div>
                  <div className="text-[12px] mt-2" style={{ color: "var(--ink)" }}>{fl.rationale}</div>
                  {reb && <div className="text-[12px] mt-2 pl-2" style={{ borderLeft: "2px solid color-mix(in oklab, var(--gold) 35%, transparent)" }}><b style={{ color: "var(--gold)" }}>Challenger:</b> {reb.benign_explanation}</div>}
                  <div className="text-[10px] mt-2 mono" style={{ color: "var(--muted)" }}>{fl.evidence_refs.join("  ·  ")}</div>
                </details>
              );
            })}
          </Card>
        </section>

        <section className="col-span-12 lg:col-span-3 space-y-4">
          <Card title="Synthesis memo">
            <pre className="whitespace-pre-wrap text-[12px] leading-5" style={{ color: "#d8d2c6" }}>{dossier?.memo ?? "Awaiting synthesis…"}</pre>
          </Card>
          <Card title="Historical analogues">
            {(dossier?.analogues ?? []).length === 0 ? <div className="text-[12px]" style={{ color: "var(--muted)" }}>—</div> :
              dossier!.analogues.map((a) => (
                <div key={a.case_name} className="panel p-2.5 mb-2 text-[12px]" style={{ color: "var(--muted)" }}>
                  <div className="flex justify-between"><b style={{ color: "var(--ink)" }}>{a.case_name}</b><span className="mono" style={{ color: "var(--gold)" }}>sim {fmt(a.similarity)}</span></div>
                  <div className="mt-0.5">{a.shared_pattern}</div>
                  {!a.in_distribution && <div className="text-[10px] mt-1" style={{ color: "var(--risk-watch)" }}>out-of-distribution · qualitative analogue</div>}
                </div>
              ))}
          </Card>
        </section>

        <section className="col-span-12 lg:col-span-6">
          <Card title="Benford's Law · first-digit distribution"
            right={summary.forensic.benford ? `n=${summary.forensic.benford.n} · MAD ${fmt(summary.forensic.benford.mad, 4)} · ${summary.forensic.benford.conformity}` : ""}>
            <BenfordChart b={summary.forensic.benford} />
          </Card>
        </section>
        <section className="col-span-12 lg:col-span-6">
          <Card title="Escalation trajectory · multi-year"><TrendChart series={summary.forensic.series} /></Card>
        </section>
      </div>
    </>
  );
}

function Card({ title, right, children }: { title: string; right?: string; children: React.ReactNode }) {
  return (
    <div className="panel p-5 rise">
      <div className="flex items-center justify-between mb-3">
        <div className="eyebrow">{title}</div>
        {right && <div className="text-[11px] mono" style={{ color: "var(--gold)" }}>{right}</div>}
      </div>
      {children}
    </div>
  );
}
