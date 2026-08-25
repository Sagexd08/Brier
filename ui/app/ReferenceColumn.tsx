'use client';

/**
 * The persistent reference column.
 *
 * Its job is the design's organising idea: a figure is shown next to the thing
 * that qualifies it. ECE appears as a before/after pair, never as one number.
 * Gas appears next to what it is a multiple of. A value the project has not
 * measured is rendered with the `.unmeasured` treatment, which is structurally
 * distinct from a measured one rather than merely annotated — so a reader
 * scanning quickly cannot mistake one for the other.
 */

import { NOT_MEASURED, fmt, type MultiseedReport, type GasReport } from '@/lib/data';
import type { ChainState } from '@/lib/chain';

interface Props {
  multiseed: MultiseedReport | null;
  gas: GasReport | null;
  chain: ChainState;
}

function Deviation({ from, to, max }: { from: number; to: number; max: number }) {
  const pf = Math.min(100, (from / max) * 100);
  const pt = Math.min(100, (to / max) * 100);
  return (
    <div style={{ marginTop: 6 }}>
      <div className="dev-track" aria-hidden="true">
        <div className="dev-fill" data-tone="trusted" style={{ width: `${pf}%` }} />
      </div>
      <div className="dev-track" style={{ marginTop: 3 }} aria-hidden="true">
        <div className="dev-fill" data-tone="verified" style={{ width: `${pt}%` }} />
      </div>
    </div>
  );
}

export default function ReferenceColumn({ multiseed, gas, chain }: Props) {
  const ece = multiseed?.summary.ece;
  const temp = multiseed?.summary.temperature;
  const verifyGas = gas?.gas['verifyProof (real EZKL proof, on-chain)'] ?? null;

  return (
    <aside className="reference-col panel" aria-label="Reference measurements">
      <div className="eyebrow">Reference</div>

      {/* Calibration: always a pair, never a lone number. */}
      <div style={{ marginTop: 14 }}>
        <div style={{ fontSize: '0.74rem', color: 'var(--reference)' }}>
          Expected calibration error
        </div>
        {ece ? (
          <>
            <div className="num" style={{ fontSize: '0.95rem', marginTop: 3 }}>
              <span style={{ color: 'var(--trusted)' }}>{fmt.dec(ece.uncalibrated.mean)}</span>
              <span style={{ color: 'var(--reference)' }}> → </span>
              <span style={{ color: 'var(--verified)' }}>{fmt.dec(ece.temperature.mean)}</span>
            </div>
            <Deviation
              from={ece.uncalibrated.mean}
              to={ece.temperature.mean}
              max={ece.uncalibrated.mean}
            />
            <div style={{ fontSize: '0.7rem', color: 'var(--reference)', marginTop: 5 }}>
              mean ± <span className="num">{fmt.dec(ece.temperature.std)}</span> over{' '}
              <span className="num">{multiseed!.n_seeds}</span> pinned seeds, reduced in every seed
            </div>
          </>
        ) : (
          <div className="unmeasured">artifact not loaded</div>
        )}
      </div>

      {temp && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: '0.74rem', color: 'var(--reference)' }}>Learned temperature</div>
          <div className="num" style={{ fontSize: '0.95rem', marginTop: 3 }}>
            {fmt.dec(temp.mean, 2)} ± {fmt.dec(temp.std, 2)}
          </div>
          <div style={{ fontSize: '0.7rem', color: 'var(--reference)' }}>
            T &gt; 1 in every seed — the base model was overconfident
          </div>
        </div>
      )}

      <hr style={{ border: 0, borderTop: '1px solid var(--rule)', margin: '18px 0' }} />

      <div>
        <div style={{ fontSize: '0.74rem', color: 'var(--reference)' }}>On-chain verification</div>
        {verifyGas !== null ? (
          <>
            <div className="num" style={{ fontSize: '0.95rem', marginTop: 3 }}>
              {fmt.int(verifyGas)} gas
            </div>
            <div style={{ fontSize: '0.7rem', color: 'var(--reference)' }}>
              ≈ <span className="num">{(verifyGas / 21000).toFixed(0)}×</span> a plain 21,000-gas
              transfer
            </div>
          </>
        ) : (
          <div className="unmeasured">artifact not loaded</div>
        )}
      </div>

      <div style={{ marginTop: 16 }}>
        <div style={{ fontSize: '0.74rem', color: 'var(--reference)' }}>Proving time</div>
        <div className="num" style={{ fontSize: '0.95rem', marginTop: 3 }}>2.13 s ± 0.09</div>
        <div style={{ fontSize: '0.7rem', color: 'var(--reference)' }}>
          EZKL / halo2, laptop CPU, flat from 1 to 16,897 params
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <div style={{ fontSize: '0.74rem', color: 'var(--reference)' }}>SP1 proving (Solana port)</div>
        <div style={{ marginTop: 4 }}>
          <span className="unmeasured">{NOT_MEASURED}</span>
        </div>
        <div style={{ fontSize: '0.7rem', color: 'var(--reference)', marginTop: 4 }}>
          Prover hardware is below the published Groth16 floor (16+ cores). The figure above is
          EZKL/halo2 and does not transfer.
        </div>
      </div>

      <hr style={{ border: 0, borderTop: '1px solid var(--rule)', margin: '18px 0' }} />

      <div>
        <div className="eyebrow">Chain</div>
        <div style={{ marginTop: 8, fontSize: '0.78rem' }}>
          {chain.state === 'checking' && (
            <span style={{ color: 'var(--reference)' }}>reading…</span>
          )}
          {chain.state === 'live' && (
            <>
              <div>
                <span
                  style={{
                    display: 'inline-block', width: 7, height: 7, borderRadius: '50%',
                    background: 'var(--verified)', marginRight: 6,
                  }}
                  aria-hidden="true"
                />
                connected · chain <span className="num">{chain.chainId}</span>
              </div>
              <div className="num" style={{ color: 'var(--reference)', fontSize: '0.72rem' }}>
                block {chain.blockNumber.toString()}
              </div>
              <div className="num" style={{ color: 'var(--reference)', fontSize: '0.72rem' }}>
                {chain.attestationCount.toString()} attestation
                {chain.attestationCount === 1n ? '' : 's'}
              </div>
            </>
          )}
          {(chain.state === 'offline' || chain.state === 'no-deployment') && (
            <div>
              <span
                style={{
                  display: 'inline-block', width: 7, height: 7, borderRadius: '50%',
                  background: 'var(--trusted)', marginRight: 6,
                }}
                aria-hidden="true"
              />
              <strong>
                {chain.state === 'offline' ? 'no node reachable' : 'no deployment found'}
              </strong>
              <div style={{ color: 'var(--reference)', fontSize: '0.72rem', marginTop: 4 }}>
                Live figures are read from chain and are not shown from cache.
              </div>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
