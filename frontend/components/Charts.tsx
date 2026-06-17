"use client";
import { Benford, ForensicSeries, riskColor } from "@/lib/api";

function polar(cx: number, cy: number, r: number, deg: number) {
  const a = ((deg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
}
function arc(cx: number, cy: number, r: number, start: number, end: number) {
  const s = polar(cx, cy, r, end);
  const e = polar(cx, cy, r, start);
  const large = end - start <= 180 ? 0 : 1;
  return `M ${s.x} ${s.y} A ${r} ${r} 0 ${large} 0 ${e.x} ${e.y}`;
}

export function RiskGauge({ value, band, confidence }: { value: number; band: string; confidence: number }) {
  const START = -135, END = 135, SPAN = END - START;
  const valEnd = START + SPAN * Math.max(0, Math.min(1, value));
  const color = riskColor(value);
  return (
    <div className="relative">
      <svg viewBox="0 0 220 200" className="w-full">
        <path d={arc(110, 110, 82, START, END)} fill="none" stroke="#221f19" strokeWidth="14" strokeLinecap="round" />
        <path d={arc(110, 110, 82, START, valEnd)} fill="none" stroke={color} strokeWidth="14" strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 600ms var(--ease)" }} />
        {[0.4, 0.66].map((t) => {
          const p = polar(110, 110, 82, START + SPAN * t);
          return <circle key={t} cx={p.x} cy={p.y} r="1.6" fill="#3a352c" />;
        })}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center" style={{ top: 6 }}>
        <div className="text-5xl font-bold mono" style={{ color }}>{value.toFixed(2)}</div>
        <div className="text-sm font-semibold tracking-wide mt-1" style={{ color }}>{band}</div>
        <div className="text-[11px] mt-0.5" style={{ color: "var(--muted)" }}>confidence {confidence.toFixed(2)}</div>
      </div>
    </div>
  );
}

const MOD_COLORS: Record<string, string> = {
  tabular: "#e6b24a", temporal: "#9b8aa6", text: "#57b39c", benford: "#c98a5a", graph: "#7e8ba0",
};

export function ContributionDonut({ contributions }: { contributions: Record<string, number> }) {
  const entries = Object.entries(contributions).filter(([, v]) => v > 0);
  const total = entries.reduce((s, [, v]) => s + v, 0) || 1;
  let acc = 0;
  const r = 52, cx = 60, cy = 60, C = 2 * Math.PI * r;
  return (
    <div className="flex items-center gap-4">
      <svg viewBox="0 0 120 120" width="118" height="118" className="shrink-0 -rotate-90">
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="#16202e" strokeWidth="14" />
        {entries.map(([k, v]) => {
          const frac = v / total;
          const seg = (
            <circle key={k} cx={cx} cy={cy} r={r} fill="none" stroke={MOD_COLORS[k] ?? "#888"}
              strokeWidth="14" strokeDasharray={`${frac * C} ${C}`} strokeDashoffset={-acc * C} />
          );
          acc += frac;
          return seg;
        })}
      </svg>
      <div className="text-[12px] space-y-1.5 flex-1">
        {entries.sort((a, b) => b[1] - a[1]).map(([k, v]) => (
          <div key={k} className="flex justify-between">
            <span><i className="inline-block w-2.5 h-2.5 rounded-sm mr-2 align-middle"
              style={{ background: MOD_COLORS[k] ?? "#888" }} />{k}</span>
            <span className="mono" style={{ color: "var(--muted)" }}>{Math.round((v / total) * 100)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function BenfordChart({ b }: { b: Benford | null }) {
  if (!b) return <div className="text-[12px]" style={{ color: "var(--muted)" }}>Insufficient numeric population for Benford.</div>;
  const W = 560, H = 170, pad = 28;
  const max = Math.max(...b.observed, ...b.expected) * 1.15;
  const x = (i: number) => pad + (i * (W - pad - 10)) / 9;
  const y = (v: number) => H - pad - (v / max) * (H - pad - 14);
  const bw = (W - pad - 10) / 9 - 8;
  const barColor = b.conformity === "nonconformity" ? "#cf5a40" : "#57b39c";
  const line = b.expected.map((v, i) => `${x(i) + bw / 2},${y(v)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
      {b.observed.map((v, i) => (
        <rect key={i} x={x(i)} y={y(v)} width={bw} height={H - pad - y(v)} rx="2" fill={barColor} opacity={0.8} />
      ))}
      <polyline points={line} fill="none" stroke="#e6b24a" strokeWidth="1.5" />
      {b.expected.map((v, i) => <circle key={i} cx={x(i) + bw / 2} cy={y(v)} r="2" fill="#e6b24a" />)}
      {b.digits.map((d, i) => (
        <text key={d} x={x(i) + bw / 2} y={H - 8} textAnchor="middle" fontSize="11" fill="#6c675e">{d}</text>
      ))}
    </svg>
  );
}

export function TrendChart({ series }: { series: ForensicSeries }) {
  const fye = (series.fye as unknown as string[]) ?? [];
  const yrs = fye.map((d) => (typeof d === "string" ? d.slice(0, 4) : d));
  const m = (series.m_score ?? []) as (number | null)[];
  const acc = (series.accruals_to_ta ?? []) as (number | null)[];
  const dso = (series.dso ?? []) as (number | null)[];
  const W = 560, H = 170, pad = 30;
  const n = yrs.length || 1;
  const x = (i: number) => pad + (i * (W - pad - 10)) / Math.max(1, n - 1);
  const vals = [...m, ...acc].filter((v): v is number => v != null);
  const lo = Math.min(-3, ...vals), hi = Math.max(2, ...vals);
  const yL = (v: number) => H - pad - ((v - lo) / (hi - lo)) * (H - pad - 14);
  const dsoMax = Math.max(1, ...dso.filter((v): v is number => v != null));
  const yR = (v: number) => H - pad - (v / dsoMax) * (H - pad - 14);
  const bw = (W - pad - 10) / Math.max(1, n) - 6;
  const path = (arr: (number | null)[]) =>
    arr.map((v, i) => (v == null ? null : `${x(i)},${yL(v)}`)).filter(Boolean).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
      <line x1={pad} y1={yL(-1.78)} x2={W - 10} y2={yL(-1.78)} stroke="#cf5a40" strokeWidth="1" strokeDasharray="3 4" opacity={0.5} />
      {dso.map((v, i) => v == null ? null : (
        <rect key={i} x={x(i) - bw / 2} y={yR(v)} width={bw} height={H - pad - yR(v)} fill="#7e8ba0" opacity={0.14} />
      ))}
      <polyline points={path(m)} fill="none" stroke="#57b39c" strokeWidth="1.75" />
      <polyline points={path(acc.map((v) => (v == null ? null : v * 10)))} fill="none" stroke="#e6b24a" strokeWidth="1.75" />
      {yrs.map((yr, i) => (i % 2 === 0 ?
        <text key={i} x={x(i)} y={H - 8} textAnchor="middle" fontSize="10" fill="#6c675e">{yr}</text> : null))}
      <text x={pad} y={12} className="mono" fontSize="9.5" fill="#57b39c">beneish m</text>
      <text x={pad + 66} y={12} className="mono" fontSize="9.5" fill="#e6b24a">accruals/ta</text>
      <text x={pad + 150} y={12} className="mono" fontSize="9.5" fill="#7e8ba0">dso</text>
      <line x1={pad} y1={yL(-1.78)} x2={pad + 2} y2={yL(-1.78)} stroke="#cf5a40" />
    </svg>
  );
}
