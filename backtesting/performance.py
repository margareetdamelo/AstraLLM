"""
Performance Analyzer for Backtesting

Calculates comprehensive performance metrics including returns, risk metrics, and trade statistics.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import numpy as np
import pandas as pd


@dataclass
class TradeRecord:
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    leverage: int
    pnl: float
    pnl_percentage: float
    commission: float
    entry_time: datetime
    exit_time: datetime
    hold_duration_seconds: int
    exit_reason: str
    strategy: str


@dataclass
class PerformanceMetrics:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_pnl_percentage: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_hold_time_seconds: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_percentage: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    avg_trades_per_day: float = 0.0
    volatility: float = 0.0
    calmar_ratio: float = 0.0
    roi: float = 0.0


class PerformanceAnalyzer:
    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.trades: List[TradeRecord] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.daily_returns: List[float] = []

    def reset(self):
        self.trades.clear()
        self.equity_curve.clear()
        self.daily_returns.clear()

    def add_trade(self, trade: TradeRecord):
        self.trades.append(trade)

    def add_equity_point(self, timestamp: datetime, equity: float):
        self.equity_curve.append((timestamp, equity))

    def calculate_metrics(self) -> PerformanceMetrics:
        if not self.trades:
            return PerformanceMetrics()

        metrics = PerformanceMetrics()

        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl <= 0]

        metrics.total_trades = len(self.trades)
        metrics.winning_trades = len(winning_trades)
        metrics.losing_trades = len(losing_trades)

        if metrics.total_trades > 0:
            metrics.win_rate = (metrics.winning_trades / metrics.total_trades) * 100

        metrics.total_pnl = sum(t.pnl for t in self.trades)
        metrics.gross_profit = sum(t.pnl for t in winning_trades) if winning_trades else 0.0
        metrics.gross_loss = abs(sum(t.pnl for t in losing_trades)) if losing_trades else 0.0

        if metrics.gross_loss > 0:
            metrics.profit_factor = metrics.gross_profit / metrics.gross_loss
        elif metrics.gross_profit > 0:
            metrics.profit_factor = float('inf')

        metrics.avg_win = metrics.gross_profit / metrics.winning_trades if metrics.winning_trades else 0.0
        metrics.avg_loss = metrics.gross_loss / metrics.losing_trades if metrics.losing_trades else 0.0

        hold_times = [t.hold_duration_seconds for t in self.trades]
        metrics.avg_hold_time_seconds = np.mean(hold_times) if hold_times else 0.0

        metrics.roi = ((self.initial_capital + metrics.total_pnl - self.initial_capital) / self.initial_capital) * 100

        self._calculate_risk_metrics(metrics)

        return metrics

    def _calculate_risk_metrics(self, metrics: PerformanceMetrics):
        if not self.equity_curve or len(self.equity_curve) < 2:
            return

        equity_values = [e[1] for e in self.equity_curve]
        equity_series = pd.Series(equity_values)

        returns = equity_series.pct_change().dropna()

        if len(returns) > 0:
            metrics.volatility = returns.std() * 100

            if returns.std() > 0:
                metrics.sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252 * 24 * 60 / 5)

                downside_returns = returns[returns < 0]
                if len(downside_returns) > 0 and downside_returns.std() > 0:
                    metrics.sortino_ratio = (returns.mean() / downside_returns.std()) * np.sqrt(252 * 24 * 60 / 5)

        peak = equity_series.expanding(min_periods=1).max()
        drawdown = (equity_series - peak) / peak * 100

        metrics.max_drawdown_percentage = abs(drawdown.min()) if len(drawdown) > 0 else 0.0

        peak_value = equity_series.iloc[0]
        max_dd_value = 0
        for value in equity_series:
            if value > peak_value:
                peak_value = value
            dd = (peak_value - value) / peak_value
            if dd > max_dd_value:
                max_dd_value = dd

        metrics.max_drawdown = max_dd_value * 100

        if metrics.max_drawdown > 0 and len(self.trades) > 0:
            total_days = (self.trades[-1].exit_time - self.trades[0].entry_time).days
            if total_days > 0:
                annual_return = (metrics.total_pnl / self.initial_capital) / total_days * 365
                metrics.calmar_ratio = annual_return / metrics.max_drawdown_percentage

        self._calculate_consecutive_trades(metrics)

        if len(self.trades) > 0:
            first_trade_date = self.trades[0].entry_time.date()
            last_trade_date = self.trades[-1].exit_time.date()
            days_diff = (last_trade_date - first_trade_date).days
            if days_diff > 0:
                metrics.avg_trades_per_day = len(self.trades) / days_diff

    def _calculate_consecutive_trades(self, metrics: PerformanceMetrics):
        if not self.trades:
            return

        max_consecutive_wins = 0
        max_consecutive_losses = 0
        current_wins = 0
        current_losses = 0

        for trade in self.trades:
            if trade.pnl > 0:
                current_wins += 1
                current_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, current_wins)
            else:
                current_losses += 1
                current_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, current_losses)

        metrics.max_consecutive_wins = max_consecutive_wins
        metrics.max_consecutive_losses = max_consecutive_losses

    def get_strategy_performance(self) -> Dict[str, Dict]:
        strategy_stats = {}

        for trade in self.trades:
            strategy = trade.strategy

            if strategy not in strategy_stats:
                strategy_stats[strategy] = {
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "total_pnl": 0.0,
                    "gross_profit": 0.0,
                    "gross_loss": 0.0,
                }

            stats = strategy_stats[strategy]
            stats["total_trades"] += 1

            if trade.pnl > 0:
                stats["winning_trades"] += 1
                stats["gross_profit"] += trade.pnl
            else:
                stats["losing_trades"] += 1
                stats["gross_loss"] += abs(trade.pnl)

            stats["total_pnl"] += trade.pnl

        for strategy, stats in strategy_stats.items():
            if stats["total_trades"] > 0:
                stats["win_rate"] = (stats["winning_trades"] / stats["total_trades"]) * 100

            if stats["gross_loss"] > 0:
                stats["profit_factor"] = stats["gross_profit"] / stats["gross_loss"]
            else:
                stats["profit_factor"] = float('inf') if stats["gross_profit"] > 0 else 0.0

            stats["avg_pnl"] = stats["total_pnl"] / stats["total_trades"]

        return strategy_stats

    def get_daily_performance(self) -> Dict[str, Dict]:
        daily_stats = {}

        for trade in self.trades:
            date_key = trade.exit_time.strftime("%Y-%m-%d")

            if date_key not in daily_stats:
                daily_stats[date_key] = {
                    "date": date_key,
                    "trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "pnl": 0.0,
                }

            daily = daily_stats[date_key]
            daily["trades"] += 1

            if trade.pnl > 0:
                daily["winning_trades"] += 1
            else:
                daily["losing_trades"] += 1

            daily["pnl"] += trade.pnl

        for date_key, daily in daily_stats.items():
            if daily["trades"] > 0:
                daily["win_rate"] = (daily["winning_trades"] / daily["trades"]) * 100

        return daily_stats

    def get_symbol_performance(self) -> Dict[str, Dict]:
        symbol_stats = {}

        for trade in self.trades:
            symbol = trade.symbol

            if symbol not in symbol_stats:
                symbol_stats[symbol] = {
                    "symbol": symbol,
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "total_pnl": 0.0,
                }

            stats = symbol_stats[symbol]
            stats["total_trades"] += 1

            if trade.pnl > 0:
                stats["winning_trades"] += 1
            else:
                stats["losing_trades"] += 1

            stats["total_pnl"] += trade.pnl

        for symbol, stats in symbol_stats.items():
            if stats["total_trades"] > 0:
                stats["win_rate"] = (stats["winning_trades"] / stats["total_trades"]) * 100

        return symbol_stats

    def to_dict(self, metrics: PerformanceMetrics) -> Dict:
        return {
            "total_trades": metrics.total_trades,
            "winning_trades": metrics.winning_trades,
            "losing_trades": metrics.losing_trades,
            "win_rate": round(metrics.win_rate, 2),
            "total_pnl": round(metrics.total_pnl, 2),
            "total_pnl_percentage": round(metrics.total_pnl_percentage, 2),
            "gross_profit": round(metrics.gross_profit, 2),
            "gross_loss": round(metrics.gross_loss, 2),
            "profit_factor": round(metrics.profit_factor, 2) if metrics.profit_factor != float('inf') else float('inf'),
            "avg_win": round(metrics.avg_win, 2),
            "avg_loss": round(metrics.avg_loss, 2),
            "avg_hold_time_seconds": round(metrics.avg_hold_time_seconds, 2),
            "sharpe_ratio": round(metrics.sharpe_ratio, 2),
            "sortino_ratio": round(metrics.sortino_ratio, 2),
            "max_drawdown": round(metrics.max_drawdown, 2),
            "max_drawdown_percentage": round(metrics.max_drawdown_percentage, 2),
            "max_consecutive_wins": metrics.max_consecutive_wins,
            "max_consecutive_losses": metrics.max_consecutive_losses,
            "avg_trades_per_day": round(metrics.avg_trades_per_day, 2),
            "volatility": round(metrics.volatility, 2),
            "calmar_ratio": round(metrics.calmar_ratio, 2),
            "roi": round(metrics.roi, 2),
            "initial_capital": self.initial_capital,
            "final_capital": self.initial_capital + metrics.total_pnl,
        }

    def print_summary(self, metrics: PerformanceMetrics):
        print("\n" + "=" * 60)
        print("BACKTEST PERFORMANCE SUMMARY")
        print("=" * 60)

        print(f"\n📊 Trade Statistics:")
        print(f"   Total Trades: {metrics.total_trades}")
        print(f"   Winning Trades: {metrics.winning_trades}")
        print(f"   Losing Trades: {metrics.losing_trades}")
        print(f"   Win Rate: {metrics.win_rate:.2f}%")

        print(f"\n💰 Profit/Loss:")
        print(f"   Total PnL: ${metrics.total_pnl:.2f}")
        print(f"   Gross Profit: ${metrics.gross_profit:.2f}")
        print(f"   Gross Loss: ${metrics.gross_loss:.2f}")
        print(f"   Profit Factor: {metrics.profit_factor:.2f}" if metrics.profit_factor != float('inf') else "   Profit Factor: ∞")
        print(f"   Average Win: ${metrics.avg_win:.2f}")
        print(f"   Average Loss: ${metrics.avg_loss:.2f}")
        print(f"   ROI: {metrics.roi:.2f}%")

        print(f"\n📈 Risk Metrics:")
        print(f"   Sharpe Ratio: {metrics.sharpe_ratio:.2f}")
        print(f"   Sortino Ratio: {metrics.sortino_ratio:.2f}")
        print(f"   Max Drawdown: {metrics.max_drawdown:.2f}%")
        print(f"   Volatility: {metrics.volatility:.2f}%")
        print(f"   Calmar Ratio: {metrics.calmar_ratio:.2f}")

        print(f"\n🔢 Consecutive Trades:")
        print(f"   Max Consecutive Wins: {metrics.max_consecutive_wins}")
        print(f"   Max Consecutive Losses: {metrics.max_consecutive_losses}")

        print(f"\n⏱️ Timing:")
        print(f"   Avg Hold Time: {metrics.avg_hold_time_seconds / 60:.2f} minutes")
        print(f"   Avg Trades/Day: {metrics.avg_trades_per_day:.2f}")

        print("=" * 60)
