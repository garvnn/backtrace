import React, { useState, useEffect, useRef } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import './App.css';

const API_BASE = 'http://localhost:8000';

function App() {
  const [portfolio, setPortfolio] = useState(null);
  const [trades, setTrades] = useState([]);
  const [performance, setPerformance] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tickerInput, setTickerInput] = useState('AAPL');
  const [backtestResult, setBacktestResult] = useState(null);
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [backtestError, setBacktestError] = useState(null);
  const [executorLoading, setExecutorLoading] = useState(false);
  const [executorError, setExecutorError] = useState(null);
  const [strategySelect, setStrategySelect] = useState('Momentum');
  const [shortMa, setShortMa] = useState(50);
  const [longMa, setLongMa] = useState(200);
  const [lookbackPeriod, setLookbackPeriod] = useState(120);
  const shortMaRef = useRef(null);
  const longMaRef = useRef(null);
  const lookbackRef = useRef(null);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60000); // Refresh every minute
    return () => clearInterval(interval);
  }, []);

  const fetchData = async () => {
    try {
      setError(null);
      const portfolioRes = await fetch(`${API_BASE}/portfolio`);
      if (!portfolioRes.ok) throw new Error('Failed to fetch portfolio');
      const portfolioData = await portfolioRes.json();
      setPortfolio(portfolioData);

      const tradesRes = await fetch(`${API_BASE}/trades`);
      if (!tradesRes.ok) throw new Error('Failed to fetch trades');
      const tradesData = await tradesRes.json();
      setTrades(tradesData.trades);

      const perfRes = await fetch(`${API_BASE}/performance`);
      if (!perfRes.ok) throw new Error('Failed to fetch performance');
      const perfData = await perfRes.json();
      setPerformance(perfData);

      const historyRes = await fetch(`${API_BASE}/portfolio-history`);
      if (!historyRes.ok) throw new Error('Failed to fetch history');
      const historyData = await historyRes.json();
      setHistory(historyData.history);
    } catch (err) {
      console.error('Error fetching data:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const formatCurrency = (value) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  };

  const formatPercent = (value) => {
    return (value * 100).toFixed(2) + '%';
  };

  const runExecutor = async () => {
    setExecutorError(null);
    setExecutorLoading(true);
    const sw = shortMaRef.current ? Number(shortMaRef.current.value) : shortMa;
    const lw = longMaRef.current ? Number(longMaRef.current.value) : longMa;
    const lb = lookbackRef.current ? Number(lookbackRef.current.value) : lookbackPeriod;
    try {
      const body = {
        strategy: strategySelect,
        ticker: tickerInput.trim().toUpperCase() || 'AAPL',
        short_window: sw || 50,
        long_window: lw || 200,
        lookback_period: lb || 120,
      };
      const res = await fetch(`${API_BASE}/run-executor`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Run failed');
      await fetchData();
    } catch (err) {
      setExecutorError(err.message);
    } finally {
      setExecutorLoading(false);
    }
  };

  const loadBacktest = async () => {
    const ticker = tickerInput.trim().toUpperCase();
    if (!ticker) return;
    setBacktestError(null);
    setBacktestLoading(true);
    const sw = shortMaRef.current ? Number(shortMaRef.current.value) : shortMa;
    const lw = longMaRef.current ? Number(longMaRef.current.value) : longMa;
    const lb = lookbackRef.current ? Number(lookbackRef.current.value) : lookbackPeriod;
    try {
      const body = {
        ticker,
        start_date: '2020-01-01',
        end_date: '2024-12-31',
        strategy: strategySelect,
        short_window: sw || 50,
        long_window: lw || 200,
        lookback_period: lb || 120,
      };
      const res = await fetch(`${API_BASE}/backtest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg = Array.isArray(data.detail)
          ? (data.detail[0]?.msg || JSON.stringify(data.detail))
          : (typeof data.detail === 'string' ? data.detail : data.detail || 'Backtest failed');
        throw new Error(msg);
      }
      if (data && (data.equity_curve !== undefined || data.total_return !== undefined)) {
        setBacktestResult(data);
      } else {
        setBacktestResult(null);
        setBacktestError('Backtest returned no data.');
      }
    } catch (err) {
      setBacktestError(err.message || 'Backtest failed');
      setBacktestResult(null);
    } finally {
      setBacktestLoading(false);
    }
  };

  // Combined chart data: live + backtest (backtest scaled to same start as live)
  const chartData = (() => {
    const backtestCurve = backtestResult?.equity_curve || [];
    const liveStart = history.length > 0 ? history[0].portfolio_value : 100000;
    const liveByDate = {};
    history.forEach(h => { const d = (h.timestamp || '').slice(0, 10); if (d) liveByDate[d] = h.portfolio_value; });
    if (backtestCurve.length === 0) return history.map(h => ({ timestamp: (h.timestamp || '').slice(0, 10) || h.timestamp, portfolio_value: h.portfolio_value, backtest_value: null }));
    const btFirst = backtestCurve[0].portfolio_value;
    const scale = btFirst > 0 ? liveStart / btFirst : 1;
    const btByDate = {};
    backtestCurve.forEach(p => { btByDate[p.timestamp] = p.portfolio_value * scale; });
    const dates = new Set([...Object.keys(liveByDate), ...backtestCurve.map(p => p.timestamp)]);
    return [...dates].sort().map(ts => ({
      timestamp: ts,
      portfolio_value: liveByDate[ts] ?? null,
      backtest_value: btByDate[ts] ?? null,
    }));
  })();

  return (
    <div className="App">
      <header>
        <h1>BackTrace Live</h1>
        <p>Backtest vs Reality</p>
        <div className="strategy-controls">
          <label className="strategy-label">Strategy</label>
          <select
            value={strategySelect}
            onChange={(e) => setStrategySelect(e.target.value)}
            className="strategy-select"
            disabled={backtestLoading || executorLoading}
          >
            <option value="Momentum">Momentum</option>
            <option value="MA Crossover">MA Crossover</option>
          </select>
          {strategySelect === 'MA Crossover' && (
            <>
              <label className="param-label">Short MA (days)</label>
              <input
                ref={shortMaRef}
                type="number"
                min={1}
                max={500}
                value={shortMa}
                onChange={(e) => setShortMa(Number(e.target.value) || 50)}
                className="param-input"
              />
              <label className="param-label">Long MA (days)</label>
              <input
                ref={longMaRef}
                type="number"
                min={1}
                max={500}
                value={longMa}
                onChange={(e) => setLongMa(Number(e.target.value) || 200)}
                className="param-input"
              />
            </>
          )}
          {strategySelect === 'Momentum' && (
            <>
              <label className="param-label">Lookback (days)</label>
              <input
                ref={lookbackRef}
                type="number"
                min={1}
                max={500}
                value={lookbackPeriod}
                onChange={(e) => setLookbackPeriod(Number(e.target.value) || 120)}
                className="param-input"
              />
            </>
          )}
        </div>
        <div className="ticker-load">
          <input
            type="text"
            value={tickerInput}
            onChange={(e) => setTickerInput(e.target.value)}
            placeholder="e.g. AAPL"
            className="ticker-input"
            disabled={backtestLoading}
          />
          <button type="button" onClick={loadBacktest} disabled={backtestLoading} className="load-backtest-btn">
            {backtestLoading ? 'Running…' : 'Load backtest'}
          </button>
          {backtestError && <span className="backtest-error">{backtestError}</span>}
          <button type="button" onClick={runExecutor} disabled={executorLoading} className="run-executor-btn">
            {executorLoading ? 'Running…' : 'Run strategy now'}
          </button>
          {executorError && <span className="backtest-error">{executorError}</span>}
        </div>
      </header>

      {error && (
        <div className="error-banner">
          Unable to load data. Retrying in 60s.
        </div>
      )}

      <div className="container">
        <div className="card strategy-help chart-card">
          <h2>How the strategies work</h2>
          {strategySelect === 'MA Crossover' ? (
            <div className="help-content">
              <p><strong>MA Crossover (moving average crossover)</strong></p>
              <p><strong>Short MA</strong> and <strong>Long MA</strong> are the number of trading days used to compute two moving averages of the stock&apos;s closing price. The short MA reacts faster to recent prices; the long MA is smoother.</p>
              <p><strong>Buy:</strong> when the short MA crosses above the long MA (short &gt; long). That often means recent momentum is turning up. <strong>Sell:</strong> when the short MA crosses below the long MA (short &lt; long).</p>
              <p>Example: 50/200 means buy when the 50-day average is above the 200-day average. Smaller short (e.g. 20) gives more frequent signals; larger short (e.g. 100) gives fewer, slower signals.</p>
            </div>
          ) : (
            <div className="help-content">
              <p><strong>Momentum</strong></p>
              <p>The strategy looks at the stock&apos;s <strong>total return over the last N days</strong> (the lookback). If that return is positive, it goes long; if negative, it goes to cash.</p>
              <p><strong>Lookback (days)</strong> is that N: e.g. 120 ≈ 6 months of trading days. Shorter lookback (e.g. 30) reacts faster to recent performance but can whipsaw. Longer lookback (e.g. 252 ≈ 1 year) trades less often and follows longer-term trend.</p>
            </div>
          )}
        </div>
        {/* Portfolio Summary */}
        <div className="card">
          <h2>Current Portfolio</h2>
          {loading && !portfolio ? (
            <div className="loading-placeholder">Loading...</div>
          ) : portfolio ? (
            <div className="stats">
              <div className="stat">
                <span className="label">Portfolio Value</span>
                <span className="value">{formatCurrency(portfolio.portfolio_value)}</span>
              </div>
              <div className="stat">
                <span className="label">Cash</span>
                <span className="value">{formatCurrency(portfolio.cash)}</span>
              </div>
              <div className="stat">
                <span className="label">Strategy</span>
                <span className="value">{portfolio.strategy ?? '—'}</span>
              </div>
            </div>
          ) : (
            <div className="empty-placeholder">No portfolio data</div>
          )}
        </div>

        {/* Performance Metrics */}
        <div className="card">
          <h2>Performance Metrics</h2>
          {loading && !performance ? (
            <div className="loading-placeholder">Loading...</div>
          ) : performance ? (
            <div className="stats">
              <div className="stat">
                <span className="label">Total Return</span>
                <span className={`value ${performance.total_return >= 0 ? 'positive' : 'negative'}`}>
                  {formatPercent(performance.total_return)}
                </span>
              </div>
              <div className="stat">
                <span className="label">Number of Trades</span>
                <span className="value">{performance.num_trades}</span>
              </div>
              <div className="stat">
                <span className="label">Current Value</span>
                <span className="value">{formatCurrency(performance.current_value)}</span>
              </div>
              <div className="stat">
                <span className="label">Initial Value</span>
                <span className="value">
                  {performance.initial_value != null ? formatCurrency(performance.initial_value) : '—'}
                </span>
              </div>
            </div>
          ) : (
            <div className="empty-placeholder">No performance data</div>
          )}
        </div>

        {/* Backtest Results */}
        <div className="card">
          <h2>Backtest Results {backtestResult?.ticker && `(${backtestResult.ticker})`}</h2>
          {backtestResult && (backtestResult.total_return !== undefined || backtestResult.equity_curve) ? (
            <div className="stats">
              {backtestResult.params_used && (
                <div className="stat params-used">
                  <span className="label">Params used</span>
                  <span className="value params-text">
                    {backtestResult.params_used.strategy === 'MeanReversion'
                      ? `Short MA ${backtestResult.params_used.short_window}, Long MA ${backtestResult.params_used.long_window}`
                      : `Lookback ${backtestResult.params_used.lookback_period} days`}
                  </span>
                </div>
              )}
              <div className="stat">
                <span className="label">Total Return</span>
                <span className={`value ${(backtestResult.total_return ?? 0) >= 0 ? 'positive' : 'negative'}`}>
                  {formatPercent(backtestResult.total_return ?? 0)}
                </span>
              </div>
              <div className="stat">
                <span className="label">Sharpe Ratio</span>
                <span className="value">{Number(backtestResult.sharpe_ratio ?? 0).toFixed(2)}</span>
              </div>
              <div className="stat">
                <span className="label">Max Drawdown</span>
                <span className="value negative">{formatPercent(backtestResult.max_drawdown ?? 0)}</span>
              </div>
              <div className="stat">
                <span className="label">Number of Trades</span>
                <span className="value">{backtestResult.num_trades ?? 0}</span>
              </div>
            </div>
          ) : (
            <div className="empty-placeholder">Enter a ticker and click Load backtest</div>
          )}
        </div>

        {/* Comparison */}
        {backtestResult && (backtestResult.total_return !== undefined) && performance && (
          <div className="card comparison-card">
            <h2>Backtest vs Live</h2>
            <div className="comparison-stats">
              <div className="comparison-row">
                <span className="label">Backtest predicted</span>
                <span className={`value ${(backtestResult.total_return ?? 0) >= 0 ? 'positive' : 'negative'}`}>
                  {formatPercent(backtestResult.total_return ?? 0)}
                </span>
              </div>
              <div className="comparison-row">
                <span className="label">Live performance</span>
                <span className={`value ${(performance.total_return ?? 0) >= 0 ? 'positive' : 'negative'}`}>
                  {formatPercent(performance.total_return ?? 0)}
                </span>
              </div>
              <div className="comparison-row">
                <span className="label">Gap</span>
                <span className="value negative">
                  {formatPercent((performance.total_return ?? 0) - (backtestResult.total_return ?? 0))}
                </span>
              </div>
            </div>
            <p className="comparison-note">Gap reflects execution costs, slippage, and timing.</p>
          </div>
        )}

        {/* Equity Curve */}
        <div className="card chart-card">
          <h2>Equity Curve</h2>
          {loading && history.length === 0 && !backtestResult ? (
            <div className="loading-placeholder chart-placeholder">Loading...</div>
          ) : chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis 
                  dataKey="timestamp" 
                  tickFormatter={(ts) => (ts ? new Date(ts).toLocaleDateString() : '')}
                />
                <YAxis tickFormatter={(v) => v != null ? `$${(v / 1000).toFixed(0)}k` : ''} />
                <Tooltip 
                  formatter={(value) => value != null ? formatCurrency(value) : '—'}
                  labelFormatter={(label) => label ? new Date(label).toLocaleString() : ''}
                />
                <Legend />
                <Line 
                  type="monotone" 
                  dataKey="portfolio_value" 
                  stroke="#2E86AB" 
                  strokeWidth={2}
                  name="Live"
                  connectNulls={false}
                />
                <Line 
                  type="monotone" 
                  dataKey="backtest_value" 
                  stroke="#94a3b8" 
                  strokeWidth={2}
                  strokeDasharray="5 5"
                  name="Backtest"
                  connectNulls={false}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="empty-placeholder chart-placeholder">No portfolio history yet. Load a backtest to compare.</div>
          )}
        </div>

        {/* Recent Trades */}
        <div className="card">
          <h2>Recent Trades</h2>
          <div className="trades-table">
            {loading && trades.length === 0 ? (
              <div className="loading-placeholder">Loading...</div>
            ) : (
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Side</th>
                  <th>Ticker</th>
                  <th>Qty</th>
                  <th>Price</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {trades.slice(0, 10).map(trade => (
                  <tr key={trade.id}>
                    <td>{new Date(trade.timestamp).toLocaleString()}</td>
                    <td className={trade.side === 'BUY' ? 'buy' : 'sell'}>{trade.side}</td>
                    <td>{trade.ticker}</td>
                    <td>{trade.qty}</td>
                    <td>{trade.price ? formatCurrency(trade.price) : '-'}</td>
                    <td>{trade.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;