'use client';

/**
 * The trust model, rendered at the same visual weight as results.
 *
 * This mirrors Figure C in the repository and uses the same three colours for
 * the same three tiers, so a reader moving between the paper and this page does
 * not have to re-learn the code.
 *
 * Two rules govern this component:
 *   1. It must never look more reassuring than the docs allow. An N-of-M
 *      committee is bounded trust, not decentralisation, and it stays in the
 *      red tier.
 *   2. Where a guarantee depends on deployed code, it reports what is actually
 *      deployed on the connected chain — not what the repository contains. The
 *      currently deployed StakePool predates the unbonding and N-of-M work, and
 *      the panel says so rather than crediting the contract with them.
 */

import type { ChainState } from '@/lib/chain';

interface Props {
  chain: ChainState;
}

export default function TrustPanel({ chain }: Props) {
  const live = chain.state === 'live' ? chain : null;
  const hasUnbonding = live?.unbondingPeriod != null;
  const hasCommittee = live?.threshold != null && live?.committeeSize != null;

  return (
    <section aria-labelledby="trust-h">
      <h2 id="trust-h">Trust boundary</h2>
      <p style={{ color: 'var(--reference)', fontSize: '0.9rem', maxWidth: '64ch', marginTop: 6 }}>
        Three tiers of assurance. Only the first is cryptography. This section carries the same
        weight as the results because the results are only meaningful inside these bounds.
      </p>

      {/* ---------------- tier 1 ---------------- */}
      <div className="tier" data-tier="verified" style={{ marginTop: 18 }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <span className="badge" style={{ color: 'var(--verified)' }}>TIER 1</span>
          <strong>Cryptographically guaranteed</strong>
        </div>
        <p style={{ margin: '8px 0 0', fontSize: '0.88rem' }}>
          Holds against a fully malicious operator. The calibration head&apos;s execution is proved
          in zero knowledge (EZKL/halo2, 2<sup>15</sup> rows) and verified on chain; tampered
          proofs, tampered outputs, and wrong verifying keys are all rejected. The slash arithmetic
          is exact fixed-point with no unchecked blocks.
        </p>
        <p
          style={{
            margin: '10px 0 0', fontSize: '0.85rem',
            borderLeft: '2px solid var(--trusted)', paddingLeft: 10,
          }}
        >
          <strong style={{ color: 'var(--trusted)' }}>Not covered:</strong> the base classifier is
          not in any circuit, and the input logit is an unverified operator-supplied value.{' '}
          <strong>An operator that fabricates the logit obtains a proof that verifies.</strong> Any
          claim that &ldquo;the AI decision is zero-knowledge proved&rdquo; is false.
        </p>
      </div>

      {/* ---------------- tier 2 ---------------- */}
      <div className="tier" data-tier="assumed">
        <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <span className="badge" style={{ color: 'var(--assumed)' }}>TIER 2</span>
          <strong>Economically assumed</strong>
        </div>
        <p style={{ margin: '8px 0 0', fontSize: '0.88rem' }}>
          Holds only if the operator is rational <em>and</em> the assumption is enforced in the
          deployed code. Honest confidence reporting is enforced by the payoff structure: the Brier
          score is strictly proper, so expected loss is minimised at the operator&apos;s true belief.
        </p>

        <div style={{ marginTop: 10, fontSize: '0.85rem' }}>
          <strong>Stake availability at slash time — deployed status:</strong>{' '}
          {chain.state !== 'live' ? (
            <span className="unmeasured">cannot read: no chain connected</span>
          ) : hasUnbonding ? (
            <span style={{ color: 'var(--verified)' }}>
              enforced — unbonding period{' '}
              <span className="num">{live!.unbondingPeriod!.toString()}</span> s
            </span>
          ) : (
            <span style={{ color: 'var(--trusted)' }}>
              <strong>not enforced in the deployed contract.</strong> This StakePool exposes no
              unbonding period, so an operator watching the mempool can withdraw before a dispute is
              mined and reduce the slash to zero. The repository contains the fix; this deployment
              predates it.
            </span>
          )}
        </div>

        <p style={{ margin: '10px 0 0', fontSize: '0.82rem', color: 'var(--reference)' }}>
          Two gaps survive even where unbonding <em>is</em> enforced: a decision nobody disputes
          within the window is unbacked once the operator exits, and the freeze is lifted by dispute
          resolution — a tier-3 action.
        </p>
      </div>

      {/* ---------------- tier 3 ---------------- */}
      <div className="tier" data-tier="trusted">
        <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <span className="badge" style={{ color: 'var(--trusted)' }}>TIER 3</span>
          <strong>Fully trusted — no cryptographic or economic guarantee</strong>
        </div>

        <div style={{ marginTop: 8, fontSize: '0.88rem' }}>
          <strong>Dispute resolution — deployed status:</strong>{' '}
          {chain.state !== 'live' ? (
            <span className="unmeasured">cannot read: no chain connected</span>
          ) : hasCommittee ? (
            <>
              <span className="num">
                {live!.threshold!.toString()}-of-{live!.committeeSize!.toString()}
              </span>{' '}
              committee. <strong>This is bounded trust, not decentralisation.</strong> The committee
              is a fixed list the admin can replace, resolvers stake nothing, and{' '}
              <span className="num">{live!.threshold!.toString()}</span> colluding members have
              exactly the power a single admin key had.
            </>
          ) : (
            <>
              <strong>a single admin key</strong> decides every outcome in this deployment. No jury,
              no oracle, no evidentiary standard, no appeal. A dishonest admin can slash a
              well-calibrated operator to zero or shield a miscalibrated one indefinitely.
            </>
          )}
        </div>

        <p style={{ margin: '10px 0 0', fontSize: '0.85rem' }}>
          <strong>Ground truth is unsolved, not merely unimplemented.</strong> For a loan rejection
          the counterfactual is unobservable — a rejected applicant never demonstrates repayment, so
          &ldquo;the decision was wrong&rdquo; has no on-chain referent. Moving from one voter to N
          voters does not create a fact that did not exist.
        </p>
      </div>

      <p style={{ fontSize: '0.8rem', color: 'var(--reference)', marginTop: 14 }}>
        Each weakness above is demonstrated by an executable test in{' '}
        <code>contracts/test/ThreatModel.t.sol</code>, not asserted in prose.
      </p>
    </section>
  );
}
