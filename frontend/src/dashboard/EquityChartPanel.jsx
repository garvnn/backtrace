import React, { useMemo } from 'react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from 'recharts';
import { EquityTooltip } from './EquityTooltip';
import { CandleSvgChart } from './CandleSvgChart';

export function EquityChartPanel({
  chartMode,
  setChartMode,
  chartRange,
  setChartRange,
  chartData,
  candleTicker,
  setCandleTicker,
  candleBars,
  candleLoading,
  candleError,
  loading,
  backtestResult,
  formatCurrency,
  onRequestBacktest,
}) {
  const annotated = useMemo(
    () =>
      chartData.map((d, i) => ({
        ...d,
        __idx: i,
        __prevLive: i > 0 ? chartData[i - 1].portfolio_value : null,
      })),
    [chartData]
  );

  const showEquityEmpty = chartMode === 'equity' && chartData.length === 0;
  const showCandleEmpty = chartMode === 'candles' && !candleLoading && (!candleBars || candleBars.length === 0);

  return (
    <div className="card">
      <h2>{chartMode === 'equity' ? 'Equity curve' : 'Price (daily)'}</h2>
      <div className="chart-toolbar">
        <div className="chart-mode-toggle">
          <button
            type="button"
            className={`chart-mode-btn ${chartMode === 'equity' ? 'active' : ''}`}
            onClick={() => setChartMode('equity')}
          >
            Equity
          </button>
          <button
            type="button"
            className={`chart-mode-btn ${chartMode === 'candles' ? 'active' : ''}`}
            onClick={() => setChartMode('candles')}
          >
            Candles
          </button>
        </div>
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
      {chartMode === 'candles' && (
        <div className="candle-ticker-field">
          <label htmlFor="candle-ticker">Symbol</label>
          <input
            id="candle-ticker"
            className="candle-ticker-input"
            value={candleTicker}
            onChange={(e) => setCandleTicker(e.target.value.toUpperCase())}
            maxLength={8}
            autoComplete="off"
          />
        </div>
      )}
      {candleError && <div className="chart-error">{candleError}</div>}
      {chartMode === 'equity' && loading && chartData.length === 0 && !backtestResult ? (
        <div className="loading-placeholder chart-placeholder" style={{ minHeight: 360 }}>
          <div className="skeleton skeleton-chart" />
        </div>
      ) : null}
      {chartMode === 'equity' && annotated.length > 0 ? (
        <ResponsiveContainer width="100%" height={360}>
          <AreaChart data={annotated} margin={{ top: 12, right: 12, left: 4, bottom: 8 }}>
            <defs>
              <linearGradient id="liveAreaGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.45} />
                <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="btAreaGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--text-secondary)" stopOpacity={0.2} />
                <stop offset="100%" stopColor="var(--text-secondary)" stopOpacity={0} />
              </linearGradient>
            </defs>
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
            <Tooltip
              content={<EquityTooltip formatCurrency={formatCurrency} />}
              cursor={{ stroke: 'rgba(130, 160, 195, 0.45)', strokeWidth: 1 }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Area
              type="monotone"
              dataKey="portfolio_value"
              name="Live"
              stroke="var(--accent)"
              strokeWidth={2}
              fill="url(#liveAreaGradient)"
              connectNulls={false}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 0, fill: 'var(--accent)' }}
            />
            <Area
              type="monotone"
              dataKey="backtest_value"
              name="Backtest"
              stroke="var(--text-secondary)"
              strokeWidth={2}
              strokeDasharray="6 4"
              fill="url(#btAreaGradient)"
              connectNulls={false}
              dot={false}
              activeDot={{ r: 3, strokeWidth: 0, fill: 'var(--text-secondary)' }}
            />
          </AreaChart>
        </ResponsiveContainer>
      ) : null}
      {chartMode === 'equity' && showEquityEmpty ? (
        <div className="empty-state chart-placeholder" style={{ minHeight: 320 }}>
          <p>No backtest data yet. Run your first backtest to see strategy performance and compare live vs historical.</p>
          <button type="button" className="empty-state-cta" onClick={onRequestBacktest}>
            Run your first backtest →
          </button>
        </div>
      ) : null}
      {chartMode === 'candles' && candleLoading ? (
        <div className="loading-placeholder chart-placeholder" style={{ minHeight: 360 }}>
          <div className="skeleton skeleton-chart" />
        </div>
      ) : null}
      {chartMode === 'candles' && !candleLoading && candleBars?.length > 0 ? (
        <CandleSvgChart data={candleBars} formatCurrency={formatCurrency} height={360} />
      ) : null}
      {chartMode === 'candles' && showCandleEmpty && !candleError ? (
        <div className="empty-state chart-placeholder" style={{ minHeight: 200 }}>
          <p>No bars returned for this symbol and range.</p>
        </div>
      ) : null}
    </div>
  );
}
