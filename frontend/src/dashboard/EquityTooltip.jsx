import React from 'react';

export function EquityTooltip({ active, payload, label, formatCurrency }) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  const ts = label || row.timestamp;
  const dateStr = ts
    ? new Date(ts).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
    : '—';
  const live = row.portfolio_value;
  const bt = row.backtest_value;
  const prev = row.__prevLive;
  const delta = live != null && prev != null ? live - prev : null;

  return (
    <div className="chart-tooltip-box">
      <div className="chart-tooltip-date">{dateStr}</div>
      {live != null && (
        <div className="chart-tooltip-row">
          <span>Live</span>
          <span className="num-mono">{formatCurrency(live)}</span>
        </div>
      )}
      {delta != null && (
        <div className="chart-tooltip-row">
          <span>Δ vs prior</span>
          <span
            className="num-mono"
            style={{ color: delta >= 0 ? 'var(--positive)' : 'var(--negative)' }}
          >
            {delta >= 0 ? '↑' : '↓'} {formatCurrency(Math.abs(delta))}
          </span>
        </div>
      )}
      {bt != null && (
        <div className="chart-tooltip-row">
          <span>Backtest</span>
          <span className="num-mono">{formatCurrency(bt)}</span>
        </div>
      )}
    </div>
  );
}
