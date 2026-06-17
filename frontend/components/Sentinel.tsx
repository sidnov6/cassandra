"use client";
import { useCallback, useEffect, useState } from "react";
import { AlertRow, BASE, ScanSummary, fmt, getAlerts, riskColor, runScan } from "@/lib/api";
import { WatchdogMap } from "./WatchdogMap";

export function Sentinel({ onOpen }: { onOpen: (ticker: string, year: string) => void }) {
  const [alerts, setAlerts] = useState<AlertRow[]>([]);
  const [scanning, setScanning] = useState(false);
  const [summary, setSummary] = useState<ScanSummary | null>(null);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    setAlerts(await getAlerts(120));
    setLoaded(true);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const scan = useCallback(async (source: "daily" | "watchlist") => {
    setScanning(true); setSummary(null);
    const res = await runScan(source, source === "daily" ? 25 : 40);
    if (res && !("error" in res)) setSummary(res);
    await refresh();
    setScanning(false);
  }, [refresh]);

  const elevated = alerts.filter((a) => a.band === "ELEVATED").length;
  const reviewed = alerts.filter((a) => a.agent_reviewed).length;

  return (
    <div className="space-y-4">
      <WatchdogMap onOpen={onOpen} />

      <div className="panel p-5">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-2">
              <span style={{ width: 7, height: 7, borderRadius: 99, background: "var(--patina)",
                display: "inline-block", boxShadow: "0 0 0 3px color-mix(in oklab, var(--patina) 22%, transparent)" }} />
              <div className="eyebrow">autonomous sentinel</div>
            </div>
            <h2 className="text-[19px] tracking-tight mt-2" style={{ fontWeight: 500 }}>
              Continuous irregularity surveillance
            </h2>
            <p className="text-[13px] mt-1" style={{ color: "var(--muted-solid)", maxWidth: 560, lineHeight: 1.6 }}>
              The Sentinel scans newly-filed SEC reports, scores every filer, and escalates the
              riskiest to a full agent review — on its own. Idempotent, so it runs forever on a
              schedule (<span className="mono">cron · systemd · launchd</span>).
            </p>
          </div>
          <div className="flex gap-2.5">
            <button onClick={() => scan("daily")} disabled={scanning}
              className="btn btn-gold px-4 py-2 text-[13px]" style={{ borderRadius: 6, fontWeight: 500, opacity: scanning ? 0.6 : 1 }}>
              {scanning ? "Scanning…" : "Scan latest filings"}
            </button>
            <button onClick={() => scan("watchlist")} disabled={scanning}
              className="tap px-4 py-2 text-[13px] panel" style={{ borderRadius: 6, color: "var(--ink)" }}>
              Rescan universe
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-px mt-5" style={{ background: "var(--line-soft)", borderRadius: 6, overflow: "hidden" }}>
          {[["tracked alerts", alerts.length], ["elevated", elevated],
            ["agent-reviewed", reviewed], ["last scan", summary ? `${summary.new_alerts} new` : "—"]].map(([k, v]) => (
            <div key={k as string} className="p-3" style={{ background: "var(--panel)" }}>
              <div className="eyebrow">{k}</div>
              <div className="mono text-[20px] mt-1" style={{ color: k === "elevated" && (v as number) > 0 ? "var(--risk-high)" : "var(--ink)" }}>{v}</div>
            </div>
          ))}
        </div>
        {summary && (
          <div className="text-[12px] mono mt-3" style={{ color: "var(--muted-solid)" }}>
            {summary.source}/{summary.index_date}: {summary.candidates} candidates → {summary.scored} scored
            → {summary.flagged} flagged · {summary.agent_reviewed} agent-reviewed · {summary.elevated} elevated
          </div>
        )}
      </div>

      <div className="panel p-5">
        <div className="eyebrow mb-3">irregularity feed · highest risk first</div>
        {!loaded ? <div className="text-[12px]" style={{ color: "var(--muted)" }}>Loading…</div>
          : alerts.length === 0 ? (
          <div className="text-[12px] panel p-3" style={{ color: "var(--muted)" }}>
            No alerts yet. Run a scan to populate the feed.
          </div>
        ) : (
          <table className="w-full text-[12px]">
            <thead><tr style={{ color: "var(--muted)" }} className="text-left">
              <th className="py-1.5">Risk</th><th>Band</th><th>Filer</th><th>FY</th><th>Form</th>
              <th>Beneish M</th><th>CFO/NI</th><th>Top flag</th><th></th>
            </tr></thead>
            <tbody>
              {alerts.map((a, i) => (
                <tr key={a.accession + i} className="tap cursor-pointer"
                  onClick={() => onOpen(a.ticker || a.cik, "")}
                  style={{ borderTop: "1px solid var(--line-soft)" }}>
                  <td className="py-2 mono" style={{ color: riskColor(a.score) }}>{fmt(a.score)}</td>
                  <td><span className="text-[10px] px-1.5 py-0.5 rounded mono"
                    style={{ background: `color-mix(in oklab, ${riskColor(a.score)} 16%, transparent)`, color: riskColor(a.score) }}>{a.band}</span></td>
                  <td className="max-w-[200px] truncate">
                    <span style={{ color: "var(--ink)" }}>{a.company}</span>
                    {a.ticker && <span className="mono ml-1.5" style={{ color: "var(--faint)" }}>{a.ticker}</span>}
                  </td>
                  <td className="mono" style={{ color: "var(--muted)" }}>{a.fiscal_year}</td>
                  <td className="mono" style={{ color: "var(--muted)" }}>{a.form || "—"}</td>
                  <td className="mono">{fmt(a.beneish_m)}</td>
                  <td className="mono">{fmt(a.cfo_ni_ratio)}</td>
                  <td className="max-w-[200px] truncate" style={{ color: "var(--muted-solid)" }}>{a.top_flags || "—"}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <a href={`${BASE}/api/dossier.pdf?q=${a.cik}`} target="_blank" rel="noreferrer"
                      className="eyebrow tap" style={{ color: "var(--gold)", textDecoration: "none" }}>PDF</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
