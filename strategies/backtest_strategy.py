"""
Simplified Backtest Strategy - For testing purposes only
Has relaxed filters to generate more trades
"""
from typing import Dict, Optional
import pandas as pd
import numpy as np
from loguru import logger


class BacktestStrategy:
    """
    A simplified strategy for backtesting with relaxed filters.
    This strategy is NOT for live trading - it just generates more signals.
    """

    name = "Backtest Strategy"

    def __init__(self, leverage: int = 5):
        self.leverage = leverage
        self.min_volume_ratio = 1.5  # Relaxed: 1.5x instead of 4x
        self.atr_threshold = 0.03  # Relaxed: 3% instead of 1.5%
        self.stop_loss_pct = 0.02
        self.take_profit_pct = 0.04

    def get_required_candles(self) -> int:
        return 30

    def analyze(self, df: pd.DataFrame, symbol: str) -> Optional[Dict]:
        """Generate signals with relaxed filters"""
        
        if len(df) < self.get_required_candles():
            return None

        current_price = df['close'].iloc[-1]
        current_bar = df.iloc[-1]

        # Calculate ATR
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=14).mean()
        atr_pct = atr.iloc[-1] / current_price if not pd.isna(atr.iloc[-1]) else 0

        # Volume analysis
        volume = df['volume']
        avg_volume = volume.rolling(window=20).mean().iloc[-1]
        volume_ratio = current_bar['volume'] / avg_volume if avg_volume > 0 else 0

        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50

        # Simple trend detection
        sma_20 = close.rolling(20).mean().iloc[-1]
        sma_50 = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else sma_20
        
        trend = "UP" if current_price > sma_20 else "DOWN"

        # Generate signal based on simple conditions
        # Relaxed: just need volume spike and reasonable RSI
        if volume_ratio >= self.min_volume_ratio:
            if current_rsi < 70 and current_rsi > 30:
                if trend == "UP" and current_price > sma_20:
                    # Long signal
                    stop_loss = current_price * (1 - self.stop_loss_pct)
                    take_profit = current_price * (1 + self.take_profit_pct)
                    
                    confidence = min(0.5 + (volume_ratio / 10), 0.9)
                    
                    return {
                        'action': 'LONG',
                        'entry_price': current_price,
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'leverage': self.leverage,
                        'confidence': confidence,
                        'reason': f'Backtest: Vol={volume_ratio:.1f}x, RSI={current_rsi:.0f}, Trend={trend}'
                    }
                elif trend == "DOWN" and current_price < sma_20:
                    # Short signal
                    stop_loss = current_price * (1 + self.stop_loss_pct)
                    take_profit = current_price * (1 - self.take_profit_pct)
                    
                    confidence = min(0.5 + (volume_ratio / 10), 0.9)
                    
                    return {
                        'action': 'SHORT',
                        'entry_price': current_price,
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'leverage': self.leverage,
                        'confidence': confidence,
                        'reason': f'Backtest: Vol={volume_ratio:.1f}x, RSI={current_rsi:.0f}, Trend={trend}'
                    }

        return None
