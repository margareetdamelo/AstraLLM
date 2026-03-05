"""
Analyze strategy changes during backtest
"""
import os
import sys
import requests
import json
from collections import defaultdict

os.environ["ASTER_API_KEY"] = "1d91c117756ccb58b8ad174288b1b3f66660e767a07c448518775c0a1b801938"
os.environ["ASTER_API_SECRET"] = "c9e0e976b7f98ca61b17a4963a6c05bddcccff63973b2e7af5f9a4012b8e7bfb"
os.environ["ASTER_SIGNER_ADDRESS"] = "0x16E0a5282B8530d9d3f8B7C1C2A7F8B5E3d2A1C"
os.environ["ASTER_USER_WALLET_ADDRESS"] = "0x16E0a5282B8530d9d3f8B7C1C2A7F8B5E3d2A1C"
os.environ["ASTER_PRIVATE_KEY"] = "0x"
os.environ["API_SECRET_KEY"] = "test_secret_key"

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from loguru import logger

from backtesting import BacktestEngine
from strategies import BacktestStrategy

logger.remove()
logger.add(sys.stderr, level="ERROR")

ASTER_FUTURES_API = "https://fapi.asterdex.com"

def fetch_historical_data(symbol, start_time_ms, end_time_ms, max_candles=5000):
    all_klines = []
    current_start = start_time_ms

    while current_start < end_time_ms:
        try:
            url = f"{ASTER_FUTURES_API}/fapi/v1/klines"
            params = {"symbol": symbol, "interval": "1h", "startTime": current_start, "endTime": end_time_ms, "limit": 100}
            response = requests.get(url, params=params, timeout=30)
            if response.status_code != 200:
                break
            data = response.json()
            if isinstance(data, dict) or not data:
                break
            all_klines.extend(data)
            last_time = data[-1][0]
            current_start = last_time + 1
            if len(data) < 100 or len(all_klines) >= max_candles:
                break
        except:
            break
    return all_klines

def analyze_strategy_changes():
    """分析策略在回测期间的变化"""
    
    end_time = datetime.now()
    start_time = end_time - timedelta(days=60)  # 使用60天数据进行快速分析
    
    start_time_ms = int(start_time.timestamp() * 1000)
    end_time_ms = int(end_time.timestamp() * 1000)
    
    # 获取BTC数据
    klines = fetch_historical_data("BTCUSDT", start_time_ms, end_time_ms)
    if not klines:
        print("No data fetched")
        return
    
    df = pd.DataFrame(klines, columns=[
        'timestamp','open','high','low','close','volume',
        'close_time','quote_volume','trades','taker_buy_base','taker_buy_quote','ignore'
    ])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    for col in ['open','high','low','close','volume']:
        df[col] = df[col].astype(float)
    df = df[['timestamp','open','high','low','close','volume']]
    
    print(f"\n{'='*70}")
    print("策略分析: 60天BTCUSDT数据")
    print(f"数据范围: {df['timestamp'].min()} 到 {df['timestamp'].max()}")
    print(f"K线数量: {len(df)}")
    print(f"{'='*70}\n")
    
    # 分析每个时间点的市场状态
    strategy = BacktestStrategy(leverage=5)
    
    market_states = []
    signals_generated = []
    
    for i in range(50, len(df)):
        current_df = df.iloc[:i+1].copy()
        current_bar = current_df.iloc[-1]
        current_time = current_bar['timestamp']
        
        # 计算各项指标
        close = current_df['close']
        volume = current_df['volume']
        
        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50
        
        # SMA
        sma_20 = close.rolling(20).mean().iloc[-1]
        
        # 成交量
        avg_volume = volume.rolling(20).mean().iloc[-1]
        volume_ratio = current_bar['volume'] / avg_volume if avg_volume > 0 else 0
        
        # ATR
        high = current_df['high']
        low = current_df['low']
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=14).mean()
        atr_pct = (atr.iloc[-1] / current_bar['close']) * 100 if not pd.isna(atr.iloc[-1]) else 0
        
        # 趋势
        trend = "UP" if current_bar['close'] > sma_20 else "DOWN"
        
        # 记录市场状态
        market_states.append({
            'time': current_time,
            'price': current_bar['close'],
            'rsi': current_rsi,
            'sma20': sma_20,
            'volume_ratio': volume_ratio,
            'atr_pct': atr_pct,
            'trend': trend
        })
        
        # 尝试生成信号
        if i % 50 == 0:  # 每50个点检查一次信号
            signal = strategy.analyze(current_df, "BTCUSDT")
            if signal:
                signals_generated.append({
                    'time': current_time,
                    'price': current_bar['close'],
                    'action': signal['action'],
                    'confidence': signal['confidence'],
                    'rsi': current_rsi,
                    'volume_ratio': volume_ratio,
                    'reason': signal.get('reason', '')
                })
    
    # 输出分析结果
    print("\n## 市场状态统计")
    print("-" * 50)
    
    rsi_values = [s['rsi'] for s in market_states]
    volume_ratios = [s['volume_ratio'] for s in market_states]
    atr_values = [s['atr_pct'] for s in market_states]
    trends = [s['trend'] for s in market_states]
    
    print(f"RSI范围: {min(rsi_values):.1f} - {max(rsi_values):.1f}")
    print(f"RSI均值: {np.mean(rsi_values):.1f}")
    print(f"")
    print(f"成交量倍数范围: {min(volume_ratios):.2f}x - {max(volume_ratios):.2f}x")
    print(f"成交量倍数均值: {np.mean(volume_ratios):.2f}x")
    print(f"成交量倍数>1.5x的比例: {sum(1 for v in volume_ratios if v >= 1.5) / len(volume_ratios) * 100:.1f}%")
    print(f"")
    print(f"ATR范围: {min(atr_values):.2f}% - {max(atr_values):.2f}%")
    print(f"ATR均值: {np.mean(atr_values):.2f}%")
    print(f"")
    print(f"趋势分布: UP={trends.count('UP')}, DOWN={trends.count('DOWN')}")
    
    print(f"\n## 信号生成统计")
    print("-" * 50)
    print(f"检测次数: {len(market_states)}")
    print(f"信号生成次数: {len(signals_generated)}")
    print(f"信号生成比例: {len(signals_generated)/len(market_states)*100:.2f}%")
    
    if signals_generated:
        print(f"\n## 生成的信号详情")
        print("-" * 50)
        for sig in signals_generated:
            print(f"时间: {sig['time']}")
            print(f"  价格: ${sig['price']:.2f}")
            print(f"  信号: {sig['action']}")
            print(f"  置信度: {sig['confidence']*100:.0f}%")
            print(f"  RSI: {sig['rsi']:.1f}")
            print(f"  成交量: {sig['volume_ratio']:.2f}x")
            print(f"  原因: {sig['reason'][:60]}...")
            print()
    
    # 策略条件分析
    print(f"\n## 策略条件满足情况")
    print("-" * 50)
    
    volume_ok = sum(1 for v in volume_ratios if v >= 1.5)
    rsi_ok = sum(1 for r in rsi_values if 30 < r < 70)
    trend_up = sum(1 for t in trends if t == "UP")
    
    print(f"成交量>=1.5x (满足买入): {volume_ok}/{len(market_states)} ({volume_ok/len(market_states)*100:.1f}%)")
    print(f"RSI在30-70区间 (满足买入): {rsi_ok}/{len(market_states)} ({rsi_ok/len(market_states)*100:.1f}%)")
    print(f"趋势向上 (满足买入): {trend_up}/{len(market_states)} ({trend_up/len(market_states)*100:.1f}%)")
    
    # 同时满足多个条件
    all_ok = sum(1 for i in range(len(market_states)) 
                 if market_states[i]['volume_ratio'] >= 1.5 
                 and 30 < market_states[i]['rsi'] < 70 
                 and market_states[i]['trend'] == 'UP')
    print(f"同时满足3个条件: {all_ok}/{len(market_states)} ({all_ok/len(market_states)*100:.1f}%)")
    
    return market_states, signals_generated

if __name__ == "__main__":
    analyze_strategy_changes()
