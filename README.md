# BackTrace

A Python-based quantitative backtesting engine that demonstrates why most retail trading strategies underperform passive investing.

## Overview

This project implements and tests two common trading strategies (momentum and moving average crossover) against buy-and-hold on historical equity data. The results show that both active strategies significantly underperform after accounting for realistic transaction costs.

## Key Findings

Testing on AAPL (2020-2024):

| Strategy | Total Return | Sharpe Ratio | Max Drawdown | Trades |
|----------|-------------|--------------|--------------|--------|
| **Buy & Hold** | +246% | ~0.48 | -32% | 1 |
| **MA Crossover** | +47% | ~1.2 | -24% | 7 |
| **Momentum** | +30% | 0.34 | -45% | 49 |

**Insight**: Transaction costs (0.1% per trade) and poor timing caused both strategies to massively underperform passive investing.

## Installation
```bash
git clone https://github.com/garvnn/backtrace.git
cd backtrace
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage
```bash
# Run comparison of all strategies
python visualization/plots.py

# Test individual strategies
python strategies/momentum.py
python strategies/mean_reversion.py

# View metrics
python analytics/metrics.py
```

## Project Structure
```
backtrace/
├── data/              # Data loading and caching
├── strategies/        # Trading strategy implementations
├── engine/           # Backtesting execution engine
├── analytics/        # Performance metrics (Sharpe, drawdown)
├── visualization/    # Chart generation
└── results/          # Output charts
```

## Strategies Implemented

### 1. Moving Average Crossover (Mean Reversion)
- **Logic**: Buy when 50-day MA crosses above 200-day MA
- **Result**: Underperformed due to slow signals and transaction costs
- **Trades**: 7 over 5 years

### 2. Momentum
- **Logic**: Buy if 6-month return is positive
- **Result**: Worst performer—high trading frequency destroyed returns
- **Trades**: 49 over 5 years

## Technical Details

- **Data Source**: Yahoo Finance (yfinance)
- **Transaction Costs**: 0.1% per trade (realistic retail brokerage)
- **Slippage**: Not modeled (assumes execution at close price)
- **Backtesting Approach**: Vectorized calculations on daily OHLCV data

## Metrics Calculated

- **Total Return**: (Final Value - Initial Capital) / Initial Capital
- **Sharpe Ratio**: Risk-adjusted returns (annualized)
- **Max Drawdown**: Largest peak-to-trough decline
- **Number of Trades**: Total buy/sell executions

## Why Strategies Failed

1. **Transaction costs accumulate**: 49 trades × 0.1% = ~5% lost to fees
2. **Poor timing**: Signals lag, causing late entries and early exits
3. **Bull market environment**: Time spent in cash missed massive gains
4. **Market efficiency**: Simple technical strategies can't beat passive investing

## Future Enhancements

- Transaction cost modeling (market impact, slippage)
- Strategy capacity analysis
- Signal decay estimation
- Walk-forward optimization
- Multi-asset portfolio construction

## Lessons Learned

This project demonstrates a fundamental truth in quantitative finance: **most retail trading strategies lose to buy-and-hold after accounting for transaction costs and realistic execution**. The value isn't in finding "profitable" strategies, but in understanding why they typically fail.

## Author

Built by Garv Narang as part of exploring quantitative finance and market microstructure.

## License

MIT