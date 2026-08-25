'use client';

import { useEffect, useState } from 'react';
import {
  loadArtifact, fmt, NOT_MEASURED,
  type DecisionRecord, type GasReport, type MultiseedReport,
  type Phase1Report, type Phase3Report, type Phase5Report, type SweepReport,
} from '@/lib/data';
import { probeChain, type ChainState } from '@/lib/chain';
import ReferenceColumn from './ReferenceColumn';
import DecisionExplorer from './DecisionExplorer';
import SlashPanel from './SlashPanel';
import TrustPanel from './TrustPanel';
import ReliabilityDiagram from './ReliabilityDiagram';

type Tab = 'decisions' | 'slash' | 'trust' | 'artifacts';

export default function Page() {
  const [tab, setTab] = useState<Tab>('decisions');
  const [chain, setChain] = useState<ChainState>({ state: 'checking' });

  const [phase1, setPhase1] = useState<Phase1Report | null>(null);
  const [multiseed, setMultiseed] = useState<MultiseedReport | null>(null);
  const [decisions, setDecisions] = useState<DecisionRecord[] | null>(null);
  const [sweep, setSweep] = useState<SweepReport | null>(null);
  const [gas, setGas] = useState<GasReport | null>(null);
  const [phase3, setPhase3] = useState<Phase3Report | null>(null);
  const [phase5, setPhase5] = useState<Phase5Report | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      const [p1, ms, dec, sw, g, p3, p5] = await Promise.all([
        loadArtifact<Phase1Report>('phase1_report.json', 'calibration report'),
        loadArtifact<MultiseedReport>('multiseed_report.json', 'multi-seed report'),
        loadArtifact<DecisionRecord[]>('per_decision.json', 'per-decision SHAP vectors'),
        loadArtifact<SweepReport>('circuit_sweep.json', 'circuit size sweep'),
        loadArtifact<GasReport>('phase4_gas.json', 'gas measurements'),
        loadArtifact<Phase3Report>('phase3_report.json', 'proving measurements'),
        loadArtifact<Phase5Report>('phase5_report.json', 'end-to-end scenarios'),
      ]);
      if (!alive) return;
      const errs: string[] = [];
      const take = <T,>(r: Awaited<ReturnType<typeof loadArtifact<T>>>, set: (v: T) => void) => {
        if (r.state === 'ok') set(r.data);
        else if (r.state === 'missing') errs.push(`${r.what}: ${r.detail}`);
      };
      take(p1, setPhase1); take(ms, setMultiseed); take(dec, setDecisions);
      take(sw, setSweep); take(g, setGas); take(p3, setPhase3); take(p5, setPhase5);
      setErrors(errs);
      setReady(true);
    })();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    let alive = true;
    probeChain().then((s) => { if (alive) setChain(s); });
    const id = setInterval(() => { probeChain().then((s) => { if (alive) setChain(s); }); }, 12000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const tabs: { id: Tab; label: string }[] = [
    { id: 'decisions', label: 'Decisions' },
    { id: 'slash', label: 'Dispute & slash' },
    { id: 'trust', label: 'Trust boundary' },
    { id: 'artifacts', label: 'Measurements' },
  ];

  return (
    <div className="shell">
      <header className="masthead">
        <div>
          <h1>Brier</h1>
          <p style={{ margin: '4px 0 0', color: 'var(--reference)', fontSize: '0.92rem', maxWidth: '58ch' }}>
            Confidence-calibrated slashing for automated loan decisions. Every figure below is
            either a committed measurement artifact or a live read from chain.
          </p>
        </div>
        <div style={{ fontSize: '0.76rem', color: 'var(--reference)', textAlign: 'right' }}>
          <div className="eyebrow">Only the calibration head is proved</div>
          <div style={{ marginTop: 4, maxWidth: '34ch' }}>
            The base classifier is not in any circuit, and its input logit is unverified.
          </div>
        </div>
      </header>

      <nav className="tabs" role="tablist" aria-label="Sections">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            className="tab"
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            id={`tab-${t.id}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <div className="layout">
        <ReferenceColumn multiseed={multiseed} gas={gas} chain={chain} />

        <main>
          {(chain.state === 'offline' || chain.state === 'no-deployment') && (
            <div className="notice" style={{ marginBottom: 20 }}>
              <strong>
                {chain.state === 'offline' ? 'No chain connected.' : 'No deployment found.'}
              </strong>{' '}
              {chain.detail}
            </div>
          )}

          {errors.length > 0 && (
            <div className="notice" style={{ marginBottom: 20 }}>
              <strong>Some measurement artifacts could not be read.</strong>
              <ul style={{ margin: '8px 0 0', paddingLeft: 18, fontSize: '0.84rem' }}>
                {errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            </div>
          )}

          {!ready && (
            <p style={{ color: 'var(--reference)' }}>Reading committed artifacts…</p>
          )}

          {ready && (
            <>
              <div role="tabpanel" id="panel-decisions" aria-labelledby="tab-decisions" hidden={tab !== 'decisions'}>
                {decisions && phase1 ? (
                  <DecisionExplorer decisions={decisions} phase1={phase1} />
                ) : (
                  <div className="notice">
                    <strong>Decision data unavailable.</strong> The explorer reads real SHAP vectors
                    from <code>artifacts/shap/per_decision.json</code>, generated by{' '}
                    <code>scripts/20_explain.py</code>. No example decisions are shipped in its place.
                  </div>
                )}
              </div>

              <div role="tabpanel" id="panel-slash" aria-labelledby="tab-slash" hidden={tab !== 'slash'}>
                <SlashPanel phase5={phase5} chain={chain} />
              </div>

              <div role="tabpanel" id="panel-trust" aria-labelledby="tab-trust" hidden={tab !== 'trust'}>
                <TrustPanel chain={chain} />
              </div>

              <div role="tabpanel" id="panel-artifacts" aria-labelledby="tab-artifacts" hidden={tab !== 'artifacts'}>
                <Artifacts phase1={phase1} multiseed={multiseed} sweep={sweep} gas={gas} phase3={phase3} />
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

function Artifacts({
  phase1, multiseed, sweep, gas, phase3,
}: {
  phase1: Phase1Report | null;
  multiseed: MultiseedReport | null;
  sweep: SweepReport | null;
  gas: GasReport | null;
  phase3: Phase3Report | null;
}) {
  const sweepOk = sweep?.records.filter((r) => r.verify_ok) ?? [];
  const maxProve = Math.max(...sweepOk.map((r) => r.prove_s ?? 0), 1);

  return (
    <section aria-labelledby="art-h">
      <h2 id="art-h">Measurements</h2>
      <p style={{ color: 'var(--reference)', fontSize: '0.9rem', maxWidth: '64ch', marginTop: 6 }}>
        Produced by the pipeline scripts in the repository. Nothing here is estimated,
        extrapolated, or copied from a paper.
      </p>

      {phase1 && (
        <>
          <h3 style={{ marginTop: 22 }}>Calibration reliability, seed 42</h3>
          <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', marginTop: 12 }}>
            <ReliabilityDiagram bins={phase1.reliability_uncalibrated} ece={phase1.ece.uncalibrated} label="Uncalibrated" tone="trusted" />
            <ReliabilityDiagram bins={phase1.reliability_temperature} ece={phase1.ece.temperature} label={`Temperature scaled, T = ${phase1.temperature.toFixed(2)}`} tone="reference" />
          </div>

          {/* accessibility: the data table the chart guidance requires */}
          <details style={{ marginTop: 14 }}>
            <summary style={{ cursor: 'pointer', fontSize: '0.84rem' }}>
              Bin values as a table
            </summary>
            <div className="scroll-x">
              <table style={{ marginTop: 10 }}>
                <thead>
                  <tr>
                    <th>Bin</th><th className="n">n</th>
                    <th className="n">Mean confidence</th><th className="n">Empirical frequency</th>
                    <th className="n">Deviation</th>
                  </tr>
                </thead>
                <tbody>
                  {phase1.reliability_temperature.filter((b) => b.count > 0).map((b, i) => (
                    <tr key={i}>
                      <td className="num">[{b.bin_lo.toFixed(1)}, {b.bin_hi.toFixed(1)})</td>
                      <td className="n">{b.count}</td>
                      <td className="n">{b.mean_conf!.toFixed(4)}</td>
                      <td className="n">{b.empirical_freq!.toFixed(4)}</td>
                      <td className="n" style={{ color: 'var(--trusted)' }}>
                        {(b.empirical_freq! - b.mean_conf!).toFixed(4)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}

      {multiseed && (
        <>
          <h3 style={{ marginTop: 26 }}>Across {multiseed.n_seeds} pinned seeds</h3>
          <div className="scroll-x">
            <table style={{ marginTop: 10 }}>
              <thead>
                <tr><th>Head</th><th className="n">ECE mean</th><th className="n">± std</th><th className="n">min</th><th className="n">max</th></tr>
              </thead>
              <tbody>
                {(['uncalibrated', 'temperature', 'mlp', 'control_fitted_on_train'] as const).map((k) => {
                  const e = multiseed.summary.ece[k];
                  if (!e) return null;
                  const label = k === 'control_fitted_on_train' ? 'control: fitted on TRAIN' : k;
                  return (
                    <tr key={k}>
                      <td style={{ fontStyle: k.startsWith('control') ? 'italic' : undefined }}>{label}</td>
                      <td className="n"><strong>{fmt.dec(e.mean)}</strong></td>
                      <td className="n">{fmt.dec(e.std)}</td>
                      <td className="n">{fmt.dec(e.min)}</td>
                      <td className="n">{fmt.dec(e.max)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p style={{ fontSize: '0.8rem', color: 'var(--reference)', marginTop: 10, maxWidth: '70ch' }}>
            Temperature scaling has the lower ECE in{' '}
            <span className="num">{multiseed.temperature_beats_mlp_on_ece_in_n_seeds}/{multiseed.n_seeds}</span>{' '}
            seeds — a majority, not a uniform result (paired Wilcoxon p ={' '}
            <span className="num">{multiseed.significance['temperature_vs_mlp_ece']?.p_value.toFixed(5)}</span>).
            Fitting the head on the training split was worse than not calibrating in{' '}
            <span className="num">{multiseed.control_worse_than_uncalibrated_in_n_seeds}/{multiseed.n_seeds}</span> seeds.
          </p>
        </>
      )}

      {sweepOk.length > 0 && (
        <>
          <h3 style={{ marginTop: 26 }}>Circuit size sweep</h3>
          <div className="scroll-x">
            <table style={{ marginTop: 10 }}>
              <thead>
                <tr><th>Head</th><th className="n">Params</th><th className="n">logrows</th><th className="n">Rows used</th><th className="n">Prove</th><th style={{ width: 130 }}>Relative</th></tr>
              </thead>
              <tbody>
                {sweepOk.map((r) => (
                  <tr key={r.name}>
                    <td className="num">{r.name}</td>
                    <td className="n">{fmt.int(r.n_params)}</td>
                    <td className="n">{r.logrows}</td>
                    <td className="n">{fmt.int(r.num_rows_used ?? 0)}</td>
                    <td className="n">{fmt.seconds(r.prove_s ?? 0)}</td>
                    <td>
                      <div className="dev-track">
                        <div className="dev-fill" style={{ width: `${((r.prove_s ?? 0) / maxProve) * 100}%` }} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p style={{ fontSize: '0.8rem', color: 'var(--reference)', marginTop: 10, maxWidth: '70ch' }}>
            Rows used scale linearly with parameters, but proving time does not follow — flat across
            four orders of magnitude, all at logrows {sweep!.distinct_logrows.join(', ')}. The
            largest head fills roughly half the circuit&apos;s capacity, so behaviour above logrows 15
            is <span className="unmeasured">{NOT_MEASURED}</span>.
          </p>
        </>
      )}

      {gas && (
        <>
          <h3 style={{ marginTop: 26 }}>Measured gas</h3>
          <div className="scroll-x">
            <table style={{ marginTop: 10 }}>
              <thead><tr><th>Operation</th><th className="n">Gas</th></tr></thead>
              <tbody>
                {Object.entries(gas.gas).map(([k, v]) => (
                  <tr key={k}><td>{k}</td><td className="n">{fmt.int(v)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {phase3 && (
        <>
          <h3 style={{ marginTop: 26 }}>Proving — EZKL {phase3.ezkl_version}</h3>
          <div className="scroll-x">
            <table style={{ marginTop: 10 }}>
              <thead><tr><th>Metric</th><th>Value</th></tr></thead>
              <tbody>
                {Object.entries(phase3.metrics).map(([k, v]) => (
                  <tr key={k}><td>{k}</td><td className="num">{v}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p style={{ fontSize: '0.8rem', color: 'var(--reference)', marginTop: 10, maxWidth: '70ch' }}>
            These are EZKL/halo2 measurements on an EVM chain. The Solana port proves the
            calibration head as an SP1 program wrapped to Groth16 — a different proving system whose
            timings are <span className="unmeasured">{NOT_MEASURED}</span> because local hardware is
            below the published floor. The figures above do not transfer.
          </p>
        </>
      )}
    </section>
  );
}
