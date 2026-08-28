"""
Strategy executor - runs BackTrace strategies live.
"""

import os
import sys
import time
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd

from strategies.momentum import MomentumStrategy
from strategies.ma_crossover import MACrossoverStrategy
from strategies.stat_arb import StatArbStrategy

from database import Database
from snapshot_health import (
    EMPTY_POSITIONS_VALUE_IS_CASH,
    SNAPSHOT_RETRY_DELAY_SECONDS,
    reconcile_snapshot,
)
from alpaca_retry import with_retry
from trading.sizing import SessionBudget, SizingPolicy, default_policy
from trading_constants import ALPACA_DATA_FEED, PAIR_CAPITAL_FRACTION


def _resolve_feed():
    """
    Which market-data feed to request, explicitly.

    Left unset, the server picks - IEX on the free plan. Since this project
    measures Alpaca-vs-Yahoo close divergence, the feed is a variable in the
    measurement, not an implementation detail to inherit silently.
    """
    name = (os.getenv("ALPACA_DATA_FEED") or ALPACA_DATA_FEED or "iex").strip().lower()
    try:
        return DataFeed(name)
    except ValueError:
        print(f"Unknown ALPACA_DATA_FEED {name!r}; falling back to IEX")
        return DataFeed.IEX

# Load .env from live/ so it works when run as "python live/executor.py" from project root
LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
_env_path = os.path.join(LIVE_DIR, ".env")
load_dotenv(_env_path)
DB_PATH = os.getenv("DB_PATH") or os.path.join(LIVE_DIR, "trading.db")

def _to_float(value):
    """Float or None. Alpaca returns these as strings, and as None before a fill."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _order_status(order):
    """
    Alpaca order status as its wire value, e.g. "accepted".

    str(order.status) yields the Python enum repr "OrderStatus.ACCEPTED", which
    previously leaked all the way into the database and then into the browser,
    where the frontend stripped the "OrderStatus." prefix back off.
    """
    return getattr(order.status, "value", str(order.status))


def _bars_to_backtrace_df(df_one):
    """Convert Alpaca bars DataFrame (single symbol) to BackTrace format: Date index, Open/High/Low/Close/Volume."""
    df = df_one.reset_index()
    df = df.rename(columns={
        'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume',
        'timestamp': 'Date'
    })
    if 'Date' in df.columns:
        df = df.set_index('Date')
    return df


class StrategyExecutor:
    def __init__(self, strategy, ticker='AAPL', params=None, session_budget=None,
                 sizing=None):
        self.strategy = strategy
        self.ticker = ticker
        self.params = params  # optional dict e.g. short_window, long_window, lookback_period for logging
        self.session_budget = session_budget  # optional SessionBudget shared across a batch run
        # The same policy BacktestEngine sizes with, so a given (capital,
        # price) pair produces the same share count on both sides. Overridable
        # for tests; see trading/sizing.py for why this is shared at all.
        self.sizing = sizing if sizing is not None else default_policy()
        api_key = os.getenv('ALPACA_API_KEY')
        secret_key = os.getenv('ALPACA_SECRET_KEY')
        if not api_key or not secret_key:
            raise ValueError(
                "Missing Alpaca keys. Create live/.env with ALPACA_API_KEY and ALPACA_SECRET_KEY "
                "(get paper keys at https://app.alpaca.markets/paper/dashboard/apis)."
            )
        # Alpaca clients (paper=True for paper trading)
        self.trading_client = TradingClient(api_key, secret_key, paper=True)
        
        self.data_client = StockHistoricalDataClient(api_key, secret_key)
        self.db = Database(DB_PATH)
    
    def _is_stat_arb(self):
        return isinstance(self.strategy, StatArbStrategy) or self.strategy.name == "Stat Arb"

    def get_historical_data(self, days=300, symbols=None):
        """Get historical price data from Alpaca. If symbols is a list of 2, returns (df_a, df_b)."""
        syms = symbols if symbols is not None else [self.ticker]
        request = StockBarsRequest(
            symbol_or_symbols=syms,
            timeframe=TimeFrame.Day,
            # UTC, not host-local. datetime.now() without a tz asks for a
            # window whose meaning depends on where the process runs - this
            # trades a New York market from UTC containers, and was developed
            # on a laptop in Eastern. StockBarsRequest strips the tzinfo when
            # it normalises, so req.start reads naive afterwards; the value it
            # keeps is the UTC one.
            start=datetime.now(timezone.utc) - timedelta(days=days),
            adjustment=Adjustment.ALL,
            feed=_resolve_feed(),
        )
        bars = with_retry(
            lambda: self.data_client.get_stock_bars(request),
            description=f"get_stock_bars({','.join(syms)})",
        )
        df = getattr(bars, 'df', pd.DataFrame())
        if df.empty:
            return (pd.DataFrame(), pd.DataFrame()) if len(syms) == 2 else pd.DataFrame()
        # Alpaca multi-symbol: index can be (timestamp, symbol) or just timestamp with symbol in columns
        if isinstance(df.index, pd.MultiIndex) and 'symbol' in (df.index.names or []):
            df = df.reset_index()
            out = []
            for s in syms:
                sub = df[df['symbol'] == s].copy()
                sub = sub.rename(columns={
                    'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume',
                    'timestamp': 'Date'
                })
                if 'Date' in sub.columns:
                    sub = sub.set_index('Date')
                out.append(sub[['Open', 'High', 'Low', 'Close', 'Volume']] if 'Open' in sub.columns else sub)
            if len(syms) == 1:
                return out[0]
            return out[0], out[1]
        # Single symbol or flat columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        df = df.rename(columns={
            'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume',
            'timestamp': 'Date'
        })
        if 'Date' in df.columns:
            df = df.set_index('Date')
        if len(syms) == 1:
            return df
        # Two symbols in one df with multiindex columns (symbol, ohlcv) - split
        if len(syms) == 2 and isinstance(bars.df.columns, pd.MultiIndex):
            a, b = syms[0], syms[1]
            df_a = bars.df[a].copy() if a in bars.df.columns.get_level_values(0) else pd.DataFrame()
            df_b = bars.df[b].copy() if b in bars.df.columns.get_level_values(0) else pd.DataFrame()
            if not df_a.empty:
                df_a = _bars_to_backtrace_df(df_a)
            if not df_b.empty:
                df_b = _bars_to_backtrace_df(df_b)
            return df_a, df_b
        return df

    def get_historical_data_pair(self, ticker_a, ticker_b, days=300):
        """Get two aligned DataFrames for a pair. Returns (df_a, df_b) with common index."""
        df_a, df_b = self.get_historical_data(days=days, symbols=[ticker_a, ticker_b])
        if df_a.empty or df_b.empty:
            return df_a, df_b
        common = df_a.index.intersection(df_b.index)
        return df_a.loc[common].sort_index(), df_b.loc[common].sort_index()

    def get_current_position(self, symbol=None):
        """
        Signed quantity held for a symbol (default self.ticker). 0 means flat.

        Fails closed: if Alpaca cannot be reached, this raises rather than
        returning 0. It previously swallowed every exception and reported "flat",
        which meant a 429, an expired key, or a transient 5xx looked identical to
        holding nothing - and execute_signal treats "flat" as permission to buy.
        A single failed position read could therefore open a second position on
        top of an existing one. Callers (the scheduler's per-ticker try/except)
        skip the ticker instead, which is the safe outcome.
        """
        sym = symbol if symbol is not None else self.ticker
        positions = with_retry(
            self.trading_client.get_all_positions, description="get_all_positions"
        )
        for pos in positions:
            if pos.symbol == sym:
                return float(pos.qty)
        return 0

    def _serialize_signal(self, signal):
        """Normalize signal value to stable string."""
        try:
            return str(int(signal))
        except Exception:
            return str(signal)

    def _log_execution_event(self, ticker, signal, action, reason, details):
        """Persist execution decision for audit/debugging."""
        self.db.log_execution(
            strategy=self.strategy.name,
            ticker=ticker,
            signal=self._serialize_signal(signal),
            action=action,
            reason=reason,
            details=details,
        )
    
    def execute_signal(self, signal, data):
        """
        Place an order when the signal changes. Idempotent on signal state.

        Sizing goes through self.sizing, the same SizingPolicy the backtest
        uses, against account cash rather than buying_power - see
        trading/sizing.py.
        """
        current_position = self.get_current_position()
        account = with_retry(self.trading_client.get_account, description="get_account")
        # Cash, not buying_power. buying_power on a margin paper account is
        # roughly 2x equity, and sizing against it is what drove production
        # cash to -$6,830.22 on 2026-07-10 while the backtest, sizing off cash,
        # modelled nothing of the sort. See trading/sizing.py.
        available_capital = float(account.cash)
        last_signal = self.db.get_last_executed_signal(self.strategy.name, self.ticker)
        
        print(f"\nCurrent position: {current_position} shares")
        print(f"Signal: {signal}")
        current_price = float(data['Close'].iloc[-1]) if not data.empty else None
        
        # Signal = 1 (buy), 0 (sell/flat). Only place order when signal changed from last executed.
        if signal == 1 and current_position == 0 and last_signal != 1:
            # Same policy object the backtest sizes with, so an identical
            # (capital, price) pair yields an identical share count on both
            # sides. That parity is asserted in live/test_sizing.py.
            session_budget_remaining = self.session_budget.remaining if self.session_budget is not None else None
            dollar_amount = self.sizing.notional(available_capital, session_budget_remaining)
            qty = self.sizing.shares(available_capital, current_price, session_budget_remaining)

            if qty > 0:
                fill_model = self._fill_model()
                order_data = MarketOrderRequest(
                    symbol=self.ticker,
                    qty=qty,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                    client_order_id=self._client_order_id('BUY'),
                )
                order = with_retry(
                    lambda: self.trading_client.submit_order(order_data),
                    description=f"submit_order(BUY {self.ticker})",
                )
                print(f"BUY order placed: {qty} shares")
                if self.session_budget is not None:
                    self.session_budget.reserve(qty * current_price)

                # Log to database
                self.db.log_trade(
                    strategy=self.strategy.name,
                    ticker=self.ticker,
                    side='BUY',
                    qty=qty,
                    price=current_price,
                    order_id=str(order.id),
                    status=_order_status(order),
                    params=self.params,
                    client_order_id=getattr(order, 'client_order_id', None),
                    fill_model=fill_model,
                )
                self._log_execution_event(
                    ticker=self.ticker,
                    signal=signal,
                    action='BUY',
                    reason='entry_buy_signal',
                    details={
                        "current_position": current_position,
                        "last_executed_signal": last_signal,
                        "available_capital": available_capital,
                        "price": current_price,
                        "qty": qty,
                        "max_dollar_per_stock": self.sizing.max_notional_per_symbol,
                        "session_budget_remaining_before": session_budget_remaining,
                        "params": self.params,
                    },
                )

                return order
            self._log_execution_event(
                ticker=self.ticker,
                signal=signal,
                action='NO_TRADE',
                reason='qty_zero',
                details={
                    "current_position": current_position,
                    "last_executed_signal": last_signal,
                    "available_capital": available_capital,
                    "price": current_price,
                    "computed_qty": qty,
                    "max_dollar_per_stock": self.sizing.max_notional_per_symbol,
                    "session_budget_remaining": session_budget_remaining,
                    "params": self.params,
                },
            )
        
        elif signal == 0 and current_position > 0 and last_signal != 0:
            # Sell all
            fill_model = self._fill_model()
            order_data = MarketOrderRequest(
                symbol=self.ticker,
                qty=current_position,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
                client_order_id=self._client_order_id('SELL'),
            )
            order = with_retry(
                lambda: self.trading_client.submit_order(order_data),
                description=f"submit_order(SELL {self.ticker})",
            )
            print(f"SELL order placed: {current_position} shares")

            # Log to database. price is the decision-time close, not the fill:
            # a DAY market order placed after the close fills at the next open.
            # Without it, exits had no price at all and no round trip in the
            # trade log was computable.
            self.db.log_trade(
                strategy=self.strategy.name,
                ticker=self.ticker,
                side='SELL',
                qty=current_position,
                price=current_price,
                order_id=str(order.id),
                status=_order_status(order),
                params=self.params,
                client_order_id=getattr(order, 'client_order_id', None),
                fill_model=fill_model,
            )
            self._log_execution_event(
                ticker=self.ticker,
                signal=signal,
                action='SELL',
                reason='exit_sell_signal',
                details={
                    "current_position": current_position,
                    "last_executed_signal": last_signal,
                    "price": current_price,
                    "qty": current_position,
                    "params": self.params,
                },
            )
            
            return order
        
        else:
            print("No action needed")
            if signal == 1 and current_position != 0:
                reason = 'already_in_position'
            elif signal == 1 and last_signal == 1:
                reason = 'signal_unchanged'
            elif signal == 0 and current_position == 0:
                reason = 'already_flat'
            elif signal == 0 and last_signal == 0:
                reason = 'signal_unchanged'
            else:
                reason = 'conditions_not_met'
            self._log_execution_event(
                ticker=self.ticker,
                signal=signal,
                action='NO_TRADE',
                reason=reason,
                details={
                    "current_position": current_position,
                    "last_executed_signal": last_signal,
                    "available_capital": available_capital,
                    "price": current_price,
                    "params": self.params,
                },
            )
            return None

    def execute_signal_pair(self, signal_a, signal_b, data_a, data_b):
        """Execute both legs of a pair trade. signal_a, signal_b in {1, -1, 0}."""
        ticker_a = self.strategy.ticker_a
        ticker_b = self.strategy.ticker_b
        pair_name = f"{ticker_a}-{ticker_b}"
        pos_a = self.get_current_position(ticker_a)
        pos_b = self.get_current_position(ticker_b)
        price_a = float(data_a['Close'].iloc[-1])
        price_b = float(data_b['Close'].iloc[-1])
        account = with_retry(self.trading_client.get_account, description="get_account")
        # Equity, not buying_power. The backtest sizes a spread leg off equity
        # (equity * capital_fraction * pair_fraction); reading buying_power
        # here made the live pair path run about 2x the backtest's leverage,
        # unmeasured, in the one place the project can least afford it.
        available_capital = float(account.equity)
        capital = self.sizing.pair_notional(available_capital, PAIR_CAPITAL_FRACTION)
        lookback = getattr(self.strategy, 'lookback', 60)
        if len(data_a) >= lookback and len(data_b) >= lookback:
            pa = data_a['Close'].iloc[-lookback:].values.astype(float)
            pb = data_b['Close'].iloc[-lookback:].values.astype(float)
            beta = float(np.polyfit(pb, pa, 1)[0])
        else:
            beta = price_a / price_b if price_b else 1.0
        # Equal dollar: qty_a = capital/price_a, qty_b such that dollar exposure in B matches hedge
        qty_a = int(capital / price_a) if price_a else 0
        qty_b = int((capital / price_b) * beta) if price_b else 0
        if qty_a <= 0 or qty_b <= 0:
            print("Position size too small; skipping pair trade.")
            self._log_execution_event(
                ticker=pair_name,
                signal=f"{self._serialize_signal(signal_a)},{self._serialize_signal(signal_b)}",
                action='NO_TRADE',
                reason='qty_zero',
                details={
                    "ticker_a": ticker_a,
                    "ticker_b": ticker_b,
                    "qty_a": qty_a,
                    "qty_b": qty_b,
                    "price_a": price_a,
                    "price_b": price_b,
                    "beta": beta,
                    "available_capital": available_capital,
                    "params": self.params,
                },
            )
            return None
        # Spread state: long spread = long A short B (pos_a > 0, pos_b < 0); short spread = short A long B
        in_long_spread = pos_a > 0 and pos_b < 0
        in_short_spread = pos_a < 0 and pos_b > 0
        want_long = signal_a == 1 and signal_b == -1
        want_short = signal_a == -1 and signal_b == 1
        want_flat = signal_a == 0 and signal_b == 0

        if want_flat and (in_long_spread or in_short_spread):
            # Close both legs
            if in_long_spread:
                order_a = self.trading_client.submit_order(MarketOrderRequest(symbol=ticker_a, qty=abs(int(pos_a)), side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
                order_b = self.trading_client.submit_order(MarketOrderRequest(symbol=ticker_b, qty=abs(int(pos_b)), side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
            else:
                order_a = self.trading_client.submit_order(MarketOrderRequest(symbol=ticker_a, qty=abs(int(pos_a)), side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
                order_b = self.trading_client.submit_order(MarketOrderRequest(symbol=ticker_b, qty=abs(int(pos_b)), side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
            spread_val = np.log(price_a) - beta * np.log(price_b)
            self.db.log_pair_trade(self.strategy.name, pair_name, ticker_a, ticker_b, 'SELL' if in_long_spread else 'BUY', 'BUY' if in_long_spread else 'SELL', abs(pos_a), abs(pos_b), spread_val, None, str(order_a.id), str(order_b.id))
            self._log_execution_event(
                ticker=pair_name,
                signal=f"{self._serialize_signal(signal_a)},{self._serialize_signal(signal_b)}",
                action='CLOSE_PAIR',
                reason='exit_to_flat',
                details={
                    "ticker_a": ticker_a,
                    "ticker_b": ticker_b,
                    "position_a": pos_a,
                    "position_b": pos_b,
                    "qty_a": abs(int(pos_a)),
                    "qty_b": abs(int(pos_b)),
                    "spread": spread_val,
                    "beta": beta,
                    "params": self.params,
                },
            )
            print(f"Closed pair: {ticker_a} SELL {abs(int(pos_a))}, {ticker_b} BUY {abs(int(pos_b))}" if in_long_spread else f"Closed pair: {ticker_a} BUY {abs(int(pos_a))}, {ticker_b} SELL {abs(int(pos_b))}")
            return None
        if want_long and not in_long_spread:
            if in_short_spread:
                # Close short first
                self.trading_client.submit_order(MarketOrderRequest(symbol=ticker_a, qty=abs(int(pos_a)), side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
                self.trading_client.submit_order(MarketOrderRequest(symbol=ticker_b, qty=abs(int(pos_b)), side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
            order_a = self.trading_client.submit_order(MarketOrderRequest(symbol=ticker_a, qty=qty_a, side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
            order_b = self.trading_client.submit_order(MarketOrderRequest(symbol=ticker_b, qty=qty_b, side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
            spread_val = np.log(price_a) - beta * np.log(price_b)
            self.db.log_pair_trade(self.strategy.name, pair_name, ticker_a, ticker_b, 'BUY', 'SELL', qty_a, qty_b, spread_val, None, str(order_a.id), str(order_b.id))
            self._log_execution_event(
                ticker=pair_name,
                signal=f"{self._serialize_signal(signal_a)},{self._serialize_signal(signal_b)}",
                action='OPEN_PAIR',
                reason='entry_long_spread',
                details={
                    "ticker_a": ticker_a,
                    "ticker_b": ticker_b,
                    "qty_a": qty_a,
                    "qty_b": qty_b,
                    "position_a": pos_a,
                    "position_b": pos_b,
                    "spread": spread_val,
                    "beta": beta,
                    "params": self.params,
                },
            )
            print(f"Long spread: BUY {qty_a} {ticker_a}, SELL {qty_b} {ticker_b}")
            return None
        if want_short and not in_short_spread:
            if in_long_spread:
                self.trading_client.submit_order(MarketOrderRequest(symbol=ticker_a, qty=abs(int(pos_a)), side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
                self.trading_client.submit_order(MarketOrderRequest(symbol=ticker_b, qty=abs(int(pos_b)), side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
            order_a = self.trading_client.submit_order(MarketOrderRequest(symbol=ticker_a, qty=qty_a, side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
            order_b = self.trading_client.submit_order(MarketOrderRequest(symbol=ticker_b, qty=qty_b, side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
            spread_val = np.log(price_a) - beta * np.log(price_b)
            self.db.log_pair_trade(self.strategy.name, pair_name, ticker_a, ticker_b, 'SELL', 'BUY', qty_a, qty_b, spread_val, None, str(order_a.id), str(order_b.id))
            self._log_execution_event(
                ticker=pair_name,
                signal=f"{self._serialize_signal(signal_a)},{self._serialize_signal(signal_b)}",
                action='OPEN_PAIR',
                reason='entry_short_spread',
                details={
                    "ticker_a": ticker_a,
                    "ticker_b": ticker_b,
                    "qty_a": qty_a,
                    "qty_b": qty_b,
                    "position_a": pos_a,
                    "position_b": pos_b,
                    "spread": spread_val,
                    "beta": beta,
                    "params": self.params,
                },
            )
            print(f"Short spread: SELL {qty_a} {ticker_a}, BUY {qty_b} {ticker_b}")
            return None
        print("No pair action needed")
        if want_flat and not (in_long_spread or in_short_spread):
            reason = 'already_flat'
        elif want_long and in_long_spread:
            reason = 'already_in_target_position'
        elif want_short and in_short_spread:
            reason = 'already_in_target_position'
        else:
            reason = 'hold_state'
        self._log_execution_event(
            ticker=pair_name,
            signal=f"{self._serialize_signal(signal_a)},{self._serialize_signal(signal_b)}",
            action='NO_TRADE',
            reason=reason,
            details={
                "ticker_a": ticker_a,
                "ticker_b": ticker_b,
                "position_a": pos_a,
                "position_b": pos_b,
                "want_long": want_long,
                "want_short": want_short,
                "want_flat": want_flat,
                "in_long_spread": in_long_spread,
                "in_short_spread": in_short_spread,
                "price_a": price_a,
                "price_b": price_b,
                "beta": beta,
                "params": self.params,
            },
        )
        return None
    
    def _fill_model(self):
        """
        Which fill model this order will follow: the market's state decides it.

        The backtest fills at Open[T+1] from a Close[T] signal. The 16:30 ET
        scheduler matches that, because a DAY market order submitted after the
        close queues to the next open. A manual run during market hours does
        not: it signals off an incomplete daily bar and fills in the same
        session, which the backtest cannot reproduce under any of its models.

        Recording which case applied is what lets
        analytics.divergence.estimate_execution_timing_impact be applied to the
        right subset of trades instead of to all of them indiscriminately.
        Returns None if the clock cannot be read - unknown, not assumed.
        """
        try:
            return "immediate_intraday" if self.trading_client.get_clock().is_open else "queued_next_open"
        except Exception as e:
            print(f"Could not read market clock; fill_model unknown: {e}")
            return None

    def _client_order_id(self, side):
        """
        Deterministic per (strategy, ticker, date, side) so the broker rejects a
        duplicate submission.

        The existing get_last_executed_signal check is self-enforced and fails
        open: if the DB write succeeded but the process died, or two runs overlap,
        nothing stops a second identical order. Alpaca rejecting a repeated
        client_order_id is enforced on the broker's side, which is the only place
        it can be enforced reliably.
        """
        stamp = datetime.now().strftime("%Y%m%d")
        slug = self.strategy.name.replace(" ", "-")
        return f"{slug}-{self.ticker}-{stamp}-{side}"

    def reconcile_open_orders(self, max_age_days=10):
        """
        Settle previously submitted orders against what Alpaca actually did.

        Called at the START of a run, not after submitting: a DAY market order
        placed at 16:30 does not fill until the next open ~17 hours later, so
        there is nothing to poll at submit time. Each run therefore settles the
        previous run's orders. This is what turns the trade log from a record of
        intentions into a record of fills, and it is the prerequisite for any
        per-trade slippage or P&L number.

        Returns a list of the changes applied.
        """
        open_orders = self.db.get_unreconciled_orders(max_age_days=max_age_days)
        if not open_orders:
            return []

        changes = []
        for row in open_orders:
            try:
                order = with_retry(
                    lambda: self.trading_client.get_order_by_id(row["order_id"]),
                    description=f"get_order_by_id({row['order_id']})",
                )
            except Exception as e:
                print(f"Could not fetch order {row['order_id']} for {row['ticker']}: {e}")
                continue

            status = _order_status(order)
            filled_qty = _to_float(getattr(order, "filled_qty", None))
            filled_avg_price = _to_float(getattr(order, "filled_avg_price", None))
            self.db.update_trade_fill(
                row["id"], status=status, filled_qty=filled_qty, filled_avg_price=filled_avg_price
            )

            slippage = None
            if filled_avg_price is not None and row.get("price"):
                # Signed against the direction of the trade: positive means the
                # fill was worse than the price the decision was made at.
                ref = float(row["price"])
                slippage = filled_avg_price - ref if row["side"] == "BUY" else ref - filled_avg_price

            change = {
                "trade_id": row["id"], "ticker": row["ticker"], "side": row["side"],
                "status": status, "filled_qty": filled_qty,
                "filled_avg_price": filled_avg_price, "reference_price": row.get("price"),
                "slippage": slippage,
            }
            changes.append(change)
            print(
                f"Reconciled {row['ticker']} {row['side']} order {row['order_id']}: "
                f"{status}, filled {filled_qty} @ {filled_avg_price}"
                + (f" (slippage {slippage:+.4f})" if slippage is not None else "")
            )

            # A non-terminal order older than a couple of trading days is not
            # patiently waiting; something is wrong and it should be visible.
            if status.lower() not in self.db.TERMINAL_ORDER_STATUSES:
                age_days = (datetime.now() - datetime.fromisoformat(row["timestamp"])).days
                if age_days >= 2:
                    print(
                        f"WARNING: order {row['order_id']} ({row['ticker']} {row['side']}) "
                        f"still '{status}' after {age_days} days"
                    )

        return changes

    def _read_account_state(self):
        """(portfolio_value, cash, positions, positions_market_value, held_count)."""
        account = with_retry(self.trading_client.get_account, description="get_account")
        raw_positions = with_retry(
            self.trading_client.get_all_positions, description="get_all_positions"
        )
        positions = {}
        market_value = 0.0
        for pos in raw_positions:
            qty = _to_float(getattr(pos, "qty", None))
            if qty is None or qty == 0:
                continue
            positions[pos.symbol] = qty
            market_value += _to_float(getattr(pos, "market_value", None)) or 0.0
        return (
            _to_float(account.portfolio_value),
            _to_float(account.cash),
            positions,
            market_value,
            len(positions),
        )

    def log_portfolio_snapshot(self):
        """
        Record one account-level snapshot (portfolio value, cash, all positions).

        Deliberately NOT called from run(). A snapshot describes the whole
        account, not one ticker, so calling it per-ticker in a batch wrote ten
        near-identical rows per trading day — inflating the table tenfold and
        making "daily" returns actually intra-run returns. Callers own the
        cadence: the scheduler snapshots once after its ticker loop, and the
        single-run API endpoint snapshots once after its one run.

        The reading is reconciled before it is persisted. On 2026-07-07 Alpaca
        returned portfolio_value == cash with an empty position list, sampled at
        16:30 ET before positions were marked, between two days that held six
        positions worth ~$105k. That row was written verbatim and produced a
        61% drawdown in every metric computed off the live curve, against an
        actual return of +1.65%. An equity curve is only worth what its worst
        point is worth, so a point that does not add up is not recorded.
        """
        value, cash, positions, market_value, held = self._read_account_state()

        ok, reason, detail = reconcile_snapshot(value, cash, market_value, held)

        # A mid-mark reading is transient: the positions are there, they just
        # have not been marked yet. One re-read a moment later resolves it, and
        # is much cheaper than losing the day's snapshot.
        if not ok or reason == EMPTY_POSITIONS_VALUE_IS_CASH:
            print(f"Snapshot did not reconcile ({reason}); re-reading account...")
            time.sleep(SNAPSHOT_RETRY_DELAY_SECONDS)
            value, cash, positions, market_value, held = self._read_account_state()
            ok, reason, detail = reconcile_snapshot(value, cash, market_value, held)

        if not ok:
            # Refusing to write is the right failure here. A missing day leaves
            # a gap in a curve that is already sparse and handled; a wrong day
            # silently corrupts every metric derived from it.
            print(f"REFUSING to record snapshot: {reason} {detail}")
            self._log_execution_event(
                ticker="ACCOUNT",
                signal="N/A",
                action="NO_SNAPSHOT",
                reason=reason,
                details=detail,
            )
            return None

        if reason == EMPTY_POSITIONS_VALUE_IS_CASH:
            # Still flat after the re-read, so the account really is flat and
            # value == cash is the correct description of it. Logged because
            # the same shape is what the defect produces, and a reader
            # comparing against the previous row deserves to know which it was.
            self._log_execution_event(
                ticker="ACCOUNT",
                signal="N/A",
                action="SNAPSHOT_FLAT",
                reason=reason,
                details=detail,
            )

        self.db.log_portfolio_snapshot(
            strategy=self.strategy.name,
            portfolio_value=value,
            cash=cash,
            positions=positions,
            data_quality=reason,
        )
        return reason

    def run(self):
        """Run strategy and execute trades. Does not snapshot; see log_portfolio_snapshot."""
        print("="*60)
        if self._is_stat_arb():
            self._run_pair()
        else:
            self._run_single()
        print("="*60)

    def _run_single(self):
        """Single-ticker flow (Momentum / MA Crossover)."""
        print(f"Running {self.strategy.name} on {self.ticker}")
        print(f"Time: {datetime.now()}")
        print("="*60)
        data = self.get_historical_data()
        print(f"Loaded {len(data)} days of historical data")
        if data.empty:
            self._log_execution_event(
                ticker=self.ticker,
                signal='N/A',
                action='NO_TRADE',
                reason='insufficient_data',
                details={"rows": 0, "params": self.params},
            )
            return
        signals = self.strategy.generate_signals(data)
        current_signal = signals.iloc[-1]
        print(f"Latest signal: {current_signal}")
        self.execute_signal(current_signal, data)

    # Note on the pair path below: its submit_order calls are deliberately NOT
    # wrapped in with_retry. Retrying a submission is only safe because every
    # single-name order carries a deterministic client_order_id that Alpaca will
    # reject on a duplicate. The pair legs pass no client_order_id, so a retry
    # after a timeout - where the first request may well have succeeded - could
    # open a second leg and leave the spread unbalanced. Retries here wait on
    # the guarded pair execution the README lists as an open gap.

    def _run_pair(self):
        """Pair flow (Stat Arb): fetch both, generate signals, execute both legs."""
        ticker_a = self.strategy.ticker_a
        ticker_b = self.strategy.ticker_b
        print(f"Running {self.strategy.name} on {ticker_a} / {ticker_b}")
        print(f"Time: {datetime.now()}")
        print("="*60)
        data_a, data_b = self.get_historical_data_pair(ticker_a, ticker_b)
        print(f"Loaded {len(data_a)} days for {ticker_a}, {len(data_b)} for {ticker_b}")
        if data_a.empty or data_b.empty:
            print("Insufficient data for pair; skipping.")
            self._log_execution_event(
                ticker=f"{ticker_a}-{ticker_b}",
                signal='N/A',
                action='NO_TRADE',
                reason='insufficient_data',
                details={
                    "rows_a": len(data_a),
                    "rows_b": len(data_b),
                    "params": self.params,
                },
            )
            return
        signal_a, signal_b = self.strategy.generate_signals(data_a, data_b)
        sa = signal_a.iloc[-1]
        sb = signal_b.iloc[-1]
        print(f"Latest signals: {ticker_a}={sa}, {ticker_b}={sb}")
        self.execute_signal_pair(sa, sb, data_a, data_b)


if __name__ == "__main__":
    strategy = MomentumStrategy()
    executor = StrategyExecutor(strategy, ticker='AAPL')
    executor.run()
    executor.log_portfolio_snapshot()