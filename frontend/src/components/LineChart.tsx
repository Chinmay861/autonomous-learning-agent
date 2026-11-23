import { useEffect, useMemo, useRef, useState } from 'react';

export interface Series {
  key: string;
  label: string;
  color: string;
  values: (number | null)[];
  /** Reference series (e.g. a theoretical minimum): drawn dashed in neutral ink, no direct label. */
  reference?: boolean;
}

interface LineChartProps {
  series: Series[];
  title: string;
  description?: string;
  yFormat: (v: number) => string;
  /** Fixed y-range; otherwise 0 to a nice max of the data. */
  yDomain?: [number, number];
  xLabel?: (index: number) => string;
  height?: number;
}

const MARGIN = { top: 12, right: 76, bottom: 26, left: 44 };
const REFERENCE_INK = '#94a3b8'; // slate-400

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const exponent = Math.floor(Math.log10(value));
  const fraction = value / 10 ** exponent;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  return nice * 10 ** exponent;
}

function pathFor(values: (number | null)[], x: (i: number) => number, y: (v: number) => number): string {
  let d = '';
  let pen = false;
  values.forEach((v, i) => {
    if (v === null || Number.isNaN(v)) {
      pen = false;
      return;
    }
    d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
    pen = true;
  });
  return d;
}

/**
 * Multi-series line chart with a snapping crosshair and one tooltip listing every series.
 * Lines are 2px, the grid is recessive, identity comes from a legend plus direct labels
 * at the line ends, so color is never the only cue.
 */
export function LineChart({ series, title, description, yFormat, yDomain, xLabel, height = 220 }: LineChartProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const length = Math.max(1, ...series.map((s) => s.values.length));
  const dataMax = Math.max(0, ...series.flatMap((s) => s.values.filter((v): v is number => v !== null)));
  const [y0, y1] = yDomain ?? [0, niceMax(dataMax * 1.05)];
  const innerW = width - MARGIN.left - MARGIN.right;
  const innerH = height - MARGIN.top - MARGIN.bottom;
  const x = (i: number) => MARGIN.left + (length <= 1 ? innerW / 2 : (i / (length - 1)) * innerW);
  const y = (v: number) => MARGIN.top + innerH - ((v - y0) / (y1 - y0 || 1)) * innerH;
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((t) => y0 + t * (y1 - y0));
  const xTickCount = Math.min(length, Math.max(2, Math.floor(innerW / 90)));
  const xTicks = Array.from(new Set(
    Array.from({ length: xTickCount }, (_, k) => Math.round((k / Math.max(1, xTickCount - 1)) * (length - 1))),
  ));
  const label = xLabel ?? ((i: number) => `Game ${i + 1}`);
  const hasData = series.some((s) => s.values.some((v) => v !== null));

  // Direct labels at each named series' last point, nudged apart so they never overlap.
  const endLabels = useMemo(() => {
    const items = series
      .filter((s) => !s.reference)
      .map((s) => {
        let last = -1;
        s.values.forEach((v, i) => { if (v !== null) last = i; });
        return last < 0 ? null : { key: s.key, label: s.label, color: s.color, ty: y(s.values[last] as number) };
      })
      .filter((item): item is NonNullable<typeof item> => item !== null)
      .sort((a, b) => a.ty - b.ty);
    for (let i = 1; i < items.length; i++) {
      if (items[i].ty - items[i - 1].ty < 14) items[i].ty = items[i - 1].ty + 14;
    }
    return items;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, width, height, y0, y1]);

  const onPointer = (e: React.PointerEvent<SVGRectElement>) => {
    const rect = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const px = e.clientX - rect.left;
    const i = Math.round(((px - MARGIN.left) / (innerW || 1)) * (length - 1));
    setHover(Math.min(length - 1, Math.max(0, i)));
  };

  const tooltipLeft = hover !== null ? Math.min(x(hover) + 12, width - 190) : 0;

  return (
    <figure className="card p-4">
      <figcaption className="mb-3 flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div>
          <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
          {description && <p className="meta mt-0.5">{description}</p>}
        </div>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-300" aria-label="Legend">
          {series.map((s) => (
            <li key={s.key} className="flex items-center gap-1.5">
              <svg width="16" height="8" aria-hidden="true">
                <line x1="0" y1="4" x2="16" y2="4" stroke={s.reference ? REFERENCE_INK : s.color}
                      strokeWidth="2" strokeDasharray={s.reference ? '3 3' : undefined} />
              </svg>
              {s.label}
            </li>
          ))}
        </ul>
      </figcaption>

      <div ref={wrapRef} className="relative">
        {!hasData ? (
          <div className="flex items-center justify-center text-sm text-slate-400" style={{ height }}>
            No finished games yet.
          </div>
        ) : (
          <svg width={width} height={height} role="img" aria-label={title} className="block max-w-full overflow-visible">
            {yTicks.map((t) => (
              <g key={t}>
                <line x1={MARGIN.left} x2={MARGIN.left + innerW} y1={y(t)} y2={y(t)} stroke="#334155" strokeWidth="1" />
                <text x={MARGIN.left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="fill-slate-400 text-[10px] tabular-nums">
                  {yFormat(t)}
                </text>
              </g>
            ))}
            {xTicks.map((i) => (
              <text key={i} x={x(i)} y={height - 6} textAnchor="middle" className="fill-slate-400 text-[10px] tabular-nums">
                {i + 1}
              </text>
            ))}

            {/* Drawn in reverse so the first series (the one the chart is about) sits on top where lines overlap. */}
            {[...series].reverse().map((s) => (
              <path key={s.key} d={pathFor(s.values, x, y)} fill="none"
                    stroke={s.reference ? REFERENCE_INK : s.color} strokeWidth="2"
                    strokeDasharray={s.reference ? '4 4' : undefined}
                    strokeLinejoin="round" strokeLinecap="round" />
            ))}

            {/* Single points have no line to draw: show them as dots. */}
            {series.map((s) => s.values.map((v, i) => {
              const prev = s.values[i - 1] ?? null;
              const next = s.values[i + 1] ?? null;
              if (v === null || prev !== null || next !== null) return null;
              return <circle key={`${s.key}-${i}`} cx={x(i)} cy={y(v)} r="3" fill={s.reference ? REFERENCE_INK : s.color} />;
            }))}

            {endLabels.map((item) => (
              <text key={item.key} x={MARGIN.left + innerW + 8} y={item.ty} dy="0.32em" className="fill-slate-300 text-[11px] font-medium">
                {item.label}
              </text>
            ))}

            {hover !== null && (
              <g pointerEvents="none">
                <line x1={x(hover)} x2={x(hover)} y1={MARGIN.top} y2={MARGIN.top + innerH} stroke="#94a3b8" strokeWidth="1" />
                {series.map((s) => {
                  const v = s.values[hover];
                  return v === null || v === undefined ? null : (
                    <circle key={s.key} cx={x(hover)} cy={y(v)} r="4.5" fill={s.reference ? REFERENCE_INK : s.color}
                            stroke="#1e293b" strokeWidth="2" />
                  );
                })}
              </g>
            )}

            <rect x={MARGIN.left} y={MARGIN.top} width={Math.max(0, innerW)} height={Math.max(0, innerH)}
                  fill="transparent" onPointerMove={onPointer} onPointerLeave={() => setHover(null)} />
          </svg>
        )}

        {hover !== null && hasData && (
          <div className="pointer-events-none absolute top-2 z-10 w-44 rounded-lg border border-slate-600 bg-slate-900/95 px-3 py-2 text-xs shadow-lg"
               style={{ left: tooltipLeft }}>
            <div className="mb-1 font-semibold text-slate-200">{label(hover)}</div>
            {series.map((s) => {
              const v = s.values[hover];
              return (
                <div key={s.key} className="flex items-center justify-between gap-3 py-0.5">
                  <span className="flex items-center gap-1.5 text-slate-400">
                    <svg width="12" height="6" aria-hidden="true">
                      <line x1="0" y1="3" x2="12" y2="3" stroke={s.reference ? REFERENCE_INK : s.color} strokeWidth="2" />
                    </svg>
                    {s.label}
                  </span>
                  <strong className="tabular-nums text-slate-100">{v === null || v === undefined ? '–' : yFormat(v)}</strong>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </figure>
  );
}
