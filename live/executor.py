"""
Strategy executor - runs BackTrace strategies live.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

from strategies.momentum import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.stat_arb import StatArbStrategy

from database import Database

# Load .env from live/ so it works when run as "python live/executor.py" from project root
LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
_env_path = os.path.join(LIVE_DIR, ".env")
load_dotenv(_env_path)
DB_PATH = os.getenv("DB_PATH") or os.path.join(LIVE_DIR, "trading.db")

# Cap per-stock position size for single-ticker strategies (10 stocks = max 100k)
MAX_DOLLAR_PER_STOCK = 10_000

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
    def __init__(self, strategy, ticker='AAPL', params=None):
        self.strategy = strategy
        self.ticker = ticker
        self.params = params  # optional dict e.g. short_window, long_window, lookback_period for logging
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
            start=datetime.now() - timedelta(days=days)
        )
        bars = self.data_client.get_stock_bars(request)
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
        """Check position for a symbol (default self.ticker). Returns signed qty."""
        sym = symbol if symbol is not None else self.ticker
        try:
            positions = self.trading_client.get_all_positions()
            for pos in positions:
                if pos.symbol == sym:
                    return float(pos.qty)
            return 0
        except Exception:
            return 0
    
    def execute_signal(self, signal, data):
        """Place order based on signal. Only acts on signal change (idempotent); caps BUY at MAX_DOLLAR_PER_STOCK."""
        current_position = self.get_current_position()
        account = self.trading_client.get_account()
        buying_power = float(account.buying_power)
        last_signal = self.db.get_last_executed_signal(self.strategy.name, self.ticker)
        
        print(f"\nCurrent position: {current_position} shares")
        print(f"Signal: {signal}")
        
        # Signal = 1 (buy), 0 (sell/flat). Only place order when signal changed from last executed.
        if signal == 1 and current_position == 0 and last_signal != 1:
            # Buy: cap at MAX_DOLLAR_PER_STOCK per stock
            current_price = float(data['Close'].iloc[-1])
            dollar_amount = min(MAX_DOLLAR_PER_STOCK, buying_power * 0.95)
            qty = int(dollar_amount / current_price)
            
            if qty > 0:
                order_data = MarketOrderRequest(
                    symbol=self.ticker,
                    qty=qty,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY
                )
                order = self.trading_client.submit_order(order_data)
                print(f"BUY order placed: {qty} shares")
                
                # Log to database
                self.db.log_trade(
                    strategy=self.strategy.name,
                    ticker=self.ticker,
                    side='BUY',
                    qty=qty,
                    price=current_price,
                    order_id=str(order.id),
                    status=str(order.status),
                    params=self.params,
                )
                
                return order
        
        elif signal == 0 and current_position > 0 and last_signal != 0:
            # Sell all
            order_data = MarketOrderRequest(
                symbol=self.ticker,
                qty=current_position,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
            order = self.trading_client.submit_order(order_data)
            print(f"SELL order placed: {current_position} shares")
            
            # Log to database
            self.db.log_trade(
                strategy=self.strategy.name,
                ticker=self.ticker,
                side='SELL',
                qty=current_position,
                order_id=str(order.id),
                status=str(order.status),
                params=self.params,
            )
            
            return order
        
        else:
            print("No action needed")
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
        account = self.trading_client.get_account()
        buying_power = float(account.buying_power)
        # Use half of allocated capital for the pair (equal dollar legs)
        capital = buying_power * 0.45
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
            print(f"Short spread: SELL {qty_a} {ticker_a}, BUY {qty_b} {ticker_b}")
            return None
        print("No pair action needed")
        return None
    
    def run(self):
        """Run strategy and execute trades."""
        print("="*60)
        if self._is_stat_arb():
            self._run_pair()
        else:
            self._run_single()
        print("="*60)
        account = self.trading_client.get_account()
        positions = {pos.symbol: float(pos.qty) for pos in self.trading_client.get_all_positions()}
        self.db.log_portfolio_snapshot(
            strategy=self.strategy.name,
            portfolio_value=float(account.portfolio_value),
            cash=float(account.cash),
            positions=positions
        )

    def _run_single(self):
        """Single-ticker flow (Momentum / MA Crossover)."""
        print(f"Running {self.strategy.name} on {self.ticker}")
        print(f"Time: {datetime.now()}")
        print("="*60)
        data = self.get_historical_data()
        print(f"Loaded {len(data)} days of historical data")
        signals = self.strategy.generate_signals(data)
        current_signal = signals.iloc[-1]
        print(f"Latest signal: {current_signal}")
        self.execute_signal(current_signal, data)

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