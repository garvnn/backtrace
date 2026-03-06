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
  const [runLoading, setRunLoading] = useState(false);
  const [placeTradeLoading, setPlaceTradeLoading] = useState(false);
  const [backtestError, setBacktestError] = useState(null);
  const [executorError, setExecutorError] = useState(null);
  const [strategySelect, setStrategySelect] = useState('Momentum');
  const [shortMa, setShortMa] = useState(50);
  const [longMa, setLongMa] = useState(200);
  const [lookbackPeriod, setLookbackPeriod] = useState(120);
  const [pairs, setPairs] = useState([]);
  const [pairTrades, setPairTrades] = useState([]);
  const [tickerB, setTickerB] = useState('MSFT');
  const [statArbLookback, setStatArbLookback] = useState(60);
  const [statArbEntry, setStatArbEntry] = useState(2);
  const [statArbExit, setStatArbExit] = useState(0.5);
  const shortMaRef = useRef(null);
  const longMaRef = useRef(null);
  const lookbackRef = useRef(null);
  const strategyFormRef = useRef(null);
  const paramsForRunRef = useRef({ strategy: 'Momentum', shortMa: 50, longMa: 200, lookbackPeriod: 120, tickerB: 'MSFT', statArbLookback: 60, statArbEntry: 2, statArbExit: 0.5 });
  useEffect(() => {
    paramsForRunRef.current = {
      strategy: strategySelect,
      shortMa,
      longMa,
      lookbackPeriod,
      tickerB,
      statArbLookback,
      statArbEntry,
      statArbExit,
    };
  }, [strategySelect, shortMa, longMa, lookbackPeriod, tickerB, statArbLookback, statArbEntry, statArbExit]);

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

      const pairsRes = await fetch(`${API_BASE}/pairs?strategy=Stat%20Arb`);
      if (pairsRes.ok) {
        const pairsData = await pairsRes.json();
        setPairs(pairsData.pairs || []);
      }
      const pairTradesRes = await fetch(`${API_BASE}/pair-trades`);
      if (pairTradesRes.ok) {
        const pairTradesData = await pairTradesRes.json();
        setPairTrades(pairTradesData.pair_trades || []);
      }
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

  // Store only fields needed for UI to avoid DataCloneError when state is cloned (e.g. by DevTools/profiling)
  // sentParams: for Stat Arb, merge in so display always shows what we sent (API can omit keys)
  const setBacktestResultMinimal = (data, sentParams = null) => {
    if (!data || (data.equity_curve === undefined && data.total_return === undefined)) {
      setBacktestResult(null);
      return;
    }
    let params_used = data.params_used || null;
    if (sentParams && (data.strategy === 'Stat Arb' || sentParams.strategy === 'Stat Arb')) {
      params_used = {
        strategy: data.strategy || sentParams.strategy || 'Stat Arb',
        ticker_a: data.params_used?.ticker_a ?? sentParams.ticker_a ?? data.ticker?.split('-')[0],
        ticker_b: data.params_used?.ticker_b ?? sentParams.ticker_b ?? data.ticker?.split('-')[1],
        lookback: data.params_used?.lookback ?? sentParams.lookback,
        entry_threshold: data.params_used?.entry_threshold ?? sentParams.entry_threshold,
        exit_threshold: data.params_used?.exit_threshold ?? sentParams.exit_threshold,
      };
    }
    setBacktestResult({
      ticker: data.ticker,
      strategy: data.strategy,
      total_return: data.total_return,
      sharpe_ratio: data.sharpe_ratio,
      max_drawdown: data.max_drawdown,
      num_trades: data.num_trades,
      equity_curve: Array.isArray(data.equity_curve) ? data.equity_curve : [],
      params_used,
    });
  };

  const runStrategy = async () => {
    const ticker = tickerInput.trim().toUpperCase();
    if (!ticker) return;

    await new Promise((r) => setTimeout(r, 0));
    // Read from ref so we send the values currently in the form (ref is updated synchronously in onChange; state can be stale if user clicks Run before re-render)
    const { strategy, shortMa, longMa, lookbackPeriod, tickerB: refTickerB, statArbLookback: refLookback, statArbEntry: refEntry, statArbExit: refExit } = paramsForRunRef.current;
    const tickerBVal = (strategy === 'Stat Arb' ? (refTickerB || '').trim().toUpperCase() : '');
    const statArbLookbackVal = strategy === 'Stat Arb' ? (Number(refLookback) || 60) : 60;
    const statArbEntryVal = strategy === 'Stat Arb' ? (Number(refEntry) || 2) : 2;
    const statArbExitVal = strategy === 'Stat Arb' ? (Number(refExit) || 0.5) : 0.5;

    setBacktestError(null);
    setBacktestResult(null);

    if (strategy === 'Stat Arb' && !tickerBVal) {
      setBacktestError('Stat Arb requires Ticker B.');
      return;
    }

    setRunLoading(true);
    try {
      const btBody = {
        ticker,
        start_date: '2020-01-01',
        end_date: '2024-12-31',
        strategy,
        short_window: shortMa,
        long_window: longMa,
        lookback_period: lookbackPeriod,
      };
      if (strategy === 'Stat Arb') {
        btBody.ticker_b = tickerBVal;
        btBody.lookback = statArbLookbackVal;
        btBody.entry_threshold = statArbEntryVal;
        btBody.exit_threshold = statArbExitVal;
      }
      const btRes = await fetch(`${API_BASE}/backtest`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Cache-Control': 'no-cache',
          'Pragma': 'no-cache',
          'Cache-Bust': String(Date.now()),
        },
        body: JSON.stringify(btBody),
      });
      const btData = await btRes.json().catch(() => ({}));
      if (btRes.ok && btData && (btData.equity_curve !== undefined || btData.total_return !== undefined)) {
        const sentParams = strategy === 'Stat Arb' ? {
          strategy: 'Stat Arb',
          ticker_a: ticker,
          ticker_b: tickerBVal,
          lookback: statArbLookbackVal,
          entry_threshold: statArbEntryVal,
          exit_threshold: statArbExitVal,
        } : null;
        setBacktestResultMinimal(btData, sentParams);
      } else {
        const msg = Array.isArray(btData.detail)
          ? (btData.detail[0]?.msg || JSON.stringify(btData.detail))
          : (typeof btData.detail === 'string' ? btData.detail : btData.detail || 'Backtest failed');
        setBacktestError(msg);
      }
    } catch (err) {
      setBacktestError(err.message || 'Backtest failed');
    } finally {
      setRunLoading(false);
    }
  };

  const placeTrade = async () => {
    await new Promise((r) => setTimeout(r, 0));
    const { strategy, shortMa, longMa, lookbackPeriod, tickerB: tb, statArbLookback: sal, statArbEntry: sae, statArbExit: sax } = paramsForRunRef.current;
    const ticker = tickerInput.trim().toUpperCase() || 'AAPL';
    const tickerBVal = (tb || '').trim().toUpperCase();
    setExecutorError(null);
    setPlaceTradeLoading(true);
    try {
      const body = {
        strategy,
        ticker,
        short_window: shortMa,
        long_window: longMa,
        lookback_period: lookbackPeriod,
      };
      if (strategy === 'Stat Arb') {
        body.ticker_b = tickerBVal;
        body.lookback = sal;
        body.entry_threshold = sae;
        body.exit_threshold = sax;
      }
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
      setPlaceTradeLoading(false);
    }
  };

  const deleteTrade = async (tradeId) => {
    try {
      const res = await fetch(`${API_BASE}/trades/${tradeId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Delete failed');
      const tradesRes = await fetch(`${API_BASE}/trades`);
      if (tradesRes.ok) {
        const data = await tradesRes.json();
        setTrades(data.trades);
      }
    } catch (err) {
      console.error('Delete trade error:', err);
    }
  };

  const formatTradeParams = (trade) => {
    const p = trade.params;
    if (!p) return '—';
    if (trade.strategy === 'MeanReversion') return `Short ${p.short_window} / Long ${p.long_window}`;
    return `Lookback ${p.lookback_period ?? '—'} days`;
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
        <div className="strategy-controls" ref={strategyFormRef}>
          <label className="strategy-label">Strategy</label>
          <select
            value={strategySelect}
            onChange={(e) => {
              const v = e.target.value;
              setStrategySelect(v);
              paramsForRunRef.current.strategy = v;
            }}
            className="strategy-select"
            disabled={runLoading || placeTradeLoading}
          >
            <option value="Momentum">Momentum</option>
            <option value="MA Crossover">MA Crossover</option>
            <option value="Stat Arb">Stat Arb</option>
          </select>
          {strategySelect === 'Stat Arb' && (
            <>
              <label className="param-label">Ticker B</label>
              <input
                type="text"
                value={tickerB}
                onChange={(e) => { setTickerB(e.target.value); paramsForRunRef.current.tickerB = e.target.value; }}
                placeholder="e.g. MSFT"
                className="param-input"
              />
              <label className="param-label">Lookback (days)</label>
              <input
                type="number"
                min={10}
                max={252}
                value={statArbLookback}
                onChange={(e) => { const v = Number(e.target.value) || 60; setStatArbLookback(v); paramsForRunRef.current.statArbLookback = v; }}
                className="param-input"
              />
              <label className="param-label">Entry z</label>
              <input
                type="number"
                min={0.5}
                step={0.1}
                value={statArbEntry}
                onChange={(e) => { const v = Number(e.target.value) || 2; setStatArbEntry(v); paramsForRunRef.current.statArbEntry = v; }}
                className="param-input"
              />
              <label className="param-label">Exit z</label>
              <input
                type="number"
                min={0}
                step={0.1}
                value={statArbExit}
                onChange={(e) => { const v = Number(e.target.value) || 0.5; setStatArbExit(v); paramsForRunRef.current.statArbExit = v; }}
                className="param-input"
              />
            </>
          )}
          {strategySelect === 'MA Crossover' && (
            <>
              <label className="param-label">Short MA (days)</label>
              <input
                ref={shortMaRef}
                name="short_window"
                type="number"
                min={1}
                max={500}
                value={shortMa}
                onChange={(e) => {
                  const v = Number(e.target.value) || 50;
                  setShortMa(v);
                  paramsForRunRef.current.shortMa = v;
                }}
                className="param-input"
              />
              <label className="param-label">Long MA (days)</label>
              <input
                ref={longMaRef}
                name="long_window"
                type="number"
                min={1}
                max={500}
                value={longMa}
                onChange={(e) => {
                  const v = Number(e.target.value) || 200;
                  setLongMa(v);
                  paramsForRunRef.current.longMa = v;
                }}
                className="param-input"
              />
            </>
          )}
          {strategySelect === 'Momentum' && (
            <>
              <label className="param-label">Lookback (days)</label>
              <input
                ref={lookbackRef}
                name="lookback_period"
                type="number"
                min={1}
                max={500}
                value={lookbackPeriod}
                onChange={(e) => {
                  const v = Number(e.target.value) || 120;
                  setLookbackPeriod(v);
                  paramsForRunRef.current.lookbackPeriod = v;
                }}
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
            placeholder={strategySelect === 'Stat Arb' ? 'Ticker A e.g. AAPL' : 'e.g. AAPL'}
            className="ticker-input"
            disabled={runLoading || placeTradeLoading}
          />
          <button
            type="button"
            onClick={runStrategy}
            disabled={runLoading || placeTradeLoading || !tickerInput.trim()}
            className="run-strategy-btn"
          >
            {runLoading ? 'Running…' : 'Run strategy'}
          </button>
          <button
            type="button"
            onClick={placeTrade}
            disabled={runLoading || placeTradeLoading || !tickerInput.trim() || (strategySelect === 'Stat Arb' && !tickerB.trim())}
            className="place-trade-btn"
          >
            {placeTradeLoading ? 'Placing…' : 'Place trade'}
          </button>
          {backtestError && <span className="backtest-error">{backtestError}</span>}
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
          {strategySelect === 'Stat Arb' ? (
            <div className="help-content">
              <p><strong>Stat Arb (statistical arbitrage / pairs trading)</strong></p>
              <p>Trade two <strong>cointegrated</strong> stocks (e.g. AAPL/MSFT, KO/PEP). The spread is log(price_A) − β·log(price_B). When the spread&apos;s <strong>z-score</strong> exceeds the entry threshold, the strategy goes short the spread (sell A, buy B); when z-score is below −entry, it goes long (buy A, sell B). It closes when |z| &lt; exit threshold.</p>
              <p><strong>Lookback</strong> is the window (days) for spread mean/std. <strong>Entry z</strong> and <strong>Exit z</strong> control when to open and close. Use <code>live/pairs_finder.py</code> to discover cointegrated pairs.</p>
            </div>
          ) : strategySelect === 'MA Crossover' ? (
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
              {strategySelect === 'Stat Arb' && pairs.length > 0 ? (
                <>
                  <div className="stat">
                    <span className="label">Positions</span>
                    <span className="value" style={{ display: 'block' }}>
                      {pairs.map((p, i) => (
                        <span key={i}>
                          {p.ticker_a}: {p.qty_a} shares · {p.ticker_b}: {p.qty_b} shares
                        </span>
                      ))}
                    </span>
                  </div>
                  <div className="stat">
                    <span className="label">Combined Value</span>
                    <span className="value">{formatCurrency(pairs[0].combined_value)}</span>
                  </div>
                </>
              ) : null}
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
                    {backtestResult.params_used.strategy === 'Stat Arb'
                      ? `${backtestResult.params_used.ticker_a ?? backtestResult.ticker?.split('-')[0] ?? '—'}-${backtestResult.params_used.ticker_b ?? backtestResult.ticker?.split('-')[1] ?? '—'}, lookback ${backtestResult.params_used.lookback ?? '—'}, entry z ${backtestResult.params_used.entry_threshold ?? '—'}, exit z ${backtestResult.params_used.exit_threshold ?? '—'}`
                      : backtestResult.params_used.strategy === 'MeanReversion'
                        ? `Short MA ${backtestResult.params_used.short_window ?? '—'}, Long MA ${backtestResult.params_used.long_window ?? '—'}`
                        : `Lookback ${backtestResult.params_used.lookback_period ?? '—'} days`}
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
            <div className="empty-placeholder">
              Enter ticker(s), set strategy and params, then click Run strategy
            </div>
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

        {/* Trades */}
        <div className="card">
          <h2>Trades</h2>
          <div className="trades-table">
            {loading && trades.length === 0 && pairTrades.length === 0 ? (
              <div className="loading-placeholder">Loading...</div>
            ) : strategySelect === 'Stat Arb' && pairTrades.length > 0 ? (
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Strategy</th>
                    <th>Pair</th>
                    <th>Side A</th>
                    <th>Side B</th>
                    <th>Qty A</th>
                    <th>Qty B</th>
                    <th>Spread</th>
                    <th>Z-score</th>
                  </tr>
                </thead>
                <tbody>
                  {pairTrades.map(pt => (
                    <tr key={pt.id}>
                      <td>{new Date(pt.timestamp).toLocaleString()}</td>
                      <td>{pt.strategy ?? '—'}</td>
                      <td>{pt.pair_name ?? `${pt.ticker_a}-${pt.ticker_b}`}</td>
                      <td className={pt.side_a === 'BUY' ? 'buy' : 'sell'}>{pt.side_a}</td>
                      <td className={pt.side_b === 'BUY' ? 'buy' : 'sell'}>{pt.side_b}</td>
                      <td>{pt.qty_a}</td>
                      <td>{pt.qty_b}</td>
                      <td>{pt.spread != null ? Number(pt.spread).toFixed(4) : '—'}</td>
                      <td>{pt.z_score != null ? Number(pt.z_score).toFixed(2) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Strategy</th>
                  <th>Params</th>
                  <th>Side</th>
                  <th>Ticker</th>
                  <th>Qty</th>
                  <th>Price</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {trades.map(trade => (
                  <tr key={trade.id}>
                    <td>{new Date(trade.timestamp).toLocaleString()}</td>
                    <td>{trade.strategy ?? '—'}</td>
                    <td>{formatTradeParams(trade)}</td>
                    <td className={trade.side === 'BUY' ? 'buy' : 'sell'}>{trade.side}</td>
                    <td>{trade.ticker}</td>
                    <td>{trade.qty}</td>
                    <td>{trade.price ? formatCurrency(trade.price) : '-'}</td>
                    <td>{trade.status}</td>
                    <td>
                      <button type="button" className="delete-trade-btn" onClick={() => deleteTrade(trade.id)}>Delete</button>
                    </td>
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