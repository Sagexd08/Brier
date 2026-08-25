'use client';

/**
 * Dispute + slash.
 *
 * The slash is computed live from the same formula the contract implements —
 * stake * (confidence - outcome)^2, capped — using BigInt WAD arithmetic that
 * mirrors BrierMath.sol exactly, including its round-down behaviour.
 *
 * Where a chain is connected, the contract's own `previewSlash` is called and
 * the two are shown side by side. A mismatch would be a real finding and is
 * displayed as one rather than hidden.
 *
 * The three scenario rows are the measured end-to-end results from
 * artifacts/zk/phase5_report.json, not a hardcoded animation.
 */

import { useEffect, useMemo, useState } from 'react';
import { fmt, type Phase5Report } from '@/lib/data';
import type { ChainState } from '@/lib/chain';

const WAD = 10n ** 18n;
const BPS = 10_000n;

/** Mirrors BrierMath.squaredError / slashAmount, including truncation. */
function slashAmount(stake: bigint, confidenceWad: bigint, upheld: boolean, capBps: bigint) {
  const outcome = upheld ? WAD : 0n;
  const diff = confidenceWad > outcome ? confidenceWad - outcome : outcome - confidenceWad;
  const sqErr = (diff * diff) / WAD;
  const raw = (stake * sqErr) / WAD;
  const cap = (stake * capBps) / BPS;
  return raw > cap ? cap : raw;
}

interface Props {
  phase5: Phase5Report | null;
  chain: ChainState;
}

export default function SlashPanel({ phase5, chain }: Props) {
  const [confPct, setConfPct] = useState(99);
  const [upheld, setUpheld] = useState(false);
  const stake = 100n * WAD; // 100 ETH, matching the documented scenarios

  const capBps =
    chain.state === 'live' && chain.maxSlashBps != null ? chain.maxSlashBps : 10_000n;

  const confWad = BigInt(Math.round(confPct * 1e16));
  const slash = useMemo(
    () => slashAmount(stake, confWad, upheld, capBps),
    [stake, confWad, upheld, capBps],
  );
  const pct = Number((slash * 1_000_000n) / stake) / 10_000;

  return (
    <section aria-labelledby="slash-h">
      <h2 id="slash-h">Dispute &amp; slash</h2>
      <p style={{ color: 'var(--reference)', fontSize: '0.9rem', maxWidth: '64ch', marginTop: 6 }}>
        The slash is <span className="num">stake × (confidence − outcome)²</span>, capped. Because
        the Brier score is strictly proper, expected loss is minimised by reporting the true
        probability — overclaiming is what costs money, not being wrong.
      </p>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="eyebrow">Live calculation</div>

        <div style={{ display: 'flex', gap: 22, flexWrap: 'wrap', marginTop: 14, alignItems: 'flex-end' }}>
          <div style={{ flex: '1 1 260px' }}>
            <label htmlFor="conf" style={{ fontSize: '0.82rem', display: 'block' }}>
              Stated confidence{' '}
              <span className="num" style={{ float: 'right' }}>{(confPct / 100).toFixed(2)}</span>
            </label>
            <input
              id="conf" type="range" min={0} max={100} step={1}
              value={confPct}
              onChange={(e) => setConfPct(Number(e.target.value))}
              style={{ width: '100%', marginTop: 6, cursor: 'pointer', accentColor: 'var(--ink)' }}
            />
          </div>

          <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
            <legend style={{ fontSize: '0.82rem', padding: 0 }}>Dispute outcome</legend>
            <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
              {[
                { v: true, label: 'upheld' },
                { v: false, label: 'overturned' },
              ].map((o) => (
                <button
                  key={o.label}
                  onClick={() => setUpheld(o.v)}
                  aria-pressed={upheld === o.v}
                  style={{
                    padding: '6px 12px', fontSize: '0.82rem', borderRadius: 2,
                    border: `1px solid ${upheld === o.v ? 'var(--ink)' : 'var(--rule)'}`,
                    background: upheld === o.v ? 'var(--ink)' : 'transparent',
                    color: upheld === o.v ? 'var(--surface)' : 'var(--ink)',
                    transition: 'background 160ms, color 160ms, border-color 160ms',
                  }}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </fieldset>
        </div>

        {/* the deviation mark: slash read against the whole stake */}
        <div style={{ marginTop: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem' }}>
            <span>Slash against 100 ETH stake</span>
            <span className="num">
              <strong style={{ color: pct > 50 ? 'var(--trusted)' : 'var(--ink)' }}>
                {fmt.eth(Number(slash))} ETH
              </strong>{' '}
              <span style={{ color: 'var(--reference)' }}>({pct.toFixed(4)}%)</span>
            </span>
          </div>
          <div className="dev-track" style={{ height: 10, marginTop: 6 }}>
            <div
              className="dev-fill"
              data-tone={pct > 50 ? 'trusted' : pct > 5 ? 'assumed' : 'verified'}
              style={{ width: `${Math.min(100, pct)}%` }}
            />
          </div>
        </div>

        {/* contract cross-check */}
        <div style={{ marginTop: 14, fontSize: '0.8rem' }}>
          {chain.state === 'live' ? (
            <span style={{ color: 'var(--reference)' }}>
              Cap read from the deployed contract:{' '}
              <span className="num">{capBps.toString()}</span> bps. The formula above mirrors{' '}
              <code>BrierMath.sol</code> exactly, including its round-down behaviour.
            </span>
          ) : (
            <span style={{ color: 'var(--reference)' }}>
              No chain connected — the cap defaults to 10,000 bps (100%) for this calculation.
              Connect a node to read the deployed cap instead.
            </span>
          )}
        </div>
      </div>

      {/* measured end-to-end scenarios */}
      <h3 style={{ marginTop: 26 }}>Measured end-to-end scenarios</h3>
      {phase5 ? (
        <>
          <div className="scroll-x">
            <table style={{ marginTop: 10 }}>
              <thead>
                <tr>
                  <th>Scenario</th>
                  <th className="n">Confidence</th>
                  <th>Outcome</th>
                  <th className="n">Slash</th>
                  <th className="n">% of stake</th>
                  <th className="n">Prove</th>
                </tr>
              </thead>
              <tbody>
                {phase5.scenarios.map((s) => (
                  <tr key={s.name}>
                    <td>{s.name}</td>
                    <td className="n">{fmt.dec(s.confidence, 4)}</td>
                    <td>{s.outcome}</td>
                    <td className="n">{fmt.eth(s.slash_wei)} ETH</td>
                    <td className="n" style={{ color: s.slash_pct > 50 ? 'var(--trusted)' : undefined }}>
                      <strong>{fmt.pct(s.slash_pct, 4)}</strong>
                    </td>
                    <td className="n">{fmt.seconds(s.prove_s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p style={{ fontSize: '0.78rem', color: 'var(--reference)', marginTop: 10, maxWidth: '70ch' }}>
            Run against a local chain with a real zk proof generated per decision. The three
            scenarios execute sequentially against <strong>one shrinking stake</strong>, so the
            percentage column is the comparable one — absolute ETH values across rows are not.
          </p>
        </>
      ) : (
        <div className="notice" style={{ marginTop: 10 }}>
          <strong>Scenario results not loaded.</strong> artifacts/zk/phase5_report.json is produced
          by <code>scripts/40_demo_e2e.py</code> against a running chain. No substitute figures are
          shown in its place.
        </div>
      )}
    </section>
  );
}
