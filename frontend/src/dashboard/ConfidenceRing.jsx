import React, { useMemo } from 'react';

export function ConfidenceRing({ monteCarloData, liveSharpe, historyLength }) {
  const { pct, label } = useMemo(() => {
    if (monteCarloData && monteCarloData.probability_profit != null && !monteCarloData.error) {
      return {
        pct: Math.round((monteCarloData.probability_profit ?? 0) * 100),
        label: 'Probability of profit (Monte Carlo)',
      };
    }
    if (historyLength >= 2 && liveSharpe != null && Number.isFinite(liveSharpe)) {
      const s = liveSharpe;
      const mapped = Math.round(Math.min(85, Math.max(40, 50 + s * 12)));
      return {
        pct: mapped,
        label: 'Confidence (estimated from live Sharpe)',
      };
    }
    return { pct: null, label: 'Run a backtest with Monte Carlo or grow history for an estimate.' };
  }, [monteCarloData, liveSharpe, historyLength]);

  const r = 52;
  const c = 64;
  const stroke = 8;
  const circ = 2 * Math.PI * r;
  const dash = pct != null ? (pct / 100) * circ : 0;

  return (
    <div className="confidence-ring-wrap">
      <svg width={c * 2} height={c * 2} viewBox={`0 0 ${c * 2} ${c * 2}`}>
        <circle cx={c} cy={c} r={r} fill="none" stroke="var(--border)" strokeWidth={stroke} />
        {pct != null && (
          <circle
            cx={c}
            cy={c}
            r={r}
            fill="none"
            stroke="var(--accent-muted)"
            strokeWidth={stroke}
            strokeLinecap="butt"
            strokeDasharray={`${dash} ${circ}`}
            transform={`rotate(-90 ${c} ${c})`}
          />
        )}
      </svg>
      {pct != null && <div className="confidence-ring-value">{pct}%</div>}
      <div className="confidence-ring-label">{label}</div>
    </div>
  );
}
