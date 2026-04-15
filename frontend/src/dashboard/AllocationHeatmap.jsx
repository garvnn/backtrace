import React, { useMemo } from 'react';

function tileColor(weight, isShort) {
  const t = Math.min(1, Math.max(0, weight));
  if (isShort) {
    const a = 0.12 + t * 0.38;
    return `rgba(248, 113, 113, ${a})`;
  }
  const a = 0.12 + t * 0.42;
  return `rgba(52, 211, 153, ${a})`;
}

export function AllocationHeatmap({ positions, formatPercent }) {
  const { tiles, hasPrices } = useMemo(() => {
    const rows = positions || [];
    let has = false;
    const notionals = rows.map((r) => {
      const px = r.current_price;
      if (px != null && px > 0) has = true;
      const q = Number(r.qty ?? 0);
      const n = px != null && px > 0 ? Math.abs(q) * px : 0;
      return { row: r, notional: n, isShort: q < 0 };
    });
    const total = notionals.reduce((s, x) => s + x.notional, 0);
    if (!has || total <= 0) {
      return {
        tiles: rows.map((r) => ({
          symbol: r.symbol,
          pct: null,
          weight: 0,
          isShort: Number(r.qty) < 0,
        })),
        hasPrices: false,
      };
    }
    return {
      tiles: notionals.map(({ row, notional, isShort }) => ({
        symbol: row.symbol,
        pct: notional / total,
        weight: notional / total,
        isShort,
      })),
      hasPrices: true,
    };
  }, [positions]);

  if (!tiles.length) {
    return <p className="allocation-empty">No positions to chart.</p>;
  }

  if (!hasPrices) {
    return (
      <p className="allocation-empty">
        Open prices are not available yet. Allocation weights require live quotes from the API.
      </p>
    );
  }

  return (
    <div className="allocation-heatmap">
      {tiles.map((t) => (
        <div
          key={t.symbol}
          className="allocation-tile"
          style={{
            background: tileColor(t.weight, t.isShort),
            borderColor: t.isShort ? 'rgba(248,113,113,0.45)' : 'rgba(52,211,153,0.35)',
          }}
        >
          <span className="allocation-tile-symbol">{t.symbol}</span>
          <span className="allocation-tile-pct num-mono">{formatPercent(t.pct)}</span>
        </div>
      ))}
    </div>
  );
}
