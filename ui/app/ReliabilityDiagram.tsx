'use client';

/**
 * The reliability diagram — this interface's signature element.
 *
 * Every point is a measured bin from artifacts/calibration/phase1_report.json.
 * No curve is fitted, no line is smoothed, and no bin is dropped for looks.
 * Empty bins are absent because they contain no observations, which is also
 * how the repo's ECE implementation treats them (skipped, not counted as
 * perfectly calibrated).
 *
 * The diagonal is the whole point: it is the reference the reading is taken
 * against, and each bin's deviation from it is drawn explicitly as a dropline.
 */

import type { ReliabilityBin } from '@/lib/data';

interface Props {
  bins: ReliabilityBin[];
  ece: number;
  label: string;
  tone: 'reference' | 'trusted';
  /** Bin index to emphasise, when a decision is selected elsewhere. */
  highlightConfidence?: number | null;
}

const W = 300;
const H = 300;
const PAD = 34;

export default function ReliabilityDiagram({
  bins,
  ece,
  label,
  tone,
  highlightConfidence = null,
}: Props) {
  const filled = bins.filter((b) => b.count > 0 && b.mean_conf !== null && b.empirical_freq !== null);
  const maxCount = Math.max(...filled.map((b) => b.count), 1);

  const x = (v: number) => PAD + v * (W - PAD * 2);
  const y = (v: number) => H - PAD - v * (H - PAD * 2);

  const stroke = tone === 'trusted' ? 'var(--trusted)' : 'var(--reference)';

  return (
    <figure style={{ margin: 0 }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        style={{ maxWidth: 340, display: 'block' }}
        role="img"
        aria-label={`Reliability diagram, ${label}. Expected calibration error ${ece.toFixed(4)}. ${filled.length} non-empty bins. A full data table follows.`}
      >
        {/* grid */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <g key={t}>
            <line x1={x(t)} y1={y(0)} x2={x(t)} y2={y(1)} stroke="var(--rule)" strokeWidth="0.5" />
            <line x1={x(0)} y1={y(t)} x2={x(1)} y2={y(t)} stroke="var(--rule)" strokeWidth="0.5" />
          </g>
        ))}

        {/* the reference: perfect calibration */}
        <line
          x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)}
          stroke="var(--ink)" strokeWidth="1.2" strokeDasharray="4 3"
        />

        {/* deviation droplines: the gap ECE actually integrates */}
        {filled.map((b, i) => (
          <line
            key={`d${i}`}
            x1={x(b.mean_conf!)} y1={y(b.mean_conf!)}
            x2={x(b.mean_conf!)} y2={y(b.empirical_freq!)}
            stroke="var(--trusted)" strokeWidth="1" opacity="0.5"
          />
        ))}

        {/* bins, area proportional to observation count */}
        {filled.map((b, i) => {
          const r = 2.5 + (b.count / maxCount) * 7;
          const isHi =
            highlightConfidence !== null &&
            highlightConfidence >= b.bin_lo &&
            highlightConfidence < b.bin_hi;
          return (
            <circle
              key={`c${i}`}
              cx={x(b.mean_conf!)} cy={y(b.empirical_freq!)} r={r}
              fill={isHi ? 'var(--ink)' : stroke}
              stroke="var(--surface)" strokeWidth="1.2"
              opacity={isHi ? 1 : 0.85}
            >
              <title>
                {`bin [${b.bin_lo.toFixed(1)}, ${b.bin_hi.toFixed(1)}) — n=${b.count}, mean confidence ${b.mean_conf!.toFixed(4)}, empirical frequency ${b.empirical_freq!.toFixed(4)}`}
              </title>
            </circle>
          );
        })}

        {/* axes */}
        <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(0)} stroke="var(--reference)" strokeWidth="1" />
        <line x1={x(0)} y1={y(0)} x2={x(0)} y2={y(1)} stroke="var(--reference)" strokeWidth="1" />
        {[0, 0.5, 1].map((t) => (
          <g key={`t${t}`}>
            <text x={x(t)} y={H - PAD + 14} textAnchor="middle" fontSize="9" fill="var(--reference)" fontFamily="var(--mono)">{t.toFixed(1)}</text>
            <text x={PAD - 8} y={y(t) + 3} textAnchor="end" fontSize="9" fill="var(--reference)" fontFamily="var(--mono)">{t.toFixed(1)}</text>
          </g>
        ))}
        <text x={x(0.5)} y={H - 4} textAnchor="middle" fontSize="9.5" fill="var(--reference)">predicted confidence</text>
        <text x={11} y={y(0.5)} textAnchor="middle" fontSize="9.5" fill="var(--reference)" transform={`rotate(-90 11 ${y(0.5)})`}>empirical frequency</text>
      </svg>

      <figcaption style={{ fontSize: '0.8rem', color: 'var(--reference)', marginTop: 6 }}>
        <strong style={{ color: 'var(--ink)' }}>{label}</strong>{' '}
        <span className="num">ECE {ece.toFixed(4)}</span> · {filled.length} non-empty bins ·
        area ∝ observations
      </figcaption>
    </figure>
  );
}
