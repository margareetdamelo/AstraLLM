"""
Test Backtest Engine - Quick verification script
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from backtesting import BacktestEngine
from strategies import BreakoutScalpingStrategy

# Create sample market data
dates = pd.date_range(start='2024-01-01', periods=200, freq='5min')
base_price = 42000
prices = []
for i in range(200):
    change = np.random.randn() * base_price * 0.005
    base_price += change
    prices.append(base_price)

df = pd.DataFrame({
    'timestamp': dates,
    'open': [p * 0.999 for p in prices],
    'high': [p * 1.002 for p in prices],
    'low': [p * 0.998 for p in prices],
    'close': prices,
    'volume': [np.random.randint(100, 1000) for _ in range(200)]
})

# Initialize strategy and engine
strategy = BreakoutScalpingStrategy(leverage=20)
engine = BacktestEngine(initial_capital=10000, strategies=[strategy])

# Run backtest
print('Running backtest on sample data...')
result = engine.run_backtest(df, 'BTCUSDT', strategy)

# Print results
print(f'Total Trades: {result["metrics"]["total_trades"]}')
print(f'Win Rate: {result["metrics"]["win_rate"]:.2f}%')
print(f'Total PnL: ${result["metrics"]["total_pnl"]:.2f}')
print(f'ROI: {result["metrics"]["roi"]:.2f}%')
print('✓ Backtest execution successful!')
