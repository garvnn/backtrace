"""
Core backtesting engine.
Signal at end of bar T uses data through Close[T]; fills at Open[T+1].
Sizing matches live: capped notional, buying-power fraction, integer shares.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from trading_constants import (
    INITIAL_CAPITAL,
    MAX_DOLLAR_PER_STOCK,
    BUYING_POWER_FRACTION,
    PAIR_CAPITAL_FRACTION,
    DEFAULT_COMMISSION,
)


class BacktestEngine:
    def __init__(
        self,
        initial_capital=None,
        commission=None,
        max_dollar_per_stock=None,
        buying_power_fraction=None,
        pair_capital_fraction=None,
    ):
        self.initial_capital = float(initial_capital if initial_capital is not None else INITIAL_CAPITAL)
        self.commission = float(commission if commission is not None else DEFAULT_COMMISSION)
        self.max_dollar_per_stock = float(
            max_dollar_per_stock if max_dollar_per_stock is not None else MAX_DOLLAR_PER_STOCK
        )
        self.buying_power_fraction = float(
            buying_power_fraction if buying_power_fraction is not None else BUYING_POWER_FRACTION
        )
        self.pair_capital_fraction = float(
            pair_capital_fraction if pair_capital_fraction is not None else PAIR_CAPITAL_FRACTION
        )

    def run_buyhold(self, data):
        """Buy once on first T+1 open (after day 0), hold; equity marked daily at Close."""
        opens = data["Open"].astype(float)
        closes = data["Close"].astype(float)
        cash = self.initial_capital
        shares = 0
        portfolio_values = []
        trades = 0

        for i in range(len(data)):
            if i == 0:
                portfolio_values.append(cash + shares * float(closes.iloc[i]))
                continue
            exec_open = float(opens.iloc[i])
            ref_close = float(closes.iloc[i - 1])
            if shares == 0 and exec_open > 0 and ref_close > 0:
                dollar = min(self.max_dollar_per_stock, cash * self.buying_power_fraction)
                qty = int(dollar / ref_close)
                if qty > 0:
                    gross = qty * exec_open
                    cash -= gross * (1.0 + self.commission)
                    shares = qty
                    trades = 1
            pv = cash + shares * float(closes.iloc[i])
            portfolio_values.append(pv)

        portfolio_values = pd.Series(portfolio_values, index=data.index)
        total_return = (float(portfolio_values.iloc[-1]) / self.initial_capital) - 1.0

        return {
            "portfolio_values": portfolio_values,
            "total_return": total_return,
            "trades": trades,
            "trade_returns": [],
        }

    def run(self, data, strategy):
        signals = strategy.generate_signals(data)
        opens = data["Open"].astype(float)
        closes = data["Close"].astype(float)
        cash = self.initial_capital
        shares = 0
        portfolio_values = []
        trades = 0
        entry_invested = None
        trade_returns = []

        for i in range(len(data)):
            if i == 0:
                portfolio_values.append(cash + shares * float(closes.iloc[i]))
                continue

            exec_open = float(opens.iloc[i])
            ref_close = float(closes.iloc[i - 1])
            sig_prev = int(signals.iloc[i - 1])

            if sig_prev == 1 and shares == 0 and exec_open > 0 and ref_close > 0:
                entry_invested = cash
                dollar = min(self.max_dollar_per_stock, cash * self.buying_power_fraction)
                qty = int(dollar / ref_close)
                if qty > 0:
                    gross = qty * exec_open
                    cash -= gross * (1.0 + self.commission)
                    shares = qty
                    trades += 1
                else:
                    entry_invested = None
            elif sig_prev == 0 and shares > 0 and exec_open > 0:
                gross = shares * exec_open
                cash += gross * (1.0 - self.commission)
                if entry_invested is not None and entry_invested > 0:
                    trade_returns.append((cash - entry_invested) / entry_invested)
                entry_invested = None
                shares = 0
                trades += 1

            pv = cash + shares * float(closes.iloc[i])
            portfolio_values.append(pv)

        portfolio_values = pd.Series(portfolio_values, index=data.index)
        total_return = (float(portfolio_values.iloc[-1]) / self.initial_capital) - 1.0

        return {
            "portfolio_values": portfolio_values,
            "total_return": total_return,
            "trades": trades,
            "trade_returns": trade_returns,
        }

    def run_pair(self, data_a, data_b, strategy):
        from strategies.stat_arb import StatArbStrategy

        if not isinstance(strategy, StatArbStrategy):
            raise TypeError("run_pair requires StatArbStrategy")
        common = data_a.index.intersection(data_b.index)
        data_a = data_a.loc[common].sort_index()
        data_b = data_b.loc[common].sort_index()
        if len(data_a) < strategy.lookback or len(data_b) < strategy.lookback:
            pv = pd.Series([self.initial_capital] * len(data_a), index=data_a.index)
            return {"portfolio_values": pv, "total_return": 0.0, "trades": 0, "trade_returns": []}

        signal_a, signal_b = strategy.generate_signals_pair(data_a, data_b)
        oa = data_a["Open"].astype(float)
        ob = data_b["Open"].astype(float)
        ca = data_a["Close"].astype(float)
        cb = data_b["Close"].astype(float)

        cash = self.initial_capital
        shares_a = 0
        shares_b = 0
        state = "flat"
        portfolio_values = []
        trades = 0
        entry_pv = None
        trade_returns = []
        lookback = strategy.lookback

        def beta_at(i):
            if i < lookback:
                return 1.0
            wa = data_a["Close"].iloc[i - lookback : i].values.astype(float)
            wb = data_b["Close"].iloc[i - lookback : i].values.astype(float)
            if len(wa) < 2:
                return 1.0
            return float(np.polyfit(wb, wa, 1)[0])

        def pair_capital(i):
            if i == 0:
                refa, refb = float(ca.iloc[0]), float(cb.iloc[0])
            else:
                refa, refb = float(ca.iloc[i - 1]), float(cb.iloc[i - 1])
            equity = cash + shares_a * refa + shares_b * refb
            bp = max(0.0, equity) * self.buying_power_fraction
            return bp * self.pair_capital_fraction, refa, refb

        def open_long_spread(i):
            nonlocal cash, shares_a, shares_b, trades, state, entry_pv
            b = beta_at(i)
            capital, refa, refb = pair_capital(i)
            if refa <= 0 or refb <= 0:
                return
            qty_a = int(capital / refa)
            qty_b = int((capital / refb) * b)
            if qty_a <= 0 or qty_b <= 0:
                return
            poa, pob = float(oa.iloc[i]), float(ob.iloc[i])
            na, nb = qty_a * poa, qty_b * pob
            cash = cash - na + nb
            cash -= (na + nb) * self.commission
            shares_a, shares_b = qty_a, -qty_b
            state = "long_spread"
            trades += 1
            entry_pv = cash + shares_a * float(ca.iloc[i]) + shares_b * float(cb.iloc[i])

        def open_short_spread(i):
            nonlocal cash, shares_a, shares_b, trades, state, entry_pv
            b = beta_at(i)
            capital, refa, refb = pair_capital(i)
            if refa <= 0 or refb <= 0:
                return
            qty_a = int(capital / refa)
            qty_b = int((capital / refb) * b)
            if qty_a <= 0 or qty_b <= 0:
                return
            poa, pob = float(oa.iloc[i]), float(ob.iloc[i])
            na, nb = qty_a * poa, qty_b * pob
            cash = cash + na - nb
            cash -= (na + nb) * self.commission
            shares_a, shares_b = -qty_a, qty_b
            state = "short_spread"
            trades += 1
            entry_pv = cash + shares_a * float(ca.iloc[i]) + shares_b * float(cb.iloc[i])

        def close_pair(i):
            nonlocal cash, shares_a, shares_b, trades, state, entry_pv
            poa, pob = float(oa.iloc[i]), float(ob.iloc[i])
            cash = cash + shares_a * poa + shares_b * pob
            cash -= (abs(shares_a * poa) + abs(shares_b * pob)) * self.commission
            if entry_pv is not None and entry_pv > 0:
                flat_pv = cash
                trade_returns.append((flat_pv - entry_pv) / entry_pv)
            shares_a, shares_b = 0, 0
            state = "flat"
            trades += 1
            entry_pv = None

        for i in range(len(data_a)):
            if i == 0:
                portfolio_values.append(cash + shares_a * float(ca.iloc[i]) + shares_b * float(cb.iloc[i]))
                continue

            sa = int(signal_a.iloc[i - 1])
            sb = int(signal_b.iloc[i - 1])

            if state == "flat":
                if sa == 1 and sb == -1:
                    open_long_spread(i)
                elif sa == -1 and sb == 1:
                    open_short_spread(i)
            elif state == "long_spread":
                if sa == 0 and sb == 0:
                    close_pair(i)
                elif sa == -1 and sb == 1:
                    close_pair(i)
                    open_short_spread(i)
            elif state == "short_spread":
                if sa == 0 and sb == 0:
                    close_pair(i)
                elif sa == 1 and sb == -1:
                    close_pair(i)
                    open_long_spread(i)

            pv = cash + shares_a * float(ca.iloc[i]) + shares_b * float(cb.iloc[i])
            portfolio_values.append(pv)

        portfolio_values = pd.Series(portfolio_values, index=data_a.index)
        total_return = (float(portfolio_values.iloc[-1]) / self.initial_capital) - 1.0
        return {
            "portfolio_values": portfolio_values,
            "total_return": total_return,
            "trades": trades,
            "trade_returns": trade_returns,
        }


if __name__ == "__main__":
    from data.loader import load_data

    print("Testing backtest engine...")
    data = load_data("AAPL", "2020-01-01", "2024-12-31")

    engine = BacktestEngine(initial_capital=INITIAL_CAPITAL)
    results = engine.run_buyhold(data)

    print(f"\nInitial Capital: ${engine.initial_capital:,.2f}")
    print(f"Final Value: ${float(results['portfolio_values'].iloc[-1]):,.2f}")
    print(f"Total Return: {results['total_return']:.2%}")

    from strategies.mean_reversion import MeanReversionStrategy

    strategy = MeanReversionStrategy()
    results_strategy = engine.run(data, strategy)

    print(f"\n--- Strategy Results ---")
    print(f"Total Return: {results_strategy['total_return']:.2%}")
    print(f"Number of Trades: {results_strategy['trades']}")
