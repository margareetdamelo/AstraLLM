"""
Order Simulator for Backtesting

Simulates order execution with realistic slippage, fees, and fill logic.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import numpy as np


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class PositionSide(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class Order:
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    leverage: int = 1
    reduce_only: bool = False
    status: str = "PENDING"
    filled_price: Optional[float] = None
    filled_quantity: float = 0.0
    commission: float = 0.0
    created_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class Position:
    symbol: str
    side: PositionSide
    entry_price: float
    quantity: float
    leverage: int
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    unrealized_pnl: float = 0.0
    liquidation_price: Optional[float] = None
    entry_time: Optional[datetime] = None

    def __post_init__(self):
        if self.entry_time is None:
            self.entry_time = datetime.now()


@dataclass
class BacktestConfig:
    initial_capital: float = 10000.0
    maker_fee: float = 0.0004
    taker_fee: float = 0.0007
    slippage_base: float = 0.0002
    slippage_volatility_factor: float = 0.0001
    min_slippage: float = 0.0001
    max_slippage: float = 0.001
    funding_rate: float = 0.0001
    funding_interval_hours: int = 8


class OrderSimulator:
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.positions: Dict[str, Position] = {}
        self.orders: List[Order] = []
        self.order_counter = 0
        self.total_commission = 0.0
        self.balance = config.initial_capital

    def reset(self):
        self.positions.clear()
        self.orders.clear()
        self.order_counter = 0
        self.total_commission = 0.0
        self.balance = self.config.initial_capital

    def generate_order_id(self) -> str:
        self.order_counter += 1
        return f"BT_{self.order_counter}_{int(datetime.now().timestamp() * 1000)}"

    def calculate_slippage(self, price: float, side: OrderSide, volatility: float = 0.02) -> float:
        slippage = self.config.slippage_base + (volatility * self.config.slippage_volatility_factor)
        slippage = min(max(slippage, self.config.min_slippage), self.config.max_slippage)

        if side == OrderSide.BUY:
            return price * (1 + slippage)
        else:
            return price * (1 - slippage)

    def calculate_fee(self, price: float, quantity: float, is_taker: bool = True) -> float:
        fee_rate = self.config.taker_fee if is_taker else self.config.maker_fee
        return price * quantity * fee_rate

    def calculate_liquidation_price(self, entry_price: float, leverage: int, side: PositionSide,
                                    maintenance_margin_rate: float = 0.005) -> float:
        if side == PositionSide.LONG:
            return entry_price * (1 - (1 / leverage) + maintenance_margin_rate)
        else:
            return entry_price * (1 + (1 / leverage) - maintenance_margin_rate)

    def can_open_position(self, symbol: str, price: float, quantity: float,
                         leverage: int, side: PositionSide) -> Tuple[bool, str]:
        margin_required = (price * quantity) / leverage
        if margin_required > self.balance:
            return False, f"Insufficient balance. Required: {margin_required:.2f}, Available: {self.balance:.2f}"

        if symbol in self.positions:
            existing = self.positions[symbol]
            if existing.side != side:
                return False, f"Opposite position already exists for {symbol}"
            if existing.quantity + quantity > self.get_max_quantity(symbol, price, leverage):
                return False, "Max position size exceeded"

        return True, "OK"

    def get_max_quantity(self, symbol: str, price: float, leverage: int) -> float:
        available_balance = self.balance
        return (available_balance * leverage) / price

    def open_position(self, symbol: str, side: PositionSide, entry_price: float,
                     quantity: float, leverage: int, stop_loss: Optional[float] = None,
                     take_profit: Optional[float] = None) -> Optional[Position]:
        can_open, reason = self.can_open_position(symbol, entry_price, quantity, leverage, side)
        if not can_open:
            return None

        liquidation_price = self.calculate_liquidation_price(entry_price, leverage, side)

        position = Position(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            leverage=leverage,
            stop_loss=stop_loss,
            take_profit=take_profit,
            liquidation_price=liquidation_price
        )

        self.positions[symbol] = position

        margin = (entry_price * quantity) / leverage
        self.balance -= margin

        return position

    def close_position(self, symbol: str, exit_price: float,
                      reason: str = "manual") -> Optional[Tuple[Position, float, float]]:
        if symbol not in self.positions:
            return None

        position = self.positions[symbol]

        if position.side == PositionSide.LONG:
            pnl = (exit_price - position.entry_price) * position.quantity
        else:
            pnl = (position.entry_price - exit_price) * position.quantity

        pnl = pnl - (exit_price * position.quantity * self.config.taker_fee)

        margin = (position.entry_price * position.quantity) / position.leverage
        self.balance += margin + pnl

        closed_position = self.positions.pop(symbol)
        self.total_commission += exit_price * position.quantity * self.config.taker_fee

        return closed_position, pnl, exit_price

    def update_positions(self, current_prices: Dict[str, float]) -> Dict[str, Tuple[str, float]]:
        triggered = {}

        for symbol, position in list(self.positions.items()):
            if symbol not in current_prices:
                continue

            current_price = current_prices[symbol]

            if position.side == PositionSide.LONG:
                position.unrealized_pnl = (current_price - position.entry_price) * position.quantity
            else:
                position.unrealized_pnl = (position.entry_price - current_price) * position.quantity

            if position.stop_loss:
                triggered_sl = False
                if position.side == PositionSide.LONG and current_price <= position.stop_loss:
                    triggered_sl = True
                elif position.side == PositionSide.SHORT and current_price >= position.stop_loss:
                    triggered_sl = True

                if triggered_sl:
                    closed, pnl, price = self.close_position(symbol, position.stop_loss, "stop_loss")
                    if closed:
                        triggered[symbol] = ("stop_loss", pnl)
                    continue

            if position.take_profit:
                triggered_tp = False
                if position.side == PositionSide.LONG and current_price >= position.take_profit:
                    triggered_tp = True
                elif position.side == PositionSide.SHORT and current_price <= position.take_profit:
                    triggered_tp = True

                if triggered_tp:
                    closed, pnl, price = self.close_position(symbol, position.take_profit, "take_profit")
                    if closed:
                        triggered[symbol] = ("take_profit", pnl)
                    continue

            if position.liquidation_price:
                triggered_liq = False
                if position.side == PositionSide.LONG and current_price <= position.liquidation_price:
                    triggered_liq = True
                elif position.side == PositionSide.SHORT and current_price >= position.liquidation_price:
                    triggered_liq = True

                if triggered_liq:
                    closed, pnl, price = self.close_position(symbol, position.liquidation_price, "liquidation")
                    if closed:
                        triggered[symbol] = ("liquidation", pnl)

        return triggered

    def get_equity(self, current_prices: Dict[str, float]) -> float:
        equity = self.balance

        for symbol, position in self.positions.items():
            if symbol in current_prices:
                current_price = current_prices[symbol]
                if position.side == PositionSide.LONG:
                    unrealized = (current_price - position.entry_price) * position.quantity
                else:
                    unrealized = (position.entry_price - current_price) * position.quantity
                equity += unrealized

        return equity

    def get_positions_summary(self) -> List[Dict]:
        summary = []
        for symbol, position in self.positions.items():
            summary.append({
                "symbol": symbol,
                "side": position.side.value,
                "entry_price": position.entry_price,
                "quantity": position.quantity,
                "leverage": position.leverage,
                "unrealized_pnl": position.unrealized_pnl,
                "stop_loss": position.stop_loss,
                "take_profit": position.take_profit,
                "liquidation_price": position.liquidation_price
            })
        return summary
