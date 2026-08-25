'use client';

/**
 * Decision explorer.
 *
 * Every value shown comes from artifacts/shap/per_decision.json and
 * artifacts/calibration/phase1_report.json — 200 real decisions from the
 * held-out test split, with their real SHAP attributions.
 *
 * The confidence is derived here the same way the pipeline derives it
 * (sigmoid of margin / T), and the derivation is shown rather than asserted,
 * so a reviewer can check it against the artifact.
 */

import { useMemo, useState } from 'react';
import { fmt, type DecisionRecord, type Phase1Report } from '@/lib/data';
import ReliabilityDiagram from './ReliabilityDiagram';

interface Props {
  decisions: DecisionRecord[];
  phase1: Phase1Report;
}

const FEATURE_NOTE: Record<string, string> = {
  checking_status: 'Checking account status (0 = <0 DM … 3 = none)',
  duration_months: 'Loan duration in months',
  credit_amount: 'Credit amount requested, DM',
  credit_history: 'Credit history, empirical risk order',
  savings_status: 'Savings account / bonds',
  employment_since: 'Years in present employment',
  installment_rate_pct_income: 'Instalment as % of disposable income',
  other_installment_plans: 'Other instalment plans',
  residence_since: 'Years at present residence',
  age_years: 'Age in years',
  purpose: 'Loan purpose (categorical code)',
  property: 'Property owned',
  housing: 'Housing',
  job: 'Job skill level',
  other_debtors: 'Co-applicant / guarantor',
  n_existing_credits: 'Existing credits at this bank',
  n_liable_maintenance: 'Dependants requiring maintenance',
  telephone: 'Registered telephone',
  foreign_worker: 'Foreign worker',
};

export default function DecisionExplorer({ decisions, phase1 }: Props) {
  const T = phase1.temperature;

  const rows = useMemo(
    () =>
      decisions.map((d) => {
        const pReject = 1 / (1 + Math.exp(-d.margin / T));
        const decision = pReject > 0.5 ? 'REJECT' : 'APPROVE';
        const correct = (pReject > 0.5 ? 1 : 0) === d.label;
        // Confidence the OPERATOR states: P(its own decision is correct).
        const stated = pReject > 0.5 ? pReject : 1 - pReject;
        return { ...d, pReject, decision, correct, stated };
      }),
    [decisions, T],
  );

  const [idx, setIdx] = useState(() => {
    const confidentWrong = rows.findIndex((r) => !r.correct && r.stated > 0.9);
    return confidentWrong >= 0 ? confidentWrong : 0;
  });
  const sel = rows[idx];
  const maxAbs = Math.max(...sel.top5.map((t) => Math.abs(t.shap)), 0.001);

  return (
    <section aria-labelledby="dec-h">
      <h2 id="dec-h">Decision explorer</h2>
      <p style={{ color: 'var(--reference)', fontSize: '0.9rem', maxWidth: '64ch', marginTop: 6 }}>
        {decisions.length} real decisions from the held-out test split of the UCI German Credit
        data. Attributions are exact SHAP values, not approximations.
      </p>

      <div style={{ display: 'flex', gap: 10, alignItems: 'center', margin: '16px 0', flexWrap: 'wrap' }}>
        <label htmlFor="dec-select" style={{ fontSize: '0.82rem' }}>Decision</label>
        <select
          id="dec-select"
          className="num"
          value={idx}
          onChange={(e) => setIdx(Number(e.target.value))}
          style={{
            fontFamily: 'var(--mono)', fontSize: '0.85rem', padding: '6px 8px',
            border: '1px solid var(--rule)', borderRadius: 2, background: 'var(--surface)',
            color: 'var(--ink)', cursor: 'pointer',
          }}
        >
          {rows.map((r, i) => (
            <option key={r.index} value={i}>
              #{String(r.index).padStart(3, '0')} · {r.decision} · conf {r.stated.toFixed(3)} ·{' '}
              {r.correct ? 'correct' : 'WRONG'}
            </option>
          ))}
        </select>
        <span style={{ fontSize: '0.78rem', color: 'var(--reference)' }}>
          {rows.filter((r) => !r.correct).length} of {rows.length} decisions were wrong
        </span>
      </div>

      <div className="explorer-grid">
        <div className="panel fade-in" key={sel.index}>
          {/* derivation, shown not asserted */}
          <div className="eyebrow">Base model → calibration head</div>
          <table style={{ marginTop: 10 }}>
            <tbody>
              <tr>
                <td>Base margin (logit)</td>
                <td className="n">{sel.margin >= 0 ? '+' : ''}{fmt.dec(sel.margin, 4)}</td>
              </tr>
              <tr>
                <td>
                  Calibrated <span className="num">P(reject)</span> = σ(margin / T),{' '}
                  T = <span className="num">{fmt.dec(T, 4)}</span>
                </td>
                <td className="n">{fmt.dec(sel.pReject, 4)}</td>
              </tr>
              <tr>
                <td>Decision</td>
                <td className="n"><strong>{sel.decision}</strong></td>
              </tr>
              <tr>
                <td>Ground truth</td>
                <td className="n">{sel.label === 1 ? 'BAD (reject correct)' : 'GOOD (approve correct)'}</td>
              </tr>
              <tr>
                <td>Stated confidence — P(this decision is correct)</td>
                <td className="n" style={{ color: sel.correct ? 'var(--verified)' : 'var(--trusted)' }}>
                  <strong>{fmt.dec(sel.stated, 4)}</strong>
                </td>
              </tr>
            </tbody>
          </table>

          <div className="eyebrow" style={{ marginTop: 20 }}>SHAP top-5 attributions</div>
          <div style={{ marginTop: 10 }}>
            {sel.top5.map((t) => {
              const w = (Math.abs(t.shap) / maxAbs) * 100;
              const reject = t.shap > 0;
              return (
                <div key={t.feature} style={{ marginBottom: 11 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, fontSize: '0.82rem' }}>
                    <span className="num">{t.feature}</span>
                    <span className="num" style={{ color: reject ? 'var(--trusted)' : 'var(--verified)' }}>
                      {t.shap >= 0 ? '+' : ''}{fmt.dec(t.shap, 4)} → {reject ? 'reject' : 'approve'}
                    </span>
                  </div>
                  {/* centre line = zero attribution; the reference this is read against */}
                  <div style={{ position: 'relative', height: 6, marginTop: 3, background: 'var(--surface-2)', borderRadius: 1 }}>
                    <div style={{ position: 'absolute', left: '50%', top: -2, bottom: -2, width: 1, background: 'var(--reference)' }} aria-hidden="true" />
                    <div
                      className="dev-fill"
                      data-tone={reject ? 'trusted' : 'verified'}
                      style={{
                        position: 'absolute', top: 0, bottom: 0,
                        left: reject ? '50%' : `${50 - w / 2}%`,
                        width: `${w / 2}%`,
                      }}
                    />
                  </div>
                  <div style={{ fontSize: '0.71rem', color: 'var(--reference)', marginTop: 2 }}>
                    {FEATURE_NOTE[t.feature] ?? ''}
                  </div>
                </div>
              );
            })}
          </div>
          <p style={{ fontSize: '0.76rem', color: 'var(--reference)', marginTop: 12 }}>
            The SHAP vector is hashed and committed on chain as evidence. It is{' '}
            <strong>not</strong> zk-proved — the commitment binds the operator to this explanation,
            it does not establish that the explanation describes the model.
          </p>
        </div>

        <div>
          <ReliabilityDiagram
            bins={phase1.reliability_temperature}
            ece={phase1.ece.temperature}
            label="Calibrated, seed 42"
            tone="reference"
            highlightConfidence={sel.pReject}
          />
          <p style={{ fontSize: '0.76rem', color: 'var(--reference)', maxWidth: 330, marginTop: 8 }}>
            The filled marker is the bin this decision falls in. Its distance from the dashed
            diagonal is the calibration error for that bin.
          </p>
        </div>
      </div>
    </section>
  );
}
