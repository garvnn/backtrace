import React, { useMemo } from 'react';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

function mergeCurves(curveA, curveB) {
  const aBy = {};
  (curveA || []).forEach((p) => {
    if (p?.timestamp) aBy[p.timestamp] = p.portfolio_value;
  });
  const bBy = {};
  (curveB || []).forEach((p) => {
    if (p?.timestamp) bBy[p.timestamp] = p.portfolio_value;
  });
  const dates = new Set([...Object.keys(aBy), ...Object.keys(bBy)]);
  return [...dates].sort().map((ts) => ({
    timestamp: ts,
    series_a: aBy[ts] ?? null,
    series_b: bBy[ts] ?? null,
  }));
}

/** Forward-fill each series so downsampled curves (different dates) still draw continuous lines. */
function forwardFillTwoSeries(rows) {
  let lastA = null;
  let lastB = null;
  return rows.map((r) => {
    if (r.series_a != null && Number.isFinite(r.series_a)) lastA = r.series_a;
    if (r.series_b != null && Number.isFinite(r.series_b)) lastB = r.series_b;
    return {
      ...r,
      series_a: r.series_a != null ? r.series_a : lastA,
      series_b: r.series_b != null ? r.series_b : lastB,
    };
  });
}

/** Same cutoff as Dashboard `chartData` in App.js */
function filterByChartRange(rows, chartRange) {
  if (!chartRange || chartRange === 'All') return rows;
  const now = new Date();
  const cut = new Date(now);
  if (chartRange === '1M') cut.setMonth(cut.getMonth() - 1);
  else if (chartRange === '3M') cut.setMonth(cut.getMonth() - 3);
  else if (chartRange === '6M') cut.setMonth(cut.getMonth() - 6);
  else if (chartRange === '1Y') cut.setFullYear(cut.getFullYear() - 1);
  const cutStr = cut.toISOString().slice(0, 10);
  return rows.filter((d) => (d.timestamp || '') >= cutStr);
}

function BenchmarkTooltip({ active, payload, label, formatCurrency }) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  const ts = label || row.timestamp;
  const dateStr = ts
    ? new Date(ts).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
    : '—';
  return (
    <div className="chart-tooltip-box">
      <div className="chart-tooltip-date">{dateStr}</div>
      {payload.map((pl) => (
        <div key={pl.dataKey} className="chart-tooltip-row">
          <span>{pl.name}</span>
          <span className="num-mono">{pl.value != null ? formatCurrency(pl.value) : '—'}</span>
        </div>
      ))}
    </div>
  );
}

export function BenchmarkPanel({
  chartRange,
  setChartRange,
  liveBenchmark,
  liveLoading,
  liveError,
  backtestResult,
  formatCurrency,
  formatPercent,
}) {
  const liveVsSpyData = useMemo(() => {
    const merged = forwardFillTwoSeries(
      mergeCurves(liveBenchmark?.live_equity_curve, liveBenchmark?.spy_equity_curve)
    );
    return merged.map((d) => ({
      ...d,
      live_value: d.series_a,
      spy_value: d.series_b,
    }));
  }, [liveBenchmark]);

  const backtestVsSpyData = useMemo(() => {
    const strat = backtestResult?.equity_curve;
    const spy = backtestResult?.benchmark?.equity_curve;
    const merged = forwardFillTwoSeries(mergeCurves(strat, spy)).map((d) => ({
      ...d,
      strategy_value: d.series_a,
      spy_bt_value: d.series_b,
    }));
    return filterByChartRange(merged, chartRange);
  }, [backtestResult, chartRange]);

  const liveM = liveBenchmark?.live;
  const spyM = liveBenchmark?.spy;

  return (
    <div className="card benchmark-panel">
      <h2>Benchmark vs SPY</h2>
      <p className="benchmark-note">
        Compares your <strong>live</strong> portfolio (rebased to <strong>$100,000</strong> at the start of the window) and your{' '}
        <strong>last backtest</strong> against SPY buy-and-hold. Range matches the Dashboard equity chart selector.
      </p>
      <div className="chart-toolbar benchmark-toolbar">
        <div className="chart-range">
          {['1M', '3M', '6M', '1Y', 'All'].map((r) => (
            <button
              key={r}
              type="button"
              className={`chart-range-btn ${chartRange === r ? 'active' : ''}`}
              onClick={() => setChartRange(r)}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      <div className="benchmark-metrics-grid">
        <div className="benchmark-metric-block">
          <h3>Live (window)</h3>
          {liveError ? (
            <p className="chart-error" style={{ fontSize: '0.9rem', lineHeight: 1.45 }}>
              <strong>Benchmark request failed.</strong> Set <code className="num-mono">REACT_APP_API_URL</code> on Vercel to your
              Railway API and redeploy the API so <code className="num-mono">GET /live-benchmark</code> is available.
              <br />
              <span className="num-mono" style={{ display: 'block', marginTop: '0.5rem' }}>
                {liveError}
              </span>
            </p>
          ) : liveLoading && !liveM ? (
            <p className="empty-placeholder">Loading…</p>
          ) : liveM ? (
            <>
              {liveM.no_history ? (
                <p className="empty-placeholder" style={{ marginBottom: '0.75rem' }}>
                  No portfolio snapshots in the database for this range. SPY metrics still reflect the market window.
                </p>
              ) : null}
              <ul className="benchmark-metric-list">
                <li>
                  <span>Total return</span> <strong className="num-mono">{formatPercent(liveM.total_return ?? 0)}</strong>
                </li>
                <li>
                  <span>Sharpe</span> <strong className="num-mono">{(liveM.sharpe_ratio ?? 0).toFixed(2)}</strong>
                </li>
                <li>
                  <span>Max drawdown</span>{' '}
                  <strong className="num-mono">{formatPercent(liveM.max_drawdown ?? 0)}</strong>
                </li>
                <li>
                  <span>Trades</span> <strong className="num-mono">{liveM.num_trades ?? '—'}</strong>
                </li>
                <li>
                  <span>Avg return / trade</span>{' '}
                  <strong className="num-mono">
                    {liveM.avg_return_per_trade != null ? formatPercent(liveM.avg_return_per_trade) : 'N/A'}
                  </strong>
                </li>
              </ul>
            </>
          ) : (
            <p className="empty-placeholder">No portfolio history in this range.</p>
          )}
        </div>
        <div className="benchmark-metric-block">
          <h3>SPY (same window)</h3>
          {liveError ? (
            <p className="empty-placeholder">—</p>
          ) : !spyM ? (
            <p className="empty-placeholder">{liveLoading ? 'Loading…' : 'No SPY data.'}</p>
          ) : (
            <ul className="benchmark-metric-list">
              <li>
                <span>Total return</span> <strong className="num-mono">{formatPercent(spyM.total_return ?? 0)}</strong>
              </li>
              <li>
                <span>Sharpe</span> <strong className="num-mono">{(spyM.sharpe_ratio ?? 0).toFixed(2)}</strong>
              </li>
              <li>
                <span>Max drawdown</span>{' '}
                <strong className="num-mono">{formatPercent(spyM.max_drawdown ?? 0)}</strong>
              </li>
            </ul>
          )}
        </div>
        <div className="benchmark-metric-block">
          <h3>Last backtest</h3>
          {!backtestResult?.benchmark ? (
            <p className="empty-placeholder">Run a backtest on the Backtest tab to see strategy vs SPY.</p>
          ) : (
            <ul className="benchmark-metric-list">
              <li>
                <span>Total return</span>{' '}
                <strong className="num-mono">{formatPercent(backtestResult.total_return ?? 0)}</strong>
              </li>
              <li>
                <span>Sharpe</span>{' '}
                <strong className="num-mono">{(backtestResult.sharpe_ratio ?? 0).toFixed(2)}</strong>
              </li>
              <li>
                <span>Max drawdown</span>{' '}
                <strong className="num-mono">{formatPercent(backtestResult.max_drawdown ?? 0)}</strong>
              </li>
              <li>
                <span>Trades</span> <strong className="num-mono">{backtestResult.num_trades ?? '—'}</strong>
              </li>
              <li>
                <span>Avg return / trade</span>{' '}
                <strong className="num-mono">
                  {backtestResult.avg_return_per_trade != null ? formatPercent(backtestResult.avg_return_per_trade) : 'N/A'}
                </strong>
              </li>
            </ul>
          )}
        </div>
        <div className="benchmark-metric-block">
          <h3>SPY (backtest period)</h3>
          {!backtestResult?.benchmark ? (
            <p className="empty-placeholder">—</p>
          ) : (
            <ul className="benchmark-metric-list">
              <li>
                <span>Total return</span>{' '}
                <strong className="num-mono">{formatPercent(backtestResult.benchmark.total_return ?? 0)}</strong>
              </li>
              <li>
                <span>Sharpe</span>{' '}
                <strong className="num-mono">{(backtestResult.benchmark.sharpe_ratio ?? 0).toFixed(2)}</strong>
              </li>
              <li>
                <span>Max drawdown</span>{' '}
                <strong className="num-mono">{formatPercent(backtestResult.benchmark.max_drawdown ?? 0)}</strong>
              </li>
            </ul>
          )}
        </div>
      </div>

      {liveVsSpyData.length > 1 && (
        <div className="benchmark-chart-wrap">
          <h3 className="benchmark-chart-title">Live vs SPY (equity)</h3>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={liveVsSpyData} margin={{ top: 8, right: 12, left: 4, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" vertical={false} />
              <XAxis
                dataKey="timestamp"
                tickFormatter={(ts) =>
                  ts ? new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: '2-digit' }) : ''
                }
                stroke="var(--text-secondary)"
                tick={{ fontSize: 11, fill: 'var(--text-secondary)' }}
                tickLine={false}
                axisLine={{ stroke: 'var(--border)' }}
              />
              <YAxis
                tickFormatter={(v) => (v != null ? `$${(v / 1000).toFixed(0)}k` : '')}
                stroke="var(--text-secondary)"
                tick={{ fontSize: 11, fill: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}
                tickLine={false}
                axisLine={{ stroke: 'var(--border)' }}
                width={56}
              />
              <Tooltip content={<BenchmarkTooltip formatCurrency={formatCurrency} />} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="live_value" name="Live (rebased)" stroke="var(--chart-line-live)" dot={false} strokeWidth={1.5} connectNulls />
              <Line type="monotone" dataKey="spy_value" name="SPY" stroke="#94a3b8" dot={false} strokeWidth={1.5} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {backtestVsSpyData.length > 1 && (
        <div className="benchmark-chart-wrap">
          <h3 className="benchmark-chart-title">Last backtest vs SPY (equity)</h3>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={backtestVsSpyData} margin={{ top: 8, right: 12, left: 4, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" vertical={false} />
              <XAxis
                dataKey="timestamp"
                tickFormatter={(ts) =>
                  ts ? new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: '2-digit' }) : ''
                }
                stroke="var(--text-secondary)"
                tick={{ fontSize: 11, fill: 'var(--text-secondary)' }}
                tickLine={false}
                axisLine={{ stroke: 'var(--border)' }}
              />
              <YAxis
                tickFormatter={(v) => (v != null ? `$${(v / 1000).toFixed(0)}k` : '')}
                stroke="var(--text-secondary)"
                tick={{ fontSize: 11, fill: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}
                tickLine={false}
                axisLine={{ stroke: 'var(--border)' }}
                width={56}
              />
              <Tooltip content={<BenchmarkTooltip formatCurrency={formatCurrency} />} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey="strategy_value"
                name="Backtest"
                stroke="var(--chart-line-bt)"
                dot={false}
                strokeWidth={1.5}
                connectNulls
              />
              <Line type="monotone" dataKey="spy_bt_value" name="SPY" stroke="#94a3b8" dot={false} strokeWidth={1.5} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
