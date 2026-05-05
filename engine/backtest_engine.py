"""
Core backtesting engine.
Executes trades and tracks portfolio value over time.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np


class BacktestEngine:
    def __init__(self, initial_capital=100000, commission=0.001):
        """
        Args:
            initial_capital: Starting cash
            commission: Transaction cost (0.001 = 0.1%)
        """
        self.initial_capital = initial_capital
        self.commission = commission
    
    def run_buyhold(self, data):
        """
        Calculate buy-and-hold returns.
        
        Args:
            data: DataFrame with 'Close' prices
            
        Returns:
            Dict with portfolio values and metrics
        """
        # Calculate daily returns
        returns = data['Close'].pct_change()
        
        # Calculate cumulative portfolio value
        portfolio_values = self.initial_capital * (1 + returns).cumprod()
        portfolio_values.iloc[0] = self.initial_capital
        
        total_return = (float(portfolio_values.iloc[-1]) / self.initial_capital) - 1
        
        return {
            'portfolio_values': portfolio_values,
            'total_return': total_return,
            'trades': 1,  # Just the initial buy
            'trade_returns': [],
        }
    
    def run(self, data, strategy):
        """
        Run backtest with a strategy.
        
        Args:
            data: DataFrame with price data
            strategy: Strategy object
            
        Returns:
            Dict with results
        """
        signals = strategy.generate_signals(data)
        
        # Start with cash
        cash = self.initial_capital
        shares = 0
        portfolio_values = []
        trades = 0
        entry_invested = None  # cash allocated at buy (for round-trip return)
        trade_returns = []
        
        for i in range(len(data)):
            price = float(data['Close'].iloc[i])
            signal = signals.iloc[i]
            
            # Execute trades based on signal
            if signal == 1 and shares == 0:  # Buy signal
                entry_invested = cash
                net = cash * (1 - self.commission)
                shares = net / price
                cash = 0
                trades += 1
            elif signal == 0 and shares > 0:  # Sell signal
                gross = shares * price
                cash = gross * (1 - self.commission)
                shares = 0
                trades += 1
                if entry_invested is not None and entry_invested > 0:
                    trade_returns.append((cash - entry_invested) / entry_invested)
                entry_invested = None
            
            # Calculate portfolio value
            portfolio_value = cash + (shares * price)
            portfolio_values.append(portfolio_value)
        
        portfolio_values = pd.Series(portfolio_values, index=data.index)
        total_return = (portfolio_values.iloc[-1] / self.initial_capital) - 1
        
        return {
            'portfolio_values': portfolio_values,
            'total_return': total_return,
            'trades': trades,
            'trade_returns': trade_returns,
        }

    def run_pair(self, data_a, data_b, strategy):
        """
        Run backtest for a pairs (Stat Arb) strategy.

        Args:
            data_a: DataFrame with 'Close' for ticker A
            data_b: DataFrame with 'Close' for ticker B
            strategy: StatArbStrategy (must have generate_signals_pair)

        Returns:
            Dict with portfolio_values, total_return, trades (same shape as run()).
        """
        from strategies.stat_arb import StatArbStrategy
        if not isinstance(strategy, StatArbStrategy):
            raise TypeError("run_pair requires StatArbStrategy")
        common = data_a.index.intersection(data_b.index)
        data_a = data_a.loc[common].sort_index()
        data_b = data_b.loc[common].sort_index()
        if len(data_a) < strategy.lookback or len(data_b) < strategy.lookback:
            pv = pd.Series([self.initial_capital] * len(data_a), index=data_a.index)
            return {'portfolio_values': pv, 'total_return': 0.0, 'trades': 0, 'trade_returns': []}
        signal_a, signal_b = strategy.generate_signals_pair(data_a, data_b)
        cash = self.initial_capital
        shares_a = 0.0
        shares_b = 0.0
        state = 'flat'  # 'flat', 'long_spread', 'short_spread'
        portfolio_values = []
        trades = 0
        capital = self.initial_capital
        entry_pv = None  # portfolio value after opening a spread (for round-trip return)
        trade_returns = []
        for i in range(len(data_a)):
            state_before = state
            pa = float(data_a['Close'].iloc[i])
            pb = float(data_b['Close'].iloc[i])
            sa = signal_a.iloc[i]
            sb = signal_b.iloc[i]
            if state == 'flat':
                if sa == 1 and sb == -1:
                    # Enter long spread: buy A, short B (equal dollar)
                    notional = capital * 0.5
                    shares_a = notional / pa
                    shares_b = -notional / pb
                    cash = capital - notional + notional  # spent on A, received from short B
                    cost = (notional * 2) * self.commission
                    cash -= cost
                    state = 'long_spread'
                    trades += 1
                elif sa == -1 and sb == 1:
                    # Enter short spread: short A, buy B
                    notional = capital * 0.5
                    shares_a = -notional / pa
                    shares_b = notional / pb
                    cash = capital - notional + notional
                    cost = (notional * 2) * self.commission
                    cash -= cost
                    state = 'short_spread'
                    trades += 1
            elif state == 'long_spread':
                if sa == 0 and sb == 0:
                    # Exit: sell A, cover B
                    cash = cash + shares_a * pa + shares_b * pb
                    cost = (abs(shares_a * pa) + abs(shares_b * pb)) * self.commission
                    cash -= cost
                    shares_a, shares_b = 0.0, 0.0
                    state = 'flat'
                    trades += 1
                elif sa == -1 and sb == 1:
                    # Reverse to short: exit long then enter short
                    cash = cash + shares_a * pa + shares_b * pb
                    cost = (abs(shares_a * pa) + abs(shares_b * pb)) * self.commission
                    cash -= cost
                    shares_a, shares_b = 0.0, 0.0
                    pv_flat = cash
                    if entry_pv is not None and entry_pv > 0:
                        trade_returns.append((pv_flat - entry_pv) / entry_pv)
                    entry_pv = None
                    notional = capital * 0.5
                    shares_a = -notional / pa
                    shares_b = notional / pb
                    cash = cash - notional + notional
                    cost = (notional * 2) * self.commission
                    cash -= cost
                    state = 'short_spread'
                    trades += 2
            elif state == 'short_spread':
                if sa == 0 and sb == 0:
                    cash = cash + shares_a * pa + shares_b * pb
                    cost = (abs(shares_a * pa) + abs(shares_b * pb)) * self.commission
                    cash -= cost
                    shares_a, shares_b = 0.0, 0.0
                    state = 'flat'
                    trades += 1
                elif sa == 1 and sb == -1:
                    cash = cash + shares_a * pa + shares_b * pb
                    cost = (abs(shares_a * pa) + abs(shares_b * pb)) * self.commission
                    cash -= cost
                    shares_a, shares_b = 0.0, 0.0
                    pv_flat = cash
                    if entry_pv is not None and entry_pv > 0:
                        trade_returns.append((pv_flat - entry_pv) / entry_pv)
                    entry_pv = None
                    notional = capital * 0.5
                    shares_a = notional / pa
                    shares_b = -notional / pb
                    cash = cash - notional + notional
                    cost = (notional * 2) * self.commission
                    cash -= cost
                    state = 'long_spread'
                    trades += 2
            portfolio_value = cash + shares_a * pa + shares_b * pb
            portfolio_values.append(portfolio_value)
            if state_before != 'flat' and state == 'flat':
                if entry_pv is not None and entry_pv > 0:
                    trade_returns.append((portfolio_value - entry_pv) / entry_pv)
                entry_pv = None
            elif state_before == 'flat' and state != 'flat':
                entry_pv = portfolio_value
            elif state_before != 'flat' and state != 'flat' and state_before != state:
                # reversal: new entry_pv is mark-to-market at end of bar
                entry_pv = portfolio_value
        portfolio_values = pd.Series(portfolio_values, index=data_a.index)
        total_return = (float(portfolio_values.iloc[-1]) / self.initial_capital) - 1
        return {
            'portfolio_values': portfolio_values,
            'total_return': total_return,
            'trades': trades,
            'trade_returns': trade_returns,
        }

if __name__ == "__main__":
    # Test the engine
    from data.loader import load_data
    
    print("Testing backtest engine...")
    data = load_data('AAPL', '2020-01-01', '2024-12-31')
    
    engine = BacktestEngine(initial_capital=100000)
    results = engine.run_buyhold(data)
    
    print(f"\nInitial Capital: ${engine.initial_capital:,.2f}")
    print(f"Final Value: ${float(results['portfolio_values'].iloc[-1]):,.2f}")
    print(f"Total Return: {results['total_return']:.2%}")

# Test with strategy
    from strategies.mean_reversion import MeanReversionStrategy
    
    strategy = MeanReversionStrategy()
    results_strategy = engine.run(data, strategy)
    
    print(f"\n--- Strategy Results ---")
    print(f"Total Return: {results_strategy['total_return']:.2%}")
    print(f"Number of Trades: {results_strategy['trades']}")