import React, { useState, useEffect, useRef, useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import './App.css';
import { Hero } from './dashboard/Hero';
import { EquityChartPanel } from './dashboard/EquityChartPanel';
import { AllocationHeatmap } from './dashboard/AllocationHeatmap';
import { ConfidenceRing } from './dashboard/ConfidenceRing';

const API_BASE =
  process.env.REACT_APP_API_URL ||
  (process.env.NODE_ENV === 'production'
    ? 'https://backtrace-production.up.railway.app'
    : 'http://localhost:8000');

function App() {
  const [portfolio, setPortfolio] = useState(null);
  const [positionsDetail, setPositionsDetail] = useState(null);
  const [trades, setTrades] = useState([]);
  const [executionLogs, setExecutionLogs] = useState([]);
  const [expandedExecutionLogIds, setExpandedExecutionLogIds] = useState({});
  const [performance, setPerformance] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tickerInput, setTickerInput] = useState('AAPL');
  const [backtestResult, setBacktestResult] = useState(null);
  const [runLoading, setRunLoading] = useState(false);
  const [backtestError, setBacktestError] = useState(null);
  const [strategySelect, setStrategySelect] = useState('Momentum');
  const [shortMa, setShortMa] = useState(50);
  const [longMa, setLongMa] = useState(200);
  const [lookbackPeriod, setLookbackPeriod] = useState(120);
  const [pairs, setPairs] = useState([]);
  const [pairTrades, setPairTrades] = useState([]);
  const [tickerB, setTickerB] = useState('MSFT');
  const [statArbTicker1, setStatArbTicker1] = useState('AAPL');
  const [availablePairs, setAvailablePairs] = useState(['MSFT', 'GOOGL', 'META']);
  const [statArbTicker2, setStatArbTicker2] = useState('MSFT');
  const [statArbLookback, setStatArbLookback] = useState(60);
  const [statArbEntry, setStatArbEntry] = useState(2);
  const [statArbExit, setStatArbExit] = useState(0.5);
  const [monteCarloData, setMonteCarloData] = useState(null);
  const [showMonteCarlo, setShowMonteCarlo] = useState(false);
  const [monteCarloLoading, setMonteCarloLoading] = useState(false);
  const [monteCarloError, setMonteCarloError] = useState(null);
  const [tickerFilter, setTickerFilter] = useState('');
  const [activeTab, setActiveTab] = useState('Dashboard');
  const [chartRange, setChartRange] = useState('All'); // '1M' | '3M' | '6M' | '1Y' | 'All'
  const [chartMode, setChartMode] = useState('equity'); // 'equity' | 'candles'
  const [candleTicker, setCandleTicker] = useState('AAPL');
  const [candleBars, setCandleBars] = useState([]);
  const [candleLoading, setCandleLoading] = useState(false);
  const [candleError, setCandleError] = useState(null);
  const [strategyHelpOpen, setStrategyHelpOpen] = useState(false);
  const [headerTime, setHeaderTime] = useState(() => new Date());
  const [positionsSort, setPositionsSort] = useState('pnl'); // 'pnl' | 'ticker'
  const shortMaRef = useRef(null);
  const longMaRef = useRef(null);
  const lookbackRef = useRef(null);
  const strategyFormRef = useRef(null);
  const paramsForRunRef = useRef({ strategy: 'Momentum', shortMa: 50, longMa: 200, lookbackPeriod: 120, tickerB: 'MSFT', statArbTicker1: 'AAPL', statArbTicker2: 'MSFT', statArbLookback: 60, statArbEntry: 2, statArbExit: 0.5 });
  useEffect(() => {
    paramsForRunRef.current = {
      strategy: strategySelect,
      shortMa,
      longMa,
      lookbackPeriod,
      tickerB,
      statArbTicker1,
      statArbTicker2,
      statArbLookback,
      statArbEntry,
      statArbExit,
    };
  }, [strategySelect, shortMa, longMa, lookbackPeriod, tickerB, statArbTicker1, statArbTicker2, statArbLookback, statArbEntry, statArbExit]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60000); // Refresh every minute
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const t = setInterval(() => setHeaderTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const fetchData = async () => {
    try {
      setError(null);
      const portfolioRes = await fetch(`${API_BASE}/portfolio`);
      if (!portfolioRes.ok) throw new Error('Failed to fetch portfolio');
      const portfolioData = await portfolioRes.json();
      setPortfolio(portfolioData);

      const positionsDetailRes = await fetch(`${API_BASE}/positions-detail`);
      if (positionsDetailRes.ok) {
        const positionsDetailData = await positionsDetailRes.json();
        setPositionsDetail(positionsDetailData);
      } else {
        setPositionsDetail(null);
      }

      const tradesRes = await fetch(`${API_BASE}/trades`);
      if (!tradesRes.ok) throw new Error('Failed to fetch trades');
      const tradesData = await tradesRes.json();
      setTrades(tradesData.trades);

      const executionLogsRes = await fetch(`${API_BASE}/execution-logs?limit=200`);
      if (executionLogsRes.ok) {
        const executionLogsData = await executionLogsRes.json();
        setExecutionLogs(executionLogsData.execution_logs || []);
      } else {
        setExecutionLogs([]);
      }

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

  const formatPercentSigned = (value) => {
    const pct = (value * 100).toFixed(2);
    const sign = value >= 0 ? '+' : '';
    return sign + pct + '%';
  };

  const timeAgo = (isoString) => {
    if (!isoString) return '';
    const d = new Date(isoString);
    const now = new Date();
    const sec = Math.floor((now - d) / 1000);
    if (sec < 60) return 'Just now';
    if (sec < 3600) return `${Math.floor(sec / 60)} min ago`;
    if (sec < 86400) return `${Math.floor(sec / 3600)} hrs ago`;
    if (sec < 604800) return `${Math.floor(sec / 86400)} days ago`;
    return d.toLocaleDateString();
  };

  // Compute live Sharpe and max drawdown from portfolio history (client-side)
  const computeSharpe = (hist) => {
    if (!hist || hist.length < 2) return null;
    const values = hist.map((h) => h.portfolio_value).filter((v) => v != null && v > 0);
    if (values.length < 2) return null;
    const returns = [];
    for (let i = 1; i < values.length; i++) {
      returns.push((values[i] - values[i - 1]) / values[i - 1]);
    }
    const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
    const variance = returns.reduce((a, r) => a + (r - mean) ** 2, 0) / returns.length;
    const std = Math.sqrt(variance);
    if (std === 0) return 0;
    const annualized = mean * 252;
    const stdAnnual = std * Math.sqrt(252);
    return stdAnnual === 0 ? 0 : annualized / stdAnnual;
  };

  const computeMaxDrawdown = (hist) => {
    if (!hist || hist.length < 2) return null;
    const values = hist.map((h) => h.portfolio_value).filter((v) => v != null);
    if (values.length < 2) return null;
    let peak = values[0];
    let maxDd = 0;
    for (let i = 1; i < values.length; i++) {
      if (values[i] > peak) peak = values[i];
      const dd = (peak - values[i]) / peak;
      if (dd > maxDd) maxDd = dd;
    }
    return -maxDd; // negative as convention
  };

  const handleStatArbTicker1Change = async (e) => {
    const ticker = e.target.value.toUpperCase();
    setStatArbTicker1(ticker);
    setTickerInput(ticker);
    if (ticker.length >= 2) {
      try {
        const res = await fetch(`${API_BASE}/available-pairs/${ticker}`);
        const data = await res.json();
        setAvailablePairs(data.available_pairs || []);
        if (!(data.available_pairs || []).includes(statArbTicker2)) {
          setStatArbTicker2('');
          setTickerB('');
          paramsForRunRef.current.tickerB = '';
        }
      } catch {
        setAvailablePairs([]);
      }
    } else {
      setAvailablePairs([]);
    }
  };

  const handleStatArbTicker2Change = (e) => {
    const v = e.target.value;
    setStatArbTicker2(v);
    setTickerB(v);
    paramsForRunRef.current.tickerB = v;
  };

  const ZScoreGauge = ({ zScore }) => {
    const z = zScore != null ? Number(zScore) : 0;
    const getColor = (val) => {
      if (Math.abs(val) > 2) return '#ef4444';
      if (Math.abs(val) > 1) return '#f59e0b';
      return '#22c55e';
    };
    const pct = Math.max(0, Math.min(100, ((z + 3) / 6) * 100));
    return (
      <div className="z-gauge">
        <div className="z-bar">
          <div
            className="z-marker"
            style={{ left: `${pct}%`, background: getColor(z) }}
          />
        </div>
        <div className="z-labels">
          <span>-3</span>
          <span>-2</span>
          <span>0</span>
          <span>+2</span>
          <span>+3</span>
        </div>
        <div className="z-value">
          Current Z-Score: <strong>{z.toFixed(2)}</strong>
        </div>
      </div>
    );
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
    await new Promise((r) => setTimeout(r, 0));
    const { strategy, shortMa, longMa, lookbackPeriod, tickerB: refTickerB, statArbTicker1: refT1, statArbTicker2: refT2, statArbLookback: refLookback, statArbEntry: refEntry, statArbExit: refExit } = paramsForRunRef.current;
    const ticker = strategy === 'Stat Arb' ? (refT1 || '').trim().toUpperCase() : tickerInput.trim().toUpperCase();
    if (!ticker) return;
    const tickerBVal = (strategy === 'Stat Arb' ? (refT2 || refTickerB || '').trim().toUpperCase() : '');
    const statArbLookbackVal = strategy === 'Stat Arb' ? (Number(refLookback) || 60) : 60;
    const statArbEntryVal = strategy === 'Stat Arb' ? (Number(refEntry) || 2) : 2;
    const statArbExitVal = strategy === 'Stat Arb' ? (Number(refExit) || 0.5) : 0.5;

    setBacktestError(null);
    setBacktestResult(null);
    setShowMonteCarlo(false);
    setMonteCarloData(null);
    setMonteCarloError(null);

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

  const fetchMonteCarlo = async (ticker, strategy) => {
    setMonteCarloError(null);
    setMonteCarloLoading(true);
    try {
      const res = await fetch(
        `${API_BASE}/monte-carlo?ticker=${encodeURIComponent(ticker)}&strategy=${encodeURIComponent(strategy)}&runs=10000`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setMonteCarloData(null);
        const detail = typeof data.detail === 'string' ? data.detail : null;
        const message = res.status === 404 && detail === 'Not Found'
          ? 'Monte Carlo endpoint not available. Restart the API server (from the live/ folder: uvicorn api:app --reload).'
          : (detail || 'Monte Carlo request failed');
        setMonteCarloError(message);
        return;
      }
      if (data.error) {
        setMonteCarloData(null);
        setMonteCarloError(data.error);
        return;
      }
      setMonteCarloData(data);
      setShowMonteCarlo(true);
    } catch (err) {
      console.error('Error fetching Monte Carlo:', err);
      setMonteCarloData(null);
      setMonteCarloError(err.message || 'Failed to run Monte Carlo');
    } finally {
      setMonteCarloLoading(false);
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

  const formatExecutionSignal = (signal) => {
    if (signal == null || signal === '' || signal === 'N/A') return '—';
    if (signal.includes(',')) {
      const [a, b] = signal.split(',');
      return `${a}/${b}`;
    }
    if (signal === '1') return 'BUY';
    if (signal === '0') return 'FLAT';
    if (signal === '-1') return 'SHORT';
    return signal;
  };

  const humanizeReason = (reason) => {
    if (!reason) return '—';
    return reason.replaceAll('_', ' ');
  };

  // Combined chart data: live + backtest (backtest scaled to same start as live)
  const chartDataFull = (() => {
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

  const chartData = (() => {
    if (!chartRange || chartRange === 'All') return chartDataFull;
    const now = new Date();
    let cut = new Date(now);
    if (chartRange === '1M') cut.setMonth(cut.getMonth() - 1);
    else if (chartRange === '3M') cut.setMonth(cut.getMonth() - 3);
    else if (chartRange === '6M') cut.setMonth(cut.getMonth() - 6);
    else if (chartRange === '1Y') cut.setFullYear(cut.getFullYear() - 1);
    const cutStr = cut.toISOString().slice(0, 10);
    return chartDataFull.filter((d) => (d.timestamp || '') >= cutStr);
  })();

  const liveSharpe = computeSharpe(history);
  const liveMaxDrawdown = computeMaxDrawdown(history);
  const daysRunning = history.length >= 1 && history[0].timestamp
    ? Math.max(0, Math.floor((Date.now() - new Date(history[0].timestamp).getTime()) / 86400000))
    : null;
  const recentTrades = trades.slice(0, 5);
  // Positions from GET /portfolio; merge in entry_price, current_price, pnl, pnl_pct from GET /positions-detail.
  const positionsFromPortfolio = useMemo(() => {
    const p = portfolio?.positions;
    if (!p) return [];
    let rows = Array.isArray(p)
      ? p.map((x) => ({ symbol: x.symbol || x.ticker, qty: Number(x.qty ?? x.quantity ?? 0) }))
      : Object.entries(p).map(([symbol, qty]) => ({ symbol, qty: Number(qty) }));
    const detailList = positionsDetail?.positions;
    if (Array.isArray(detailList) && detailList.length > 0) {
      const bySymbol = {};
      detailList.forEach((d) => {
        bySymbol[d.symbol] = d;
      });
      rows = rows.map((row) => {
        const d = bySymbol[row.symbol];
        if (!d) return row;
        return {
          ...row,
          entry_price: d.entry_price,
          current_price: d.current_price,
          pnl: d.pnl,
          pnl_pct: d.pnl_pct,
        };
      });
    }
    return rows;
  }, [portfolio, positionsDetail]);
  const positionsCount = positionsFromPortfolio.length;

  // Default candle symbol: largest absolute notional when prices exist; else first symbol; else AAPL.
  const defaultCandleTicker = useMemo(() => {
    let best = null;
    let bestVal = 0;
    for (const r of positionsFromPortfolio) {
      const px = r.current_price;
      const q = Number(r.qty ?? 0);
      if (px != null && px > 0) {
        const n = Math.abs(q) * px;
        if (n > bestVal) {
          bestVal = n;
          best = r.symbol;
        }
      }
    }
    if (best) return best;
    if (positionsFromPortfolio[0]?.symbol) return positionsFromPortfolio[0].symbol;
    return 'AAPL';
  }, [positionsFromPortfolio]);

  useEffect(() => {
    setCandleTicker((prev) => {
      if (prev === 'AAPL' && defaultCandleTicker && defaultCandleTicker !== 'AAPL') return defaultCandleTicker;
      return prev;
    });
  }, [defaultCandleTicker]);

  useEffect(() => {
    if (chartMode !== 'candles' || !candleTicker?.trim()) {
      setCandleBars([]);
      setCandleError(null);
      setCandleLoading(false);
      return undefined;
    }
    let cancelled = false;
    setCandleLoading(true);
    setCandleError(null);
    const tr = chartRange === 'All' ? 'ALL' : chartRange;
    fetch(
      `${API_BASE}/daily-bars?ticker=${encodeURIComponent(candleTicker.trim())}&time_range=${encodeURIComponent(tr)}`
    )
      .then(async (res) => {
        const data = await res.json();
        if (!res.ok) {
          const d = data?.detail;
          const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map((x) => x.msg || x).join(', ') : 'Request failed';
          throw new Error(msg);
        }
        if (cancelled) return;
        setCandleBars(Array.isArray(data.bars) ? data.bars : []);
      })
      .catch((err) => {
        if (!cancelled) {
          setCandleError(err.message || 'Failed to load daily bars');
          setCandleBars([]);
        }
      })
      .finally(() => {
        if (!cancelled) setCandleLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [chartMode, chartRange, candleTicker]);

  const tabs = [
    { id: 'Dashboard', label: 'Dashboard' },
    { id: 'Portfolio', label: 'Portfolio' },
    { id: 'Trades', label: 'Trades' },
    { id: 'Backtest', label: 'Backtest' },
  ];

  useEffect(() => {
    const val = portfolio?.portfolio_value ?? performance?.current_value;
    if (val != null) {
      document.title = `BackTrace Live | ${formatCurrency(val)}`;
    }
    return () => { document.title = 'BackTrace Live'; };
  }, [portfolio?.portfolio_value, performance?.current_value]);

  return (
    <div className="App">
      <header>
        <div className="header-brand">BackTrace Live</div>
        <nav className="header-tabs">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={`tab-btn ${activeTab === tab.id ? 'tab-btn-active' : ''}`}
              onClick={() => { fetchData(); setActiveTab(tab.id); }}
            >
              {tab.label}
            </button>
          ))}
        </nav>
        <div className="header-clock" title="Local time">
          {headerTime.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </div>
      </header>

      {error && (
        <div className="error-banner">
          <span>Unable to load data. Retrying in 60s.</span>
          <button type="button" onClick={fetchData} style={{ padding: '0.35rem 0.75rem', background: 'rgba(255,255,255,0.15)', border: 'none', borderRadius: 6, color: '#fecaca', cursor: 'pointer' }}>Retry</button>
        </div>
      )}

      <div className="container">
        {activeTab === 'Portfolio' && (
          <div className="card portfolio-tab-card">
            <h2>Current Portfolio</h2>
            {portfolio != null && (
              <>
                <div className="portfolio-tab-summary">
                  <div className="portfolio-tab-value">
                    <span className="label">Portfolio Value</span>
                    <span className="value">{formatCurrency(portfolio.portfolio_value ?? 0)}</span>
                  </div>
                  <div className="portfolio-tab-cash">
                    <span className="label">Cash</span>
                    <span className="value">{formatCurrency(portfolio.cash ?? 0)}</span>
                  </div>
                </div>
                {portfolio.timestamp && (
                  <p className="portfolio-last-update">Last updated: {timeAgo(portfolio.timestamp)}</p>
                )}
                <div className="positions-table-wrap">
                  <div className="positions-sort">
                    <span>Sort by:</span>
                    <button type="button" className={positionsSort === 'ticker' ? 'active' : ''} onClick={() => setPositionsSort('ticker')}>Ticker</button>
                    <button type="button" className={positionsSort === 'pnl' ? 'active' : ''} onClick={() => setPositionsSort('pnl')}>P&L</button>
                  </div>
                  <table className="positions-detail-table">
                    <thead>
                      <tr>
                        <th>Ticker</th>
                        <th>Qty</th>
                        <th>Entry Price</th>
                        <th>Current Price</th>
                        <th>P&L</th>
                        <th>P&L %</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...positionsFromPortfolio]
                        .sort((a, b) => positionsSort === 'ticker'
                          ? (a.symbol || '').localeCompare(b.symbol || '')
                          : (b.pnl ?? 0) - (a.pnl ?? 0))
                        .map((row) => (
                          <tr key={row.symbol}>
                            <td><strong>{row.symbol}</strong></td>
                            <td>{row.qty}</td>
                            <td>{row.entry_price != null ? formatCurrency(row.entry_price) : '—'}</td>
                            <td>{row.current_price != null ? formatCurrency(row.current_price) : '—'}</td>
                            <td className={(row.pnl ?? 0) >= 0 ? 'positive' : 'negative'}>{row.pnl != null ? formatCurrency(row.pnl) : '—'}</td>
                            <td className={(row.pnl_pct ?? 0) >= 0 ? 'positive' : 'negative'}>{row.pnl_pct != null ? formatPercent(row.pnl_pct) : '—'}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                  {positionsFromPortfolio.length === 0 && (
                    <p className="empty-placeholder">No open positions.</p>
                  )}
                </div>
              </>
            )}
            {portfolio == null && !loading && <p className="empty-placeholder">Unable to load portfolio.</p>}
            {loading && portfolio == null && <div className="loading-placeholder">Loading…</div>}
          </div>
        )}

        {activeTab === 'Trades' && (
          <div className="card">
            <h2>Trade History</h2>
            {!(strategySelect === 'Stat Arb' && pairTrades.length > 0) && trades.length > 0 && (
              <div className="trades-filter">
                <label htmlFor="ticker-filter-th">Filter by ticker:</label>
                <input id="ticker-filter-th" type="text" placeholder="All tickers" value={tickerFilter} onChange={(e) => setTickerFilter(e.target.value.trim())} className="ticker-filter-input" />
              </div>
            )}
            <div className="trades-table">
              {strategySelect === 'Stat Arb' && pairTrades.length > 0 ? (
                <table>
                  <thead><tr><th>Time</th><th>Strategy</th><th>Pair</th><th>Side A</th><th>Side B</th><th>Qty A</th><th>Qty B</th><th>Spread</th><th>Z-score</th></tr></thead>
                  <tbody>
                    {pairTrades.map((pt) => (
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
                  <thead><tr><th>Time</th><th>Strategy</th><th>Params</th><th>Side</th><th>Ticker</th><th>Qty</th><th>Price</th><th>Status</th><th>Actions</th></tr></thead>
                  <tbody>
                    {(tickerFilter ? trades.filter((t) => (t.ticker || '').toUpperCase().includes(tickerFilter.toUpperCase())) : trades).map((trade) => (
                      <tr key={trade.id}>
                        <td>{new Date(trade.timestamp).toLocaleString()}</td>
                        <td>{trade.strategy ?? '—'}</td>
                        <td>{formatTradeParams(trade)}</td>
                        <td className={trade.side === 'BUY' ? 'buy' : 'sell'}>{trade.side}</td>
                        <td>{trade.ticker}</td>
                        <td>{trade.qty}</td>
                        <td>{trade.price ? formatCurrency(trade.price) : '-'}</td>
                        <td>{trade.status}</td>
                        <td><button type="button" className="delete-trade-btn" onClick={() => deleteTrade(trade.id)}>Delete</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            {loading && trades.length === 0 && pairTrades.length === 0 && <div className="loading-placeholder">Loading…</div>}
            {!loading && trades.length === 0 && pairTrades.length === 0 && <p className="empty-placeholder">No trades yet — run your first backtest.</p>}

            <div className="decision-logs-section">
              <h2>Decision Logs</h2>
              <p className="decision-logs-note">Shows why the executor placed a trade or skipped one.</p>
              <div className="trades-table">
                <table>
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Strategy</th>
                      <th>Ticker/Pair</th>
                      <th>Signal</th>
                      <th>Action</th>
                      <th>Reason</th>
                      <th>Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {executionLogs.map((log) => {
                      const expanded = !!expandedExecutionLogIds[log.id];
                      return (
                        <React.Fragment key={log.id}>
                          <tr>
                            <td>{new Date(log.timestamp).toLocaleString()}</td>
                            <td>{log.strategy ?? '—'}</td>
                            <td>{log.ticker ?? '—'}</td>
                            <td>{formatExecutionSignal(log.signal)}</td>
                            <td className={log.action === 'NO_TRADE' ? '' : (String(log.action).includes('SELL') ? 'sell' : 'buy')}>{log.action}</td>
                            <td className={log.action === 'NO_TRADE' ? 'decision-reason-no-trade' : ''}>{humanizeReason(log.reason)}</td>
                            <td>
                              {log.details ? (
                                <button
                                  type="button"
                                  className="details-toggle-btn"
                                  onClick={() => setExpandedExecutionLogIds((prev) => ({ ...prev, [log.id]: !prev[log.id] }))}
                                >
                                  {expanded ? 'Hide' : 'Show'}
                                </button>
                              ) : '—'}
                            </td>
                          </tr>
                          {expanded && log.details && (
                            <tr>
                              <td colSpan={7}>
                                <pre className="execution-details-json">{JSON.stringify(log.details, null, 2)}</pre>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {!loading && executionLogs.length === 0 && <p className="empty-placeholder">No decision logs yet — run the executor once.</p>}
            </div>
          </div>
        )}

        {activeTab === 'Backtest' && (
          <div className="backtest-tab">
            <div className="card">
              <h2>Run Backtest</h2>
              <div className="backtest-form" ref={strategyFormRef}>
                <label className="strategy-label">Strategy</label>
                <select
                  value={strategySelect}
                  onChange={(e) => { const v = e.target.value; setStrategySelect(v); paramsForRunRef.current.strategy = v; }}
                  className="strategy-select"
                  disabled={runLoading}
                >
                  <option value="Momentum">Momentum</option>
                  <option value="MA Crossover">MA Crossover</option>
                  <option value="Stat Arb">Stat Arb</option>
                </select>
                {strategySelect === 'Stat Arb' && (
                  <>
                    <div className="pair-selector">
                      <div>
                        <label className="param-label">First Stock</label>
                        <input type="text" value={statArbTicker1} onChange={handleStatArbTicker1Change} placeholder="e.g. AAPL" className="param-input pair-input" />
                      </div>
                      <div>
                        <label className="param-label">Paired With</label>
                        <select value={statArbTicker2} onChange={handleStatArbTicker2Change} disabled={availablePairs.length === 0} className="strategy-select pair-select">
                          <option value="">Select pair...</option>
                          {availablePairs.map(t => (<option key={t} value={t}>{t}</option>))}
                        </select>
                      </div>
                    </div>
                    <label className="param-label">Lookback (days)</label>
                    <input type="number" min={10} max={252} value={statArbLookback} onChange={(e) => { const v = Number(e.target.value) || 60; setStatArbLookback(v); paramsForRunRef.current.statArbLookback = v; }} className="param-input" />
                    <label className="param-label">Entry z</label>
                    <input type="number" min={0.5} step={0.1} value={statArbEntry} onChange={(e) => { const v = Number(e.target.value) || 2; setStatArbEntry(v); paramsForRunRef.current.statArbEntry = v; }} className="param-input" />
                    <label className="param-label">Exit z</label>
                    <input type="number" min={0} step={0.1} value={statArbExit} onChange={(e) => { const v = Number(e.target.value) || 0.5; setStatArbExit(v); paramsForRunRef.current.statArbExit = v; }} className="param-input" />
                  </>
                )}
                {strategySelect === 'MA Crossover' && (
                  <>
                    <label className="param-label">Short MA (days)</label>
                    <input ref={shortMaRef} type="number" min={1} max={500} value={shortMa} onChange={(e) => { const v = Number(e.target.value) || 50; setShortMa(v); paramsForRunRef.current.shortMa = v; }} className="param-input" />
                    <label className="param-label">Long MA (days)</label>
                    <input ref={longMaRef} type="number" min={1} max={500} value={longMa} onChange={(e) => { const v = Number(e.target.value) || 200; setLongMa(v); paramsForRunRef.current.longMa = v; }} className="param-input" />
                  </>
                )}
                {strategySelect === 'Momentum' && (
                  <>
                    <label className="param-label">Lookback (days)</label>
                    <input ref={lookbackRef} type="number" min={1} max={500} value={lookbackPeriod} onChange={(e) => { const v = Number(e.target.value) || 120; setLookbackPeriod(v); paramsForRunRef.current.lookbackPeriod = v; }} className="param-input" />
                  </>
                )}
                {strategySelect !== 'Stat Arb' && (
                  <input type="text" value={tickerInput} onChange={(e) => setTickerInput(e.target.value)} placeholder="e.g. AAPL" className="ticker-input" disabled={runLoading} />
                )}
                <button type="button" onClick={runStrategy} disabled={runLoading || (strategySelect === 'Stat Arb' ? (!statArbTicker1.trim() || !statArbTicker2.trim()) : !tickerInput.trim())} className="run-strategy-btn">
                  {runLoading ? 'Running…' : 'Run strategy'}
                </button>
              </div>
              {backtestError && <span className="backtest-error">{backtestError}</span>}
              {strategySelect === 'Stat Arb' && pairTrades.length > 0 && (
                <div style={{ marginTop: '1rem' }}>
                  <ZScoreGauge zScore={pairTrades[0]?.z_score ?? 0} />
                </div>
              )}
            </div>
            <div className="card">
              <h2>Backtest Results {backtestResult?.ticker && `(${backtestResult.ticker})`}</h2>
              {backtestResult && (backtestResult.total_return !== undefined || backtestResult.equity_curve) ? (
                <div className="stats">
                  {backtestResult.params_used && (
                    <div className="stat params-used">
                      <span className="label">Params used</span>
                      <span className="value params-text">
                        {backtestResult.params_used.strategy === 'Stat Arb' ? `${backtestResult.params_used.ticker_a ?? backtestResult.ticker?.split('-')[0] ?? '—'}-${backtestResult.params_used.ticker_b ?? backtestResult.ticker?.split('-')[1] ?? '—'}, lookback ${backtestResult.params_used.lookback ?? '—'}, entry z ${backtestResult.params_used.entry_threshold ?? '—'}, exit z ${backtestResult.params_used.exit_threshold ?? '—'}` : backtestResult.params_used.strategy === 'MeanReversion' ? `Short MA ${backtestResult.params_used.short_window ?? '—'}, Long MA ${backtestResult.params_used.long_window ?? '—'}` : `Lookback ${backtestResult.params_used.lookback_period ?? '—'} days`}
                      </span>
                    </div>
                  )}
                  <div className="stat"><span className="label">Total Return</span><span className={`value ${(backtestResult.total_return ?? 0) >= 0 ? 'positive' : 'negative'}`}>{formatPercent(backtestResult.total_return ?? 0)}</span></div>
                  <div className="stat"><span className="label">Sharpe Ratio</span><span className="value">{Number(backtestResult.sharpe_ratio ?? 0).toFixed(2)}</span></div>
                  <div className="stat"><span className="label">Max Drawdown</span><span className="value negative">{formatPercent(backtestResult.max_drawdown ?? 0)}</span></div>
                  <div className="stat"><span className="label">Number of Trades</span><span className="value">{backtestResult.num_trades ?? 0}</span></div>
                </div>
              ) : (
                <div className="empty-placeholder">Run a backtest above to see results.</div>
              )}
              {backtestResult && (backtestResult.total_return !== undefined || backtestResult.equity_curve) && (
                <div style={{ marginTop: '1rem' }}>
                  <button type="button" onClick={() => fetchMonteCarlo(backtestResult.ticker, backtestResult.strategy || strategySelect)} disabled={monteCarloLoading} className="run-strategy-btn" style={{ background: 'var(--accent)' }}>
                    {monteCarloLoading ? 'Running…' : 'Run Monte Carlo Simulation'}
                  </button>
                  {monteCarloError && <span className="backtest-error" style={{ display: 'block', marginTop: '0.5rem' }}>{monteCarloError}</span>}
                </div>
              )}
            </div>
            {showMonteCarlo && monteCarloData && !monteCarloData.error && (
              <div className="card chart-card monte-carlo-card">
                <h2>Monte Carlo Simulation (10,000 runs)</h2>
                <div className="stats monte-carlo-stats">
                  <div className="stat"><span className="label">5th Percentile (worst case)</span><span className={`value ${(monteCarloData.percentiles?.[5] ?? 0) < (monteCarloData.percentiles?.[50] ?? 0) ? 'negative' : ''}`}>{formatCurrency(monteCarloData.percentiles?.[5] ?? 0)}</span></div>
                  <div className="stat"><span className="label">50th Percentile (median)</span><span className="value">{formatCurrency(monteCarloData.percentiles?.[50] ?? 0)}</span></div>
                  <div className="stat"><span className="label">95th Percentile (best case)</span><span className="value">{formatCurrency(monteCarloData.percentiles?.[95] ?? 0)}</span></div>
                  <div className="stat"><span className="label">Probability of Profit</span><span className="value">{((monteCarloData.probability_profit ?? 0) * 100).toFixed(1)}%</span></div>
                </div>
                {monteCarloData.histogram_data && monteCarloData.histogram_data.length > 0 && (
                  <ResponsiveContainer width="100%" height={280}>
                    <BarChart data={monteCarloData.histogram_data}><CartesianGrid strokeDasharray="3 3" stroke="var(--border)" /><XAxis dataKey="bin" tickFormatter={(v) => formatCurrency(v)} stroke="var(--text-secondary)" /><YAxis stroke="var(--text-secondary)" /><Tooltip formatter={(v) => [v, 'Count']} labelFormatter={(l) => formatCurrency(l)} /><Bar dataKey="count" fill="#6d7380" /></BarChart>
                  </ResponsiveContainer>
                )}
              </div>
            )}
          </div>
        )}

        {activeTab === 'Dashboard' && (
          <div className="dashboard-grid" style={{ paddingTop: 0 }}>
            <div style={{ gridColumn: '1 / -1' }}>
              <Hero
                loading={loading}
                portfolio={portfolio}
                performance={performance}
                formatCurrency={formatCurrency}
                formatPercentSigned={formatPercentSigned}
                timeAgo={timeAgo}
                positionsCount={positionsCount}
                pairsCount={pairs.length}
                daysRunning={daysRunning}
                history={history}
              />
            </div>

            <div className="dashboard-main">
              <EquityChartPanel
                chartMode={chartMode}
                setChartMode={setChartMode}
                chartRange={chartRange}
                setChartRange={setChartRange}
                chartData={chartData}
                candleTicker={candleTicker}
                setCandleTicker={setCandleTicker}
                candleBars={candleBars}
                candleLoading={candleLoading}
                candleError={candleError}
                loading={loading}
                backtestResult={backtestResult}
                formatCurrency={formatCurrency}
                onRequestBacktest={() => setActiveTab('Backtest')}
              />

              <div className="dashboard-widgets-row">
                <div className="card">
                  <h2>Allocation</h2>
                  {loading && !portfolio ? (
                    <div className="skeleton skeleton-widget" />
                  ) : (
                    <AllocationHeatmap positions={positionsFromPortfolio} formatPercent={formatPercent} />
                  )}
                </div>
                <div className="card">
                  <h2>Strategy outlook</h2>
                  {loading && !performance && !monteCarloData ? (
                    <div className="skeleton skeleton-widget" style={{ minHeight: 220 }} />
                  ) : (
                    <ConfidenceRing
                      monteCarloData={monteCarloData}
                      liveSharpe={liveSharpe}
                      historyLength={history.length}
                    />
                  )}
                </div>
              </div>

              {/* Backtest vs Live */}
              <div className="card">
                <h2>Backtest vs Live</h2>
                {backtestResult && (backtestResult.total_return !== undefined) && performance ? (
                  <>
                    <table className="comparison-table">
                      <thead><tr><th>Metric</th><th>Backtest</th><th>Live</th><th>Gap</th></tr></thead>
                      <tbody>
                        <tr
                          className={
                            (performance.total_return ?? 0) - (backtestResult.total_return ?? 0) >= 0
                              ? 'row-profit-zone'
                              : 'row-loss-zone'
                          }
                        >
                          <td>Total Return</td>
                          <td className={`num-mono ${(backtestResult.total_return ?? 0) >= 0 ? 'num-positive' : 'num-negative'}`}>{formatPercentSigned(backtestResult.total_return ?? 0)}</td>
                          <td className={`num-mono ${(performance.total_return ?? 0) >= 0 ? 'num-positive' : 'num-negative'}`}>{formatPercentSigned(performance.total_return ?? 0)}</td>
                          <td className={`num-mono ${((performance.total_return ?? 0) - (backtestResult.total_return ?? 0)) >= 0 ? 'num-positive' : 'num-negative'}`}>{formatPercentSigned((performance.total_return ?? 0) - (backtestResult.total_return ?? 0))}</td>
                        </tr>
                        <tr
                          className={
                            (() => {
                              const g = liveSharpe != null && backtestResult.sharpe_ratio != null ? liveSharpe - backtestResult.sharpe_ratio : null;
                              if (g == null) return '';
                              return g >= 0 ? 'row-profit-zone' : 'row-loss-zone';
                            })()
                          }
                        >
                          <td>Sharpe Ratio</td>
                          <td className="num-mono">{backtestResult.sharpe_ratio != null ? Number(backtestResult.sharpe_ratio).toFixed(2) : '—'}</td>
                          <td className="num-mono">{liveSharpe != null ? liveSharpe.toFixed(2) : '—'}</td>
                          <td className="num-mono">{liveSharpe != null && backtestResult.sharpe_ratio != null ? `${liveSharpe - backtestResult.sharpe_ratio >= 0 ? '↑ ' : '↓ '}${Math.abs(liveSharpe - backtestResult.sharpe_ratio).toFixed(2)}` : '—'}</td>
                        </tr>
                        <tr
                          className={
                            (() => {
                              const g = liveMaxDrawdown != null && backtestResult.max_drawdown != null ? liveMaxDrawdown - backtestResult.max_drawdown : null;
                              if (g == null) return '';
                              return g >= 0 ? 'row-profit-zone' : 'row-loss-zone';
                            })()
                          }
                        >
                          <td>Max Drawdown</td>
                          <td className="num-mono num-negative">{formatPercentSigned(backtestResult.max_drawdown ?? 0)}</td>
                          <td className="num-mono num-negative">{liveMaxDrawdown != null ? formatPercentSigned(liveMaxDrawdown) : '—'}</td>
                          <td className="num-mono">{liveMaxDrawdown != null && backtestResult.max_drawdown != null ? (liveMaxDrawdown - backtestResult.max_drawdown >= 0 ? '+' : '') + formatPercentSigned(liveMaxDrawdown - backtestResult.max_drawdown) : '—'}</td>
                        </tr>
                      </tbody>
                    </table>
                    <p className="comparison-note">Gap reflects execution costs, slippage, and timing.</p>
                  </>
                ) : (
                  <>
                    <table className="comparison-table">
                      <thead><tr><th>Metric</th><th>Backtest</th><th>Live</th><th>Gap</th></tr></thead>
                      <tbody>
                        <tr className="placeholder-row"><td>Total Return</td><td>—</td><td>—</td><td>—</td></tr>
                        <tr className="placeholder-row"><td>Sharpe Ratio</td><td>—</td><td>—</td><td>—</td></tr>
                        <tr className="placeholder-row"><td>Max Drawdown</td><td>—</td><td>—</td><td>—</td></tr>
                      </tbody>
                    </table>
                    <div className="empty-state" style={{ paddingTop: '1rem', paddingBottom: 0 }}>
                      <p style={{ marginBottom: '0.75rem' }}>No backtest data yet. Run your first backtest to see comparison.</p>
                      <button type="button" className="empty-state-cta" onClick={() => setActiveTab('Backtest')}>Run your first backtest to see comparison →</button>
                    </div>
                  </>
                )}
              </div>
            </div>

            <div className="dashboard-sidebar">
              {/* Current Holdings */}
              <div className="card">
                <h2>Current Holdings</h2>
                {loading && !portfolio ? (
                  <div className="skeleton skeleton-line" style={{ height: 24, marginBottom: 8 }} />
                ) : positionsFromPortfolio.length > 0 ? (
                  <>
                    <ul className="holdings-compact-list">
                      {positionsFromPortfolio.slice(0, 8).map((row) => (
                        <li key={row.symbol}>
                          <span><strong>{row.symbol}</strong> {row.qty} · <span className={(row.pnl_pct ?? 0) >= 0 ? 'positive' : 'negative'}>{row.pnl_pct != null ? formatPercentSigned(row.pnl_pct) : '—'}</span></span>
                          <span className={`holdings-compact-badge ${row.qty >= 0 ? 'long' : 'short'}`}>{row.qty >= 0 ? 'LONG' : 'SHORT'}</span>
                        </li>
                      ))}
                    </ul>
                    <button type="button" className="card-link" onClick={() => setActiveTab('Portfolio')}>View all positions →</button>
                  </>
                ) : (
                  <p className="empty-placeholder">No open positions.</p>
                )}
              </div>

              {/* Recent Activity */}
              <div className="card">
                <h2>Recent Activity</h2>
                {loading && trades.length === 0 ? (
                  <div className="skeleton skeleton-line" style={{ height: 20, marginBottom: 8 }} />
                ) : recentTrades.length > 0 ? (
                  <>
                    {recentTrades.map((trade) => (
                      <div key={trade.id} className="activity-row">
                        <span>{new Date(trade.timestamp).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}</span>
                        <span><strong>{trade.ticker}</strong></span>
                        <span className={trade.side === 'BUY' ? 'buy' : 'sell'}>{trade.side}</span>
                        <span>{trade.qty}</span>
                      </div>
                    ))}
                    <button type="button" className="card-link" onClick={() => setActiveTab('Trades')}>View full history →</button>
                  </>
                ) : (
                  <div className="empty-state">
                    <p>No trades yet. Run your first backtest to start trading.</p>
                    <button type="button" className="empty-state-cta" onClick={() => setActiveTab('Backtest')}>Run backtest →</button>
                  </div>
                )}
              </div>

              {/* Monte Carlo Summary */}
              <div className="card">
                <h2>Monte Carlo Summary</h2>
                {monteCarloData && !monteCarloData.error ? (
                  <>
                    <div className="mc-summary-bar">
                      <div className="mc-summary-segment" style={{ width: '30%', background: '#5a4a4a' }} title="5th %" />
                      <div className="mc-summary-segment" style={{ width: '40%', background: '#4a5058' }} title="50th %" />
                      <div className="mc-summary-segment" style={{ width: '30%', background: '#4a5c4e' }} title="95th %" />
                    </div>
                    <div className="hero-stat"><span className="label">5th / 50th / 95th</span> {formatCurrency(monteCarloData.percentiles?.[5] ?? 0)} / {formatCurrency(monteCarloData.percentiles?.[50] ?? 0)} / {formatCurrency(monteCarloData.percentiles?.[95] ?? 0)}</div>
                    <div className="mc-summary-prob">Probability of profit: {((monteCarloData.probability_profit ?? 0) * 100).toFixed(1)}%</div>
                    <button type="button" className="card-link" onClick={() => setActiveTab('Backtest')}>View full simulation →</button>
                  </>
                ) : (
                  <div className="empty-state">
                    <p>Run a backtest and Monte Carlo to see outcome distribution.</p>
                    <button type="button" className="empty-state-cta" onClick={() => setActiveTab('Backtest')}>Run backtest & Monte Carlo →</button>
                  </div>
                )}
              </div>
            </div>

            {/* Collapsible strategy help */}
            <div style={{ gridColumn: '1 / -1', marginTop: '1rem' }}>
              <button type="button" className="strategy-help-toggle" onClick={() => setStrategyHelpOpen((o) => !o)}>
                {strategyHelpOpen ? '▼' : '▶'} How the strategies work
              </button>
              {strategyHelpOpen && (
                <div className="card strategy-help" style={{ marginTop: '0.5rem' }}>
                  {strategySelect === 'Stat Arb' ? (
                    <div className="help-content">
                      <p><strong>Stat Arb (statistical arbitrage / pairs trading)</strong></p>
                      <p>Trade two <strong>cointegrated</strong> stocks (e.g. AAPL/MSFT, KO/PEP). The spread is log(price_A) − β·log(price_B). When the spread&apos;s <strong>z-score</strong> exceeds the entry threshold, the strategy goes short the spread (sell A, buy B); when z-score is below −entry, it goes long (buy A, sell B). It closes when |z| &lt; exit threshold.</p>
                      <div className="z-score-explainer">
                        <h3>What is Z-Score?</h3>
                        <p>Measures how far the price spread is from normal:</p>
                        <ul>
                          <li><strong>Z = 0:</strong> Spread is at historical average (neutral)</li>
                          <li><strong>Z = +2:</strong> Stock A is expensive vs Stock B (sell A, buy B)</li>
                          <li><strong>Z = -2:</strong> Stock A is cheap vs Stock B (buy A, sell B)</li>
                          <li><strong>|Z| &lt; 0.5:</strong> Close position (back to normal)</li>
                        </ul>
                      </div>
                    </div>
                  ) : strategySelect === 'MA Crossover' ? (
                    <div className="help-content">
                      <p><strong>MA Crossover (moving average crossover)</strong></p>
                      <p><strong>Short MA</strong> and <strong>Long MA</strong> are the number of trading days used to compute two moving averages of the stock&apos;s closing price. The short MA reacts faster to recent prices; the long MA is smoother.</p>
                      <p><strong>Buy:</strong> when the short MA crosses above the long MA (short &gt; long). <strong>Sell:</strong> when the short MA crosses below the long MA.</p>
                      <p>Example: 50/200 means buy when the 50-day average is above the 200-day average.</p>
                    </div>
                  ) : (
                    <div className="help-content">
                      <p><strong>Momentum</strong></p>
                      <p>The strategy looks at the stock&apos;s <strong>total return over the last N days</strong> (the lookback). If that return is positive, it goes long; if negative, it goes to cash.</p>
                      <p><strong>Lookback (days)</strong> is that N: e.g. 120 ≈ 6 months. Shorter lookback reacts faster; longer follow longer-term trend.</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;