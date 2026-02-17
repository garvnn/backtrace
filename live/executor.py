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
import pandas as pd

from strategies.momentum import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy

from database import Database

load_dotenv()

class StrategyExecutor:
    def __init__(self, strategy, ticker='AAPL'):
        self.strategy = strategy
        self.ticker = ticker
        
        # Alpaca clients
        self.trading_client = TradingClient(
            os.getenv('ALPACA_API_KEY'),
            os.getenv('ALPACA_SECRET_KEY'),
            paper=True
        )
        
        self.data_client = StockHistoricalDataClient(
            os.getenv('ALPACA_API_KEY'),
            os.getenv('ALPACA_SECRET_KEY')
        )
        self.db = Database()
    
    def get_historical_data(self, days=300):
        """Get historical price data from Alpaca."""
        request = StockBarsRequest(
            symbol_or_symbols=self.ticker,
            timeframe=TimeFrame.Day,
            start=datetime.now() - timedelta(days=days)
        )
        
        bars = self.data_client.get_stock_bars(request)
        df = bars.df
        
        # Flatten multi-index if needed
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        # Rename columns to match BackTrace format
        # Reset index to make timestamp a column
        df = df.reset_index()
        
        # Rename columns to match BackTrace format
        df = df.rename(columns={
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume',
            'timestamp': 'Date'
        })
        
        # Set Date as index
        if 'Date' in df.columns:
            df = df.set_index('Date')
        
        return df
    
    
    
    def get_current_position(self):
        """Check if we currently hold the ticker."""
        try:
            positions = self.trading_client.get_all_positions()
            for pos in positions:
                if pos.symbol == self.ticker:
                    return float(pos.qty)
            return 0
        except:
            return 0
    
    def execute_signal(self, signal, data):
        """Place order based on signal."""
        current_position = self.get_current_position()
        account = self.trading_client.get_account()
        buying_power = float(account.buying_power)
        
        print(f"\nCurrent position: {current_position} shares")
        print(f"Signal: {signal}")
        
        # Signal = 1 (buy), 0 (sell/flat)
        if signal == 1 and current_position == 0:
            # Buy with all available cash
            current_price = float(data['Close'].iloc[-1])
            qty = int(buying_power * 0.95 / current_price)
            
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
                    status=str(order.status)
                )
                
                return order
        
        elif signal == 0 and current_position > 0:
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
                status=str(order.status)
            )
            
            return order
        
        else:
            print("No action needed")
            return None
    
    def run(self):
        """Run strategy and execute trades."""
        print("="*60)
        print(f"Running {self.strategy.name} on {self.ticker}")
        print(f"Time: {datetime.now()}")
        print("="*60)
        
        # Get data
        data = self.get_historical_data()
        print(f"Loaded {len(data)} days of historical data")
        
        # Generate signal
        signals = self.strategy.generate_signals(data)
        current_signal = signals.iloc[-1]
        
        print(f"Latest signal: {current_signal}")
        
        # Execute trade
        self.execute_signal(current_signal, data)
        
        print("="*60)

        print("="*60)
        
        # Log portfolio snapshot
        account = self.trading_client.get_account()
        positions = {pos.symbol: float(pos.qty) for pos in self.trading_client.get_all_positions()}
        
        self.db.log_portfolio_snapshot(
            strategy=self.strategy.name,
            portfolio_value=float(account.portfolio_value),
            cash=float(account.cash),
            positions=positions
        )


if __name__ == "__main__":
    strategy = MomentumStrategy()
    executor = StrategyExecutor(strategy, ticker='AAPL')
    executor.run()