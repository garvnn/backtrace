import React, { useMemo, useRef, useState, useEffect, useLayoutEffect } from 'react';

function HeroSparkline({ history, positive }) {
  const pts = useMemo(() => {
    const h = history || [];
    const slice = h.slice(-40);
    if (slice.length < 2) return null;
    const vals = slice.map((x) => x.portfolio_value).filter((v) => v != null && v > 0);
    return vals.length >= 2 ? vals : null;
  }, [history]);

  if (!pts) return null;

  const min = Math.min(...pts);
  const max = Math.max(...pts);
  const pw = 96;
  const ph = 28;
  const pad = 2;
  const normY = (v) =>
    max === min ? ph / 2 : ph - pad - ((v - min) / (max - min)) * (ph - 2 * pad);
  const d = pts
    .map((v, i) => {
      const x = pad + (i / (pts.length - 1)) * (pw - 2 * pad);
      const y = normY(v);
      return `${i === 0 ? 'M' : 'L'} ${x} ${y}`;
    })
    .join(' ');

  const stroke = positive ? 'var(--positive)' : 'var(--negative)';

  return (
    <svg className="hero-sparkline" width={pw} height={ph} viewBox={`0 0 ${pw} ${ph}`} aria-hidden>
      <path d={d} fill="none" stroke={stroke} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" opacity={0.85} />
    </svg>
  );
}

function useAnimatedPortfolioValue(target, initialCapital, enabled) {
  const [display, setDisplay] = useState(0);
  const endRef = useRef(initialCapital ?? 0);
  const ranRef = useRef(false);
  const wasEnabledRef = useRef(false);

  useLayoutEffect(() => {
    if (enabled && !wasEnabledRef.current && target != null && Number.isFinite(target)) {
      const start = initialCapital ?? target;
      setDisplay(start);
      endRef.current = start;
      ranRef.current = false;
    }
    wasEnabledRef.current = enabled;
  }, [enabled, initialCapital, target]);

  useEffect(() => {
    if (!enabled || target == null || !Number.isFinite(target)) return;
    const from = ranRef.current ? endRef.current : (initialCapital ?? target);
    const to = target;
    const rel = Math.abs(to - from) / Math.max(Math.abs(from), 1);
    if (ranRef.current && rel < 0.0005) {
      setDisplay(to);
      endRef.current = to;
      return;
    }
    ranRef.current = true;
    const duration = 480;
    const t0 = performance.now();
    const ease = (t) => 1 - (1 - t) ** 3;
    let frame;
    const tick = (now) => {
      const p = Math.min(1, (now - t0) / duration);
      setDisplay(from + (to - from) * ease(p));
      if (p < 1) frame = requestAnimationFrame(tick);
      else {
        endRef.current = to;
      }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, enabled, initialCapital]);

  return display;
}

export function Hero({
  loading,
  portfolio,
  performance,
  formatCurrency,
  formatPercentSigned,
  timeAgo,
  positionsCount,
  pairsCount,
  daysRunning,
  history,
}) {
  const rawValue = portfolio?.portfolio_value ?? performance?.current_value ?? 0;
  const initialCapital = performance?.initial_value ?? 100000;
  const hasData = !loading && (portfolio != null || performance != null);
  const displayValue = useAnimatedPortfolioValue(rawValue, initialCapital, hasData);

  const totalRet = performance?.total_return ?? 0;
  const positive = totalRet >= 0;

  if (loading && !portfolio && !performance) {
    return (
      <div className="hero hero--loading">
        <div className="skeleton skeleton-hero-value" style={{ marginBottom: 'var(--space-2)' }} />
        <div className="hero-secondary">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="skeleton skeleton-hero-stat" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className={`hero ${positive ? '' : 'hero--loss'}`}>
      <div className="hero-primary">
        <div className="hero-value-wrap">
          <span className="hero-value num-mono">{formatCurrency(displayValue)}</span>
        </div>
        <div className="hero-return-row">
          {performance && (
            <span className={`hero-return ${positive ? 'positive' : 'negative'}`}>
              {formatPercentSigned(totalRet)}
            </span>
          )}
          <HeroSparkline history={history} positive={positive} />
        </div>
      </div>
      <div className="hero-secondary">
        <span className="hero-stat">
          <strong>Cash</strong> <span className="num-mono">{formatCurrency(portfolio?.cash ?? 0)}</span>
        </span>
        <span className="hero-stat">
          <strong>Positions</strong> <span className="num-mono">{positionsCount}</span>
        </span>
        {pairsCount > 0 && (
          <span className="hero-stat">
            <strong>Pairs</strong> <span className="num-mono">{pairsCount}</span>
          </span>
        )}
        {daysRunning != null && (
          <span className="hero-stat">
            <strong>Days running</strong> <span className="num-mono">{daysRunning}</span>
          </span>
        )}
        <span className="hero-stat">
          <strong>Strategy</strong> {portfolio?.strategy ?? '—'}
        </span>
        {portfolio?.timestamp && (
          <span className="hero-stat">
            <strong>Last updated</strong> {timeAgo(portfolio.timestamp)}
          </span>
        )}
      </div>
    </div>
  );
}
