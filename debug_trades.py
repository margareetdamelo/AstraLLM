"""
Debug backtest to see why no trades executed
"""
import pandas as pd
import numpy as np
from datetime import datetime
import sys

import os
os.environ["ASTER_API_KEY"] = "1d91c117756ccb58b8ad174288b1b3f66660e767a07c448518775c0a1b801938"
os.environ["ASTER_API_SECRET"] = "c9e0e976b7f98ca61b17a4963a6c05bddcccff63973b2e7af5f9a4012b8e7bfb"
os.environ["ASTER_SIGNER_ADDRESS"] = "0x16E0a5282B8530d9d3f8B7C1C2A7F8B5E3d2A1C"
os.environ["ASTER_USER_WALLET_ADDRESS"] = "0x16E0a5282B8530d9d3f8B7C1C2A7F8B5E3d2A1C"
os.environ["ASTER_PRIVATE_KEY"] = "0x"
os.environ["API_SECRET_KEY"] = "test_secret_key"

import requests

ASTER_FUTURES_API = "https://fapi.asterdex.com"

def fetch_data(symbol, start_ms, end_ms):
    all_klines = []
    current = start_ms
    while current < end_ms:
        resp = requests.get(f"{ASTER_FUTURES_API}/fapi/v1/klines", 
            params={"symbol": symbol, "interval": "1h", "startTime": current, "endTime": end_ms, "limit": 100}, timeout=30)
        data = resp.json()
        if not data or isinstance(data, dict):
            break
        all_klines.extend(data)
        current = data[-1][0] + 1
        if len(data) < 100:
            break
    return all_klines

from datetime import datetime, timedelta

# Get real BTC data
end_ms = int(datetime.now().timestamp() * 1000)
start_ms = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)

print(f"Fetching BTC data...")
klines = fetch_data("BTCUSDT", start_ms, end_ms)
print(f"Got {len(klines)} candles")

df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume','close_time','quote_volume','trades','taker_buy_base','taker_buy_quote','ignore'])
df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
for col in ['open','high','low','close','volume']:
    df[col] = df[col].astype(float)
df = df[['timestamp','open','high','low','close','volume']]

print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
print(f"Price range: {df['close'].min()} to {df['close'].max()}")
print(f"Volume stats: min={df['volume'].min()}, max={df['volume'].max()}, mean={df['volume'].mean():.2f}")

# Test with real strategy
from backtesting import BacktestEngine
from strategies import BreakoutScalpingStrategy

strategy = BreakoutScalpingStrategy(leverage=5)
engine = BacktestEngine(initial_capital=10000, strategies=[strategy])

# Run backtest
result = engine.run_backtest(df, 'BTCUSDT', strategy)

print(f"\n=== RESULT ===")
print(f"Signals generated: {result.get('signals_generated', 0)}")
print(f"Trades executed: {result.get('trades_executed', 0)}")
print(f"Total trades: {result['metrics']['total_trades']}")
print(f"Final balance: ${result['final_capital']:.2f}")
