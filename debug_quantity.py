"""
Debug quantity calculation
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

os.environ["ASTER_API_KEY"] = "1d91c117756ccb58b8ad174288b1b3f66660e767a07c448518775c0a1b801938"
os.environ["ASTER_API_SECRET"] = "c9e0e976b7f98ca61b17a4963a6c05bddcccff63973b2e7af5f9a4012b8e7bfb"
os.environ["ASTER_SIGNER_ADDRESS"] = "0x16E0a5282B8530d9d3f8B7C1C2A7F8B5E3d2A1C"
os.environ["ASTER_USER_WALLET_ADDRESS"] = "0x16E0a5282B8530d9d3f8B7C1C2A7F8B5E3d2A1C"
os.environ["ASTER_PRIVATE_KEY"] = "0x"
os.environ["API_SECRET_KEY"] = "test_secret_key"

import requests
from backtesting import BacktestEngine, OrderSimulator
from backtesting.order_simulator import BacktestConfig, PositionSide
from strategies import BreakoutScalpingStrategy

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

# Get 1 month of BTC data
end_ms = int(datetime.now().timestamp() * 1000)
start_ms = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)

print(f"Fetching BTC data...")
klines = fetch_data("BTCUSDT", start_ms, end_ms)

df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume','close_time','quote_volume','trades','taker_buy_base','taker_buy_quote','ignore'])
df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
for col in ['open','high','low','close','volume']:
    df[col] = df[col].astype(float)
df = df[['timestamp','open','high','low','close','volume']]

print(f"Loaded {len(df)} candles")

# Test quantity calculation
config = BacktestConfig(initial_capital=10000)
sim = OrderSimulator(config)

# Get a sample price
entry_price = df['close'].iloc[-1]
stop_loss = entry_price * 0.97
leverage = 5
volatility = 0.012  # 1.2%

print(f"\n=== Testing Quantity Calculation ===")
print(f"Entry price: ${entry_price:.2f}")
print(f"Stop loss: ${stop_loss:.2f}")
print(f"Leverage: {leverage}x")
print(f"Balance: ${sim.balance:.2f}")

# Manual calculation
risk_per_trade = 0.02
risk_amount = sim.balance * risk_per_trade
volatility_multiplier = max(0.5, 1 - (volatility * 2))
risk_amount_adjusted = risk_amount * volatility_multiplier

stop_distance = abs(entry_price - stop_loss) / entry_price
print(f"Stop distance: {stop_distance:.4f} ({stop_distance*100:.2f}%)")

position_value = risk_amount_adjusted / stop_distance
quantity = position_value / entry_price
print(f"Raw quantity (before leverage adj): {quantity}")

leverage_adjustment = min(1.0, 20 / leverage)
quantity *= leverage_adjustment
print(f"After leverage adjustment: {quantity}")

max_quantity = sim.get_max_quantity("BTCUSDT", entry_price, leverage)
print(f"Max quantity possible: {max_quantity}")

final_quantity = min(quantity, max_quantity)
print(f"Final quantity: {final_quantity}")

# Try opening a position
print(f"\n=== Testing Position Opening ===")
result = sim.open_position(
    symbol="BTCUSDT",
    side=PositionSide.LONG,
    entry_price=entry_price,
    quantity=final_quantity,
    leverage=leverage,
    stop_loss=stop_loss,
    take_profit=entry_price * 1.04
)

if result:
    print(f"✅ Position opened successfully!")
    print(f"   Quantity: {result.quantity}")
    print(f"   Margin used: ${(entry_price * result.quantity) / leverage:.2f}")
    print(f"   Remaining balance: ${sim.balance:.2f}")
else:
    print(f"❌ Failed to open position")

# Check what happens with can_open_position
print(f"\n=== Checking can_open_position ===")
can_open, reason = sim.can_open_position("BTCUSDT", entry_price, final_quantity, leverage, PositionSide.LONG)
print(f"can_open: {can_open}")
print(f"Reason: {reason}")
