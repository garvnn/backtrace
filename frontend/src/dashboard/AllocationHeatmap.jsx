import React, { useMemo } from 'react';

function tileColor(weight, isShort) {
  const t = Math.min(1, Math.max(0, weight));
  if (isShort) {
    const L = 24 + Math.round(t * 10);
    return `hsl(0, 9%, ${L}%)`;
  }
  const L = 26 + Math.round(t * 11);
  return `hsl(135, 7%, ${L}%)`;
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
            borderColor: t.isShort ? 'hsl(0, 8%, 32%)' : 'hsl(135, 6%, 32%)',
          }}
        >
          <span className="allocation-tile-symbol">{t.symbol}</span>
          <span className="allocation-tile-pct num-mono">{formatPercent(t.pct)}</span>
        </div>
      ))}
    </div>
  );
}
