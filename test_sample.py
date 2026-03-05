"""
Test backtest with sample data
"""
import pandas as pd
import numpy as np
from datetime import datetime
from backtesting import BacktestEngine
from strategies import BreakoutScalpingStrategy

dates = pd.date_range(start='2025-09-01', periods=500, freq='1h')
base_price = 42000
prices = []
for i in range(500):
    change = np.random.randn() * base_price * 0.01
    base_price += change
    prices.append(base_price)

df = pd.DataFrame({
    'timestamp': dates,
    'open': [p * 0.999 for p in prices],
    'high': [p * 1.005 for p in prices],
    'low': [p * 0.995 for p in prices],
    'close': prices,
    'volume': [np.random.randint(100, 1000) for _ in range(500)]
})

strategy = BreakoutScalpingStrategy(leverage=5)
engine = BacktestEngine(initial_capital=10000, strategies=[strategy])

result = engine.run_backtest(df, 'BTCUSDT', strategy)
print(f'Total Trades: {result["metrics"]["total_trades"]}')
print(f'Total PnL: ${result["metrics"]["total_pnl"]:.2f}')
