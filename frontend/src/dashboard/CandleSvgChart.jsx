import React, { useRef, useState, useEffect, useCallback } from 'react';

const PAD = { l: 8, r: 8, t: 8, b: 22 };

export function CandleSvgChart({ data, formatCurrency, height = 340 }) {
  const wrapRef = useRef(null);
  const [width, setWidth] = useState(600);
  const [hover, setHover] = useState(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth || 600));
    ro.observe(el);
    setWidth(el.clientWidth || 600);
    return () => ro.disconnect();
  }, []);

  const innerW = Math.max(0, width - PAD.l - PAD.r);
  const innerH = height - PAD.t - PAD.b;

  const onMove = useCallback(
    (e) => {
      if (!data?.length || innerW <= 0) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const x = e.clientX - rect.left - PAD.l;
      const i = Math.round((x / innerW) * (data.length - 1));
      const clamped = Math.max(0, Math.min(data.length - 1, i));
      setHover({ i: clamped, xPx: PAD.l + (clamped / Math.max(1, data.length - 1)) * innerW });
    },
    [data, innerW]
  );

  const onLeave = useCallback(() => setHover(null), []);

  if (!data?.length) {
    return <div ref={wrapRef} style={{ height, minHeight: height }} />;
  }

  let minP = Infinity;
  let maxP = -Infinity;
  data.forEach((d) => {
    minP = Math.min(minP, d.low);
    maxP = Math.max(maxP, d.high);
  });
  if (!Number.isFinite(minP) || minP === maxP) {
    minP -= 1;
    maxP += 1;
  }
  const padY = (maxP - minP) * 0.04;
  minP -= padY;
  maxP += padY;

  const yScale = (p) => PAD.t + innerH - ((p - minP) / (maxP - minP)) * innerH;
  const slot = innerW / data.length;
  const bodyW = Math.max(2, Math.min(10, slot * 0.65));

  const hi = hover?.i;
  const hiRow = hi != null ? data[hi] : null;

  return (
    <div ref={wrapRef} style={{ width: '100%', position: 'relative' }}>
      {hiRow && (
        <div
          className="chart-tooltip-box"
          style={{
            position: 'absolute',
            top: 8,
            right: 8,
            zIndex: 2,
            pointerEvents: 'none',
            minWidth: 160,
          }}
        >
          <div className="chart-tooltip-date">{hiRow.date}</div>
          <div className="chart-tooltip-row">
            <span>O / H / L / C</span>
            <span className="num-mono" style={{ textAlign: 'right', fontSize: '0.75rem' }}>
              {formatCurrency(hiRow.open)} / {formatCurrency(hiRow.high)}
              <br />
              {formatCurrency(hiRow.low)} / {formatCurrency(hiRow.close)}
            </span>
          </div>
        </div>
      )}
      <svg
        width={width}
        height={height}
        style={{ display: 'block' }}
        onMouseMove={onMove}
        onMouseLeave={onLeave}
      >
        <rect x={PAD.l} y={PAD.t} width={innerW} height={innerH} fill="rgba(255,255,255,0.02)" rx={0} />
        {hover && (
          <line
            x1={hover.xPx}
            x2={hover.xPx}
            y1={PAD.t}
            y2={PAD.t + innerH}
            stroke="rgba(255,255,255,0.14)"
            strokeWidth={1}
          />
        )}
        {data.map((d, i) => {
          const cx = PAD.l + (i + 0.5) * slot;
          const yO = yScale(d.open);
          const yC = yScale(d.close);
          const yH = yScale(d.high);
          const yL = yScale(d.low);
          const up = d.close >= d.open;
          const stroke = up ? '#6b8f72' : '#a67b7b';
          const fill = up ? 'rgba(107, 143, 114, 0.35)' : 'rgba(166, 123, 123, 0.35)';
          const top = Math.min(yO, yC);
          const h = Math.max(1, Math.abs(yC - yO));
          return (
            <g key={d.date}>
              <line x1={cx} x2={cx} y1={yH} y2={yL} stroke={stroke} strokeWidth={1} opacity={0.9} />
              <rect x={cx - bodyW / 2} y={top} width={bodyW} height={h} fill={fill} stroke={stroke} strokeWidth={1} rx={1} />
            </g>
          );
        })}
      </svg>
    </div>
  );
}
