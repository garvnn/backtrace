import React, { useState, useEffect } from 'react';
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

  const loadBacktest = async () => {
    const ticker = tickerInput.trim().toUpperCase();
    if (!ticker) return;
    setBacktestError(null);
    setBacktestLoading(true);
    try {
      const res = await fetch(`${API_BASE}/backtest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker, start_date: '2020-01-01', end_date: '2024-12-31', strategy: 'Momentum' }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Backtest failed');
      setBacktestResult(data);
    } catch (err) {
      setBacktestError(err.message);
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
        </div>
      </header>

      {error && (
        <div className="error-banner">
          Unable to load data. Retrying in 60s.
        </div>
      )}

      <div className="container">
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
          {backtestResult ? (
            <div className="stats">
              <div className="stat">
                <span className="label">Total Return</span>
                <span className={`value ${backtestResult.total_return >= 0 ? 'positive' : 'negative'}`}>
                  {formatPercent(backtestResult.total_return)}
                </span>
              </div>
              <div className="stat">
                <span className="label">Sharpe Ratio</span>
                <span className="value">{Number(backtestResult.sharpe_ratio).toFixed(2)}</span>
              </div>
              <div className="stat">
                <span className="label">Max Drawdown</span>
                <span className="value negative">{formatPercent(backtestResult.max_drawdown)}</span>
              </div>
              <div className="stat">
                <span className="label">Number of Trades</span>
                <span className="value">{backtestResult.num_trades}</span>
              </div>
            </div>
          ) : (
            <div className="empty-placeholder">Enter a ticker and click Load backtest</div>
          )}
        </div>

        {/* Comparison */}
        {backtestResult && performance && (
          <div className="card comparison-card">
            <h2>Backtest vs Live</h2>
            <div className="comparison-stats">
              <div className="comparison-row">
                <span className="label">Backtest predicted</span>
                <span className={`value ${backtestResult.total_return >= 0 ? 'positive' : 'negative'}`}>
                  {formatPercent(backtestResult.total_return)}
                </span>
              </div>
              <div className="comparison-row">
                <span className="label">Live performance</span>
                <span className={`value ${performance.total_return >= 0 ? 'positive' : 'negative'}`}>
                  {formatPercent(performance.total_return)}
                </span>
              </div>
              <div className="comparison-row">
                <span className="label">Gap</span>
                <span className="value negative">
                  {formatPercent((performance.total_return || 0) - (backtestResult.total_return || 0))}
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