"""
Backtest Engine - Core engine for strategy backtesting

This module provides the main BacktestEngine class that orchestrates the entire backtesting process.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from loguru import logger

from .order_simulator import (
    OrderSimulator,
    OrderSide,
    PositionSide,
    BacktestConfig,
    Position
)
from .performance import (
    PerformanceAnalyzer,
    TradeRecord,
    PerformanceMetrics
)


@dataclass
class BacktestResult:
    symbol: str
    strategy_name: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    metrics: Dict
    trades: List[Dict]
    equity_curve: List[Dict]
    daily_stats: Dict
    strategy_stats: Dict


class BacktestEngine:
    def __init__(self, initial_capital: float = 10000.0, strategies: List = None):
        self.initial_capital = initial_capital
        self.strategies = strategies or []

        self.config = BacktestConfig(initial_capital=initial_capital)
        self.order_simulator = OrderSimulator(self.config)
        self.performance_analyzer = PerformanceAnalyzer(initial_capital)

        self.current_df = None
        self.current_symbol = None
        self.current_strategy = None
        self.results = []

    def add_strategy(self, strategy):
        self.strategies.append(strategy)

    def reset(self):
        self.order_simulator.reset()
        self.performance_analyzer.reset()
        self.current_df = None
        self.current_symbol = None
        self.current_strategy = None

    def prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        if 'timestamp' not in df.columns:
            raise ValueError("DataFrame must have 'timestamp' column")

        df = df.sort_values('timestamp').reset_index(drop=True)

        required_columns = ['open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            if col not in df.columns:
                raise ValueError(f"DataFrame must have '{col}' column")

        df['returns'] = df['close'].pct_change()
        df['log_returns'] = np.log(df['close'] / df['close'].shift(1))

        df['volatility'] = df['returns'].rolling(window=20).std()

        if len(df) > 20:
            df['atr'] = self._calculate_atr(df)

        df = df.fillna(0)

        return df

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df['high']
        low = df['low']
        close = df['close']

        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()

        return atr

    def run_backtest(self, df: pd.DataFrame, symbol: str, strategy,
                    funding_history: Optional[List[Dict]] = None) -> Dict:
        self.reset()

        self.current_symbol = symbol
        self.current_strategy = strategy

        df = self.prepare_data(df)

        logger.info(f"Starting backtest for {symbol} with {strategy.name}")
        logger.info(f"Data range: {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")
        logger.info(f"Total candles: {len(df)}")

        signals_generated = 0
        trades_executed = 0
        skip_warmup = strategy.get_required_candles() if hasattr(strategy, 'get_required_candles') else 50

        for i in range(skip_warmup, len(df)):
            current_bar = df.iloc[i]
            current_time = current_bar['timestamp']
            current_price = current_bar['close']
            current_date = pd.to_datetime(current_time)

            historical_df = df.iloc[:i+1].copy()

            current_prices = {symbol: current_price}
            triggered = self.order_simulator.update_positions(current_prices)

            for triggered_symbol, (exit_reason, pnl) in triggered.items():
                if triggered_symbol in self.order_simulator.positions:
                    continue

                position = None
                for pos in list(self.order_simulator.positions.values()):
                    if pos.symbol == triggered_symbol:
                        position = pos
                        break

                if position:
                    hold_duration = (current_date - position.entry_time).total_seconds()

                    trade_record = TradeRecord(
                        symbol=triggered_symbol,
                        side=position.side.value,
                        entry_price=position.entry_price,
                        exit_price=current_price,
                        quantity=position.quantity,
                        leverage=position.leverage,
                        pnl=pnl,
                        pnl_percentage=(pnl / (position.entry_price * position.quantity)) * 100,
                        commission=current_price * position.quantity * self.config.taker_fee,
                        entry_time=position.entry_time,
                        exit_time=current_date,
                        hold_duration_seconds=int(hold_duration),
                        exit_reason=exit_reason,
                        strategy=strategy.name
                    )

                    self.performance_analyzer.add_trade(trade_record)
                    trades_executed += 1

            equity = self.order_simulator.get_equity(current_prices)
            self.performance_analyzer.add_equity_point(current_date, equity)

            if symbol in self.order_simulator.positions:
                continue

            try:
                signal = self._generate_signal(strategy, historical_df, symbol, funding_history)

                if signal and signal.get('confidence', 0) >= 0.4:
                    side = signal['action']
                    entry_price = current_price

                    slippage_price = self.order_simulator.calculate_slippage(
                        entry_price,
                        OrderSide.BUY if side == "LONG" else OrderSide.SELL,
                        current_bar.get('volatility', 0.02)
                    )

                    leverage = signal.get('leverage', 10)

                    stop_loss = signal.get('stop_loss')
                    if not stop_loss:
                        if side == "LONG":
                            stop_loss = entry_price * 0.97
                        else:
                            stop_loss = entry_price * 1.03

                    quantity = self._calculate_position_size(
                        symbol,
                        slippage_price,
                        stop_loss,
                        leverage,
                        current_bar.get('volatility', 0.02)
                    )

                    logger.info(f"Signal: action={signal.get('action')}, entry={entry_price}, stop={stop_loss}, qty={quantity:.6f}, bal={self.order_simulator.balance:.2f}")

                    # Minimum quantity for U-M futures (1 contract = 0.001 BTC = 1 张)
                    if quantity >= 0.001:
                        position_side = PositionSide.LONG if side == "LONG" else PositionSide.SHORT

                        logger.info(f"Opening position: {position_side.value} {quantity} @ {slippage_price}")

                        position = self.order_simulator.open_position(
                            symbol=symbol,
                            side=position_side,
                            entry_price=slippage_price,
                            quantity=quantity,
                            leverage=leverage,
                            stop_loss=signal.get('stop_loss'),
                            take_profit=signal.get('take_profit')
                        )

                        if position:
                            signals_generated += 1

            except Exception as e:
                logger.debug(f"Error generating signal at index {i}: {e}")

        self._close_remaining_positions(df.iloc[-1]['timestamp'], df.iloc[-1]['close'])

        metrics = self.performance_analyzer.calculate_metrics()
        metrics_dict = self.performance_analyzer.to_dict(metrics)

        trades = [
            {
                "symbol": t.symbol,
                "side": t.side,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "leverage": t.leverage,
                "pnl": round(t.pnl, 2),
                "pnl_percentage": round(t.pnl_percentage, 2),
                "entry_time": t.entry_time.isoformat(),
                "exit_time": t.exit_time.isoformat(),
                "hold_duration_seconds": t.hold_duration_seconds,
                "exit_reason": t.exit_reason,
                "strategy": t.strategy
            }
            for t in self.performance_analyzer.trades
        ]

        equity_curve = [
            {"timestamp": e[0].isoformat(), "equity": round(e[1], 2)}
            for e in self.performance_analyzer.equity_curve
        ]

        strategy_stats = self.performance_analyzer.get_strategy_performance()
        daily_stats = self.performance_analyzer.get_daily_performance()

        logger.info(f"Backtest completed: {signals_generated} signals, {trades_executed} trades executed")

        return {
            "symbol": symbol,
            "strategy": strategy.name,
            "initial_capital": self.initial_capital,
            "final_capital": self.order_simulator.balance,
            "metrics": metrics_dict,
            "trades": trades,
            "equity_curve": equity_curve,
            "strategy_stats": strategy_stats,
            "daily_stats": daily_stats,
            "signals_generated": signals_generated,
            "trades_executed": trades_executed
        }

    def run_multi_strategy_backtest(self, df: pd.DataFrame, symbol: str,
                                   funding_history: Optional[List[Dict]] = None) -> Dict:
        if not self.strategies:
            logger.warning("No strategies configured for backtest")
            return {}

        all_results = {}
        best_strategy = None
        best_pnl = float('-inf')

        logger.info(f"Running multi-strategy backtest for {symbol} with {len(self.strategies)} strategies")

        for strategy in self.strategies:
            logger.info(f"\n{'='*50}")
            logger.info(f"Testing strategy: {strategy.name}")
            logger.info(f"{'='*50}")

            result = self.run_backtest(df, symbol, strategy, funding_history)
            all_results[strategy.name] = result

            if result['metrics']['total_pnl'] > best_pnl:
                best_pnl = result['metrics']['total_pnl']
                best_strategy = strategy.name

        return {
            "symbol": symbol,
            "strategies_tested": [s.name for s in self.strategies],
            "best_strategy": best_strategy,
            "best_pnl": best_pnl,
            "results": all_results,
            "summary": {
                strategy_name: {
                    "total_pnl": result["metrics"]["total_pnl"],
                    "win_rate": result["metrics"]["win_rate"],
                    "total_trades": result["metrics"]["total_trades"],
                    "sharpe_ratio": result["metrics"]["sharpe_ratio"],
                    "max_drawdown": result["metrics"]["max_drawdown"]
                }
                for strategy_name, result in all_results.items()
            }
        }

    def _generate_signal(self, strategy, df: pd.DataFrame, symbol: str,
                        funding_history: Optional[List[Dict]] = None) -> Optional[Dict]:
        try:
            if hasattr(strategy, 'analyze'):
                return strategy.analyze(df, symbol)
            return None
        except Exception as e:
            logger.debug(f"Signal generation error: {e}")
            return None

    def _calculate_position_size(self, symbol: str, entry_price: float,
                               stop_loss: float, leverage: int,
                               volatility: float = 0.02) -> float:
        risk_per_trade = 0.02
        risk_amount = self.order_simulator.balance * risk_per_trade

        if volatility:
            volatility_multiplier = max(0.5, 1 - (volatility * 2))
            risk_amount *= volatility_multiplier

        stop_distance = abs(entry_price - stop_loss) / entry_price

        if stop_distance == 0:
            return 0

        position_value = risk_amount / stop_distance
        quantity = position_value / entry_price

        leverage_adjustment = min(1.0, 20 / leverage)
        quantity *= leverage_adjustment

        max_quantity = self.order_simulator.get_max_quantity(symbol, entry_price, leverage)
        quantity = min(quantity, max_quantity)

        return quantity

    def _close_remaining_positions(self, exit_time, exit_price):
        for symbol, position in list(self.order_simulator.positions.items()):
            if position.side == PositionSide.LONG:
                pnl = (exit_price - position.entry_price) * position.quantity
            else:
                pnl = (position.entry_price - exit_price) * position.quantity

            pnl = pnl - (exit_price * position.quantity * self.config.taker_fee)

            exit_reason = "end_of_backtest"

            trade_record = TradeRecord(
                symbol=symbol,
                side=position.side.value,
                entry_price=position.entry_price,
                exit_price=exit_price,
                quantity=position.quantity,
                leverage=position.leverage,
                pnl=pnl,
                pnl_percentage=(pnl / (position.entry_price * position.quantity)) * 100,
                commission=exit_price * position.quantity * self.config.taker_fee,
                entry_time=position.entry_time,
                exit_time=pd.to_datetime(exit_time),
                hold_duration_seconds=int((pd.to_datetime(exit_time) - position.entry_time).total_seconds()),
                exit_reason=exit_reason,
                strategy=self.current_strategy.name if self.current_strategy else "unknown"
            )

            self.performance_analyzer.add_trade(trade_record)

        self.order_simulator.positions.clear()

    def save_results(self, results: Dict, filename: str):
        try:
            with open(filename, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            logger.info(f"Results saved to {filename}")
        except Exception as e:
            logger.error(f"Error saving results: {e}")

    def print_results(self, results: Dict):
        print("\n" + "=" * 70)
        print(f"BACKTEST RESULTS - {results.get('symbol', 'N/A')} | {results.get('strategy', 'N/A')}")
        print("=" * 70)

        metrics = results.get('metrics', {})

        print(f"\n📊 Capital:")
        print(f"   Initial: ${results.get('initial_capital', 0):.2f}")
        print(f"   Final: ${results.get('final_capital', 0):.2f}")
        print(f"   PnL: ${metrics.get('total_pnl', 0):.2f}")
        print(f"   ROI: {metrics.get('roi', 0):.2f}%")

        print(f"\n📈 Trade Statistics:")
        print(f"   Total Trades: {metrics.get('total_trades', 0)}")
        print(f"   Winning: {metrics.get('winning_trades', 0)}")
        print(f"   Losing: {metrics.get('losing_trades', 0)}")
        print(f"   Win Rate: {metrics.get('win_rate', 0):.2f}%")

        print(f"\n💰 Profit Metrics:")
        print(f"   Gross Profit: ${metrics.get('gross_profit', 0):.2f}")
        print(f"   Gross Loss: ${metrics.get('gross_loss', 0):.2f}")
        print(f"   Profit Factor: {metrics.get('profit_factor', 0):.2f}")
        print(f"   Avg Win: ${metrics.get('avg_win', 0):.2f}")
        print(f"   Avg Loss: ${metrics.get('avg_loss', 0):.2f}")

        print(f"\n⚠️ Risk Metrics:")
        print(f"   Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}")
        print(f"   Max Drawdown: {metrics.get('max_drawdown', 0):.2f}%")
        print(f"   Volatility: {metrics.get('volatility', 0):.2f}%")

        print(f"\n🔢 Trade Info:")
        print(f"   Signals Generated: {results.get('signals_generated', 0)}")
        print(f"   Trades Executed: {results.get('trades_executed', 0)}")

        print("=" * 70)
