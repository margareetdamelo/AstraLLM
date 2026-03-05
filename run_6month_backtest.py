"""
Run 6-month backtest with equity curve + BTC price comparison
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
os.environ["API_SECRET_KEY"] = "test_secret_key_for_backtest"

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from loguru import logger

from backtesting import BacktestEngine
from strategies import BacktestStrategy

logger.remove()
logger.add(sys.stderr, level="WARNING")

ASTER_FUTURES_API = "https://fapi.asterdex.com"

def fetch_historical_data(symbol, start_time_ms, end_time_ms, max_candles=5000):
    """分页获取历史K线数据"""
    all_klines = []
    current_start = start_time_ms

    while current_start < end_time_ms:
        try:
            url = f"{ASTER_FUTURES_API}/fapi/v1/klines"
            params = {
                "symbol": symbol,
                "interval": "1h",
                "startTime": current_start,
                "endTime": end_time_ms,
                "limit": 100
            }

            response = requests.get(url, params=params, timeout=30)

            if response.status_code != 200:
                break

            data = response.json()

            if isinstance(data, dict):
                break

            if not data:
                break

            all_klines.extend(data)

            last_time = data[-1][0]
            current_start = last_time + 1

            if len(data) < 100:
                break

            if len(all_klines) >= max_candles:
                break

        except Exception as e:
            logger.error(f"Error: {e}")
            break

    return all_klines

def run_backtest():
    """运行6个月回测"""
    logger.info("Starting 6-month backtest...")

    end_time = datetime.now()
    start_time = end_time - timedelta(days=180)

    start_time_ms = int(start_time.timestamp() * 1000)
    end_time_ms = int(end_time.timestamp() * 1000)

    logger.info(f"Period: {start_time.strftime('%Y-%m-%d')} to {end_time.strftime('%Y-%m-%d')}")

    symbols = ["BTCUSDT", "ETHUSDT"]

    strategies = [
        BacktestStrategy(leverage=5),
    ]

    all_results = {}
    all_daily_pnl = defaultdict(list)
    btc_price_data = {}

    # Fetch BTC price data for comparison
    logger.info("Fetching BTC price data for comparison...")
    btc_klines = fetch_historical_data("BTCUSDT", start_time_ms, end_time_ms)
    if btc_klines:
        btc_df = pd.DataFrame(btc_klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])
        btc_df['timestamp'] = pd.to_datetime(btc_df['timestamp'], unit='ms')
        btc_df['close'] = btc_df['close'].astype(float)
        
        # Group by date and get daily close price
        btc_df['date'] = btc_df['timestamp'].dt.strftime('%Y-%m-%d')
        btc_daily = btc_df.groupby('date')['close'].last()
        btc_price_data = btc_daily.to_dict()
        logger.info(f"Got {len(btc_price_data)} days of BTC price data")

    for symbol in symbols:
        logger.info(f"Processing {symbol}")

        klines = fetch_historical_data(symbol, start_time_ms, end_time_ms)

        if not klines or len(klines) == 0:
            continue

        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])

        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)

        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
        df = df.drop_duplicates(subset=['timestamp']).reset_index(drop=True)

        if len(df) < 100:
            continue

        engine = BacktestEngine(initial_capital=10000, strategies=strategies)
        result = engine.run_multi_strategy_backtest(df, symbol, None)

        for trade in engine.performance_analyzer.trades:
            date_key = trade.exit_time.strftime('%Y-%m-%d')
            all_daily_pnl[date_key].append(trade.pnl)

        all_results[symbol] = result

    return all_results, all_daily_pnl, btc_price_data

def generate_report(all_results, daily_pnl, btc_price_data):
    """生成回测报告"""
    
    all_days = sorted(daily_pnl.keys())
    daily_summary = []
    cumulative_pnl = 0
    
    for day in all_days:
        day_pnl = sum(daily_pnl[day])
        cumulative_pnl += day_pnl
        daily_summary.append({
            'date': day,
            'daily_pnl': day_pnl,
            'cumulative_pnl': cumulative_pnl
        })
    
    daily_table = "| 日期 | 当日盈亏 | 累计盈亏 |\n|------|----------|----------|\n"
    for row in daily_summary:
        sign = "+" if row['daily_pnl'] >= 0 else ""
        cum_sign = "+" if row['cumulative_pnl'] >= 0 else ""
        daily_table += f"| {row['date']} | {sign}{row['daily_pnl']:.2f} | {cum_sign}{row['cumulative_pnl']:.2f} |\n"

    report = []

    report.append("# Astra LLM 6个月回测报告")
    report.append("")
    report.append(f"**回测时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"**初始资金**: $10,000 USDT")
    report.append(f"**回测周期**: 过去6个月")
    report.append(f"**时间周期**: 1小时K线")
    report.append(f"**测试策略**: BacktestStrategy (宽松过滤器)")
    report.append("")
    report.append("---")
    report.append("")
    report.append("## 汇总统计")
    report.append("")

    total_pnl = 0
    total_trades = 0

    for symbol, result in all_results.items():
        results = result.get('results', {})
        for strategy_name, stats in results.items():
            metrics = stats.get('metrics', {})
            total_pnl += metrics.get('total_pnl', 0)
            total_trades += metrics.get('total_trades', 0)

    report.append(f"- **总交易次数**: {total_trades}")
    report.append(f"- **总盈亏**: ${total_pnl:.2f}")
    if total_trades > 0:
        report.append(f"- **总收益率**: {(total_pnl / 10000) * 100:.2f}%")
    report.append("")

    report.append("---")
    report.append("")
    report.append("## 各交易对详细结果")
    report.append("")

    for symbol, result in all_results.items():
        report.append(f"### {symbol}")
        report.append("")

        results = result.get('results', {})
        for strategy_name, stats in results.items():
            metrics = stats.get('metrics', {})
            report.append(f"#### {strategy_name}")
            report.append("")
            report.append(f"| 指标 | 数值 |")
            report.append(f"|------|------|")
            report.append(f"| 总交易次数 | {metrics.get('total_trades', 0)} |")
            report.append(f"| 胜率 | {metrics.get('win_rate', 0):.2f}% |")
            report.append(f"| 总盈亏 | ${metrics.get('total_pnl', 0):.2f} |")
            report.append(f"| 夏普比率 | {metrics.get('sharpe_ratio', 0):.2f} |")
            report.append(f"| 最大回撤 | {metrics.get('max_drawdown', 0):.2f}% |")
            report.append("")

    report.append("---")
    report.append("")
    report.append("## 日收益趋势")
    report.append("")
    report.append(daily_table)

    report.append("---")
    report.append("")
    report.append("## 权益曲线数据 (含BTC价格对比)")
    report.append("")
    report.append("| 时间 | 权益 | BTC价格 | 权益变化 | BTC变化 |")
    report.append("|------|------|---------|----------|---------|")
    
    first_equity = None
    first_btc_price = None
    
    for symbol, result in all_results.items():
        results = result.get('results', {})
        for strategy_name, stats in results.items():
            equity = stats.get('equity_curve', [])
            step = max(1, len(equity) // 50)
            
            for i in range(0, len(equity), step):
                e = equity[i]
                timestamp = e['timestamp'][:10]
                equity_val = e['equity']
                
                if first_equity is None:
                    first_equity = equity_val
                
                # Get BTC price for this date
                btc_price = btc_price_data.get(timestamp, None)
                btc_price_str = f"${btc_price:,.0f}" if btc_price else "N/A"
                
                if first_btc_price is None and btc_price:
                    first_btc_price = btc_price
                
                # Calculate changes
                equity_change = ((equity_val - first_equity) / first_equity * 100) if first_equity else 0
                btc_change = ((btc_price - first_btc_price) / first_btc_price * 100) if btc_price and first_btc_price else 0
                
                equity_sign = "+" if equity_change >= 0 else ""
                btc_sign = "+" if btc_change >= 0 else ""
                
                report.append(f"| {timestamp} | ${equity_val:,.2f} | {btc_price_str} | {equity_sign}{equity_change:.2f}% | {btc_sign}{btc_change:.2f}% |")
            break
        break

    return "\n".join(report), daily_summary

if __name__ == "__main__":
    results, daily_pnl, btc_price = run_backtest()

    if results:
        with open("backtest_results.json", "w") as f:
            json.dump(results, f, indent=2, default=str)

        report, daily_summary = generate_report(results, daily_pnl, btc_price)
        with open("wiki/03-回测报告.md", "w", encoding="utf-8") as f:
            f.write(report)

        print("\n" + report)
    else:
        print("No results generated")
