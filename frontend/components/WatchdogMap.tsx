"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { geoAlbersUsa, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import statesTopo from "us-atlas/states-10m.json";
import { BASE, fmt, riskColor } from "@/lib/api";

const W = 960, H = 600;

type Det = {
  cik: string; ticker: string; company: string; city: string; state: string;
  score: number; band: string; flags: string; x: number; y: number; flagged: boolean;
};

export function WatchdogMap({ onOpen }: { onOpen: (t: string, y: string) => void }) {
  const { statePaths, project } = useMemo(() => {
    /* eslint-disable @typescript-eslint/no-explicit-any */
    const topo = statesTopo as any;
    const fc = feature(topo, topo.objects.states) as any;
    const proj = geoAlbersUsa().fitSize([W, H], fc);
    const path = geoPath(proj);
    return {
      statePaths: (fc.features as any[]).map((f: any, i: number) => ({ d: path(f) || "", id: i })),
      project: (lng: number, lat: number) => proj([lng, lat]) as [number, number] | null,
    };
  }, []);

  const [scanning, setScanning] = useState(false);
  const [drone, setDrone] = useState({ x: W / 2, y: H / 2 });
  const [dets, setDets] = useState<Det[]>([]);
  const [pings, setPings] = useState<{ x: number; y: number; band: string; id: number }[]>([]);
  const [current, setCurrent] = useState<string>("");
  const [counts, setCounts] = useState({ scanned: 0, flagged: 0, elevated: 0 });
  const [selected, setSelected] = useState<Det | null>(null);
  const [done, setDone] = useState<string>("");
  const [acq, setAcq] = useState<{ id: number; x: number; y: number }[]>([]);
  const [banner, setBanner] = useState<{ id: number; company: string; ticker: string; score: number } | null>(null);
  const [trail, setTrail] = useState<{ x: number; y: number }[]>([]);
  const [flash, setFlash] = useState(0);
  const esRef = useRef<EventSource | null>(null);
  const pingId = useRef(0);

  useEffect(() => () => esRef.current?.close(), []);

  const launch = useCallback((source: "watchlist" | "daily") => {
    esRef.current?.close();
    setScanning(true); setDets([]); setPings([]); setSelected(null); setDone("");
    setAcq([]); setBanner(null); setTrail([]);
    setCounts({ scanned: 0, flagged: 0, elevated: 0 }); setCurrent("acquiring targets…");
    const es = new EventSource(`${BASE}/api/sentinel/stream?source=${source}&limit=${source === "daily" ? 25 : 60}`);
    esRef.current = es;
    es.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.type === "error") { setCurrent("error: " + d.msg); setScanning(false); es.close(); return; }
      if (d.type === "done") {
        setDone(`sweep complete · ${d.scored} scanned · ${d.flagged} flagged · ${d.elevated} elevated`);
        setCurrent(""); setScanning(false); es.close(); return;
      }
      if (d.type !== "scan") return;
      const xy = d.lat != null && d.lng != null ? project(d.lng, d.lat) : null;
      setCounts((c) => ({ scanned: c.scanned + 1, flagged: c.flagged + (d.flagged ? 1 : 0),
        elevated: c.elevated + (d.band === "ELEVATED" ? 1 : 0) }));
      setCurrent(`${d.company}${d.state ? " · " + d.state : ""}`);
      if (!xy) return;
      const [x, y] = xy;
      setDrone({ x, y });
      setTrail((t) => [...t.slice(-11), { x, y }]);
      const id = pingId.current++;
      setPings((p) => [...p.slice(-8), { x, y, band: d.band, id }]);
      setTimeout(() => setPings((p) => p.filter((q) => q.id !== id)), 1400);
      if (d.flagged) {
        setDets((prev) => {
          const det: Det = { cik: d.cik, ticker: d.ticker, company: d.company, city: d.city,
            state: d.state, score: d.score, band: d.band, flags: d.top_flags, x, y, flagged: true };
          return [...prev.filter((p) => p.cik !== d.cik), det];
        });
      }
      if (d.band === "ELEVATED") {
        // TARGET ACQUIRED — reticle snap, shockwave, HUD callout, map pulse
        const aid = pingId.current++;
        setAcq((a) => [...a, { id: aid, x, y }]);
        setTimeout(() => setAcq((a) => a.filter((q) => q.id !== aid)), 1700);
        setBanner({ id: aid, company: d.company, ticker: d.ticker, score: d.score });
        setFlash(aid);
        setTimeout(() => setBanner((b) => (b && b.id === aid ? null : b)), 2200);
      }
    };
    es.onerror = () => { setScanning(false); es.close(); };
  }, [project]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span style={{ width: 7, height: 7, borderRadius: 99, background: scanning ? "var(--risk-high)" : "var(--patina)",
              display: "inline-block", boxShadow: `0 0 0 3px color-mix(in oklab, ${scanning ? "var(--risk-high)" : "var(--patina)"} 22%, transparent)` }} />
            <div className="eyebrow">watchdog · live aerial sweep</div>
          </div>
          <div className="text-[13px] mt-1.5 mono" style={{ color: "var(--muted-solid)", minHeight: 18 }}>
            {scanning ? <span style={{ color: "var(--gold)" }}>▸ scanning {current}</span>
              : done ? <span style={{ color: "var(--patina)" }}>{done}</span>
              : "drone idle — launch a sweep to map irregularities across US registrants"}
          </div>
        </div>
        <div className="flex gap-2.5">
          <button onClick={() => launch("watchlist")} disabled={scanning}
            className="btn btn-gold px-4 py-2 text-[13px]" style={{ borderRadius: 6, fontWeight: 500, opacity: scanning ? 0.55 : 1 }}>
            {scanning ? "Sweeping…" : "Launch sweep"}
          </button>
          <button onClick={() => launch("daily")} disabled={scanning}
            className="tap px-4 py-2 text-[13px] panel" style={{ borderRadius: 6, color: "var(--ink)" }}>
            Sweep today&apos;s filings
          </button>
        </div>
      </div>

      <div className="relative panel" style={{ overflow: "hidden", background: "#0a0906" }}>
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full block">
          <defs>
            <radialGradient id="cone" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="var(--gold)" stopOpacity="0.18" />
              <stop offset="100%" stopColor="var(--gold)" stopOpacity="0" />
            </radialGradient>
            <filter id="soft"><feGaussianBlur stdDeviation="1.1" /></filter>
          </defs>

          {statePaths.map((s) => (
            <path key={s.id} d={s.d} fill="#11100b" stroke="color-mix(in oklab, var(--gold) 16%, transparent)" strokeWidth={0.5} />
          ))}

          {/* flight trail */}
          {trail.length > 1 && (
            <polyline points={trail.map((p) => `${p.x},${p.y}`).join(" ")} fill="none"
              stroke="var(--gold)" strokeWidth={1} strokeOpacity={0.22} strokeDasharray="1.5 5" strokeLinecap="round" />
          )}

          {/* radar pings */}
          {pings.map((p) => (
            <circle key={p.id} cx={p.x} cy={p.y} r={4} fill="none"
              stroke={riskColor(p.band === "ELEVATED" ? 0.8 : p.band === "WATCH" ? 0.5 : 0.2)} strokeWidth={1.4}>
              <animate attributeName="r" from="4" to="34" dur="1.4s" />
              <animate attributeName="opacity" from="0.9" to="0" dur="1.4s" />
            </circle>
          ))}

          {/* detection markers */}
          {dets.map((d) => {
            const c = riskColor(d.score); const elev = d.band === "ELEVATED";
            return (
              <g key={d.cik} transform={`translate(${d.x},${d.y})`} className="marker-in"
                style={{ cursor: "pointer" }} onClick={() => setSelected(d)}>
                {elev && <circle r={9} fill="none" stroke={c} strokeWidth={1} opacity={0.6}>
                  <animate attributeName="r" values="7;12;7" dur="1.8s" repeatCount="indefinite" />
                  <animate attributeName="opacity" values="0.7;0.15;0.7" dur="1.8s" repeatCount="indefinite" /></circle>}
                <circle r={elev ? 4 : 3} fill={c} />
                {elev && (<g stroke={c} strokeWidth={1} opacity={0.85}>
                  <path d="M-9,-9 L-9,-5 M-9,-9 L-5,-9 M9,-9 L9,-5 M9,-9 L5,-9 M-9,9 L-9,5 M-9,9 L-5,9 M9,9 L9,5 M9,9 L5,9" fill="none" />
                </g>)}
              </g>
            );
          })}

          {/* target-acquired reticles + shockwave on elevated hits */}
          {acq.map((a) => (
            <g key={a.id} transform={`translate(${a.x},${a.y})`}>
              <circle r={6} fill="none" stroke="var(--risk-high)" strokeWidth={2}>
                <animate attributeName="r" from="6" to="52" dur="0.9s" />
                <animate attributeName="opacity" from="0.95" to="0" dur="0.9s" />
              </circle>
              <circle r={6} fill="none" stroke="var(--risk-high)" strokeWidth={1}>
                <animate attributeName="r" from="6" to="34" dur="0.9s" begin="0.14s" />
                <animate attributeName="opacity" from="0.7" to="0" dur="0.9s" begin="0.14s" />
              </circle>
              <g className="reticle-converge">
                <circle r={15} fill="none" stroke="var(--risk-high)" strokeWidth={0.7} opacity={0.55} />
                <path d="M-14,-14 L-14,-7 M-14,-14 L-7,-14 M14,-14 L14,-7 M14,-14 L7,-14 M-14,14 L-14,7 M-14,14 L-7,14 M14,14 L14,7 M14,14 L7,14"
                  fill="none" stroke="var(--risk-high)" strokeWidth={1.5} />
                <path d="M0,-5 L0,5 M-5,0 L5,0" stroke="var(--risk-high)" strokeWidth={0.8} opacity={0.7} />
              </g>
            </g>
          ))}

          {/* drone + scan cone */}
          {scanning && (
            <g style={{ transform: `translate(${drone.x}px,${drone.y}px)`,
              transition: "transform 700ms cubic-bezier(0.23,1,0.32,1)" }}>
              <circle r={46} fill="url(#cone)" />
              <g style={{ transformOrigin: "center" }}>
                <line x1={0} y1={0} x2={46} y2={0} stroke="var(--gold)" strokeWidth={1} opacity={0.5}>
                  <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="2.2s" repeatCount="indefinite" />
                </line>
              </g>
              <g filter="url(#soft)">
                <path d="M0,-9 L6,7 L0,3 L-6,7 Z" fill="var(--gold)" />
              </g>
              <path d="M0,-9 L6,7 L0,3 L-6,7 Z" fill="none" stroke="#fff3d6" strokeWidth={0.6} />
            </g>
          )}
        </svg>

        {/* map pulse on acquisition */}
        {flash > 0 && (
          <div key={flash} className="map-flash absolute inset-0" style={{ pointerEvents: "none",
            background: "radial-gradient(circle at 50% 46%, color-mix(in oklab, var(--risk-high) 28%, transparent), transparent 60%)" }} />
        )}

        {/* TARGET ACQUIRED banner */}
        {banner && (
          <div key={banner.id} className="acq-banner absolute mono" style={{ left: "50%", top: 14, pointerEvents: "none",
            background: "color-mix(in oklab, var(--bg) 80%, transparent)", border: "1px solid var(--risk-high)",
            borderRadius: 6, padding: "6px 14px", backdropFilter: "blur(6px)", whiteSpace: "nowrap", zIndex: 5 }}>
            <span style={{ color: "var(--risk-high)", letterSpacing: "0.2em", fontSize: 10 }}>● TARGET ACQUIRED</span>
            <span style={{ color: "var(--ink)", marginLeft: 12, fontSize: 12 }}>{banner.company}{banner.ticker ? ` · ${banner.ticker}` : ""}</span>
            <span style={{ color: "var(--risk-high)", marginLeft: 12, fontSize: 13 }}>{banner.score.toFixed(2)}</span>
          </div>
        )}

        {/* HUD */}
        <div className="absolute top-3 right-3 flex gap-px" style={{ background: "var(--line-soft)", borderRadius: 6, overflow: "hidden" }}>
          {[["scanned", counts.scanned], ["flagged", counts.flagged], ["elevated", counts.elevated]].map(([k, v]) => (
            <div key={k as string} className="px-3 py-1.5" style={{ background: "color-mix(in oklab, var(--bg) 86%, transparent)", backdropFilter: "blur(6px)" }}>
              <div className="eyebrow" style={{ fontSize: 8 }}>{k}</div>
              <div className="mono text-[15px]" style={{ color: k === "elevated" && (v as number) > 0 ? "var(--risk-high)" : "var(--ink)" }}>{v}</div>
            </div>
          ))}
        </div>
        <div className="absolute bottom-3 left-3 eyebrow" style={{ fontSize: 8, color: "var(--faint)" }}>
          albers usa · {dets.length} live detections · click a target for the dossier
        </div>
      </div>

      {/* detection detail */}
      {selected && (
        <div className="panel p-4 rise" style={{ borderLeft: `2px solid ${riskColor(selected.score)}` }}>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="flex items-center gap-2">
                <span className="mono text-[18px]" style={{ color: riskColor(selected.score) }}>{fmt(selected.score)}</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded mono" style={{ background: `color-mix(in oklab, ${riskColor(selected.score)} 16%, transparent)`, color: riskColor(selected.score) }}>{selected.band}</span>
                <span className="text-[15px]" style={{ fontWeight: 500 }}>{selected.company}</span>
                {selected.ticker && <span className="mono text-[12px]" style={{ color: "var(--faint)" }}>{selected.ticker}</span>}
              </div>
              <div className="text-[12px] mt-1" style={{ color: "var(--muted-solid)" }}>
                {selected.city ? `${selected.city}, ` : ""}{selected.state} · {selected.flags || "scored on forensic signals"}
              </div>
            </div>
            <div className="flex gap-2">
              <a href={`${BASE}/api/dossier.pdf?q=${selected.cik}`} target="_blank" rel="noreferrer"
                className="btn btn-gold px-3.5 py-2 text-[12px]" style={{ borderRadius: 6, fontWeight: 500, textDecoration: "none" }}>
                Download dossier PDF
              </a>
              <button onClick={() => onOpen(selected.ticker || selected.cik, "")}
                className="tap px-3.5 py-2 text-[12px] panel" style={{ borderRadius: 6, color: "var(--ink)" }}>
                Open full analysis
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
