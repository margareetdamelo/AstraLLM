# 回测功能完整性分析报告

> 分析范围: `backtesting/engine.py`, `backtesting/order_simulator.py`, `backtesting/performance.py`, `main.py`, `run_backtest.py`, `strategies/backtest_strategy.py` 及全部 9 个策略文件
> 分析目标: 检查回测功能的完整性、正确性和可靠性

---

## 一、严重 BUG (3 个)

### BUG-1: [P0] SL/TP 触发后 TradeRecord 永远无法创建 -- 死代码

**文件**: `backtesting/engine.py` 第 134-165 行

```python
triggered = self.order_simulator.update_positions(current_prices)

for triggered_symbol, (exit_reason, pnl) in triggered.items():
    if triggered_symbol in self.order_simulator.positions:   # <-- 检查仓位是否还在
        continue

    position = None
    for pos in list(self.order_simulator.positions.values()):  # <-- 又在已关闭的仓位里找
        if pos.symbol == triggered_symbol:
            position = pos
            break

    if position:  # <-- position 永远是 None
        # ...创建 TradeRecord...  <-- 永远不会执行
```

**问题分析**:
- `update_positions()` 触发 SL/TP/清算后, 内部调用 `close_position()`, 该方法通过 `self.positions.pop(symbol)` **已经把仓位从 dict 中移除**了
- 第 135 行检查 `triggered_symbol in self.order_simulator.positions` -- 由于仓位已移除, 这里为 `False`, 所以 `continue` 不会执行 (这没问题)
- 但第 139-142 行又在 `self.order_simulator.positions` 中搜索该 symbol -- **仓位已经被 pop 了, 所以永远找不到, `position` 永远为 `None`**
- 结果: **所有 SL/TP/清算触发的交易都不会被记录到 `PerformanceAnalyzer`**, `trades_executed` 计数永远为 0

**影响**: 回测只能统计到 `_close_remaining_positions()` 在末尾关闭的残留仓位, 绩效指标完全失真。

---

### BUG-2: [P0] Position 的 `entry_time` 使用 `datetime.now()` 而非回测时间

**文件**: `backtesting/order_simulator.py` 第 64-68 行

```python
class Position:
    ...
    entry_time: Optional[datetime] = None

    def __post_init__(self):
        if self.entry_time is None:
            self.entry_time = datetime.now()  # <-- 回测中用的是真实系统时间
```

**问题分析**: `BacktestEngine.run_backtest()` 调用 `open_position()` 时没传 `entry_time`, 导致所有仓位的 `entry_time` 为**运行回测时的真实系统时间**, 而非回测数据中的历史时间。

**影响**: `hold_duration_seconds` 计算完全错误 (拿 `current_date (历史)` 减 `entry_time (真实)` 结果为负数或极大值), Calmar 比率、平均持仓时间等指标失真。

---

### BUG-3: [P1] `_generate_signal()` 丢弃了 `funding_history` 参数

**文件**: `backtesting/engine.py` 第 316-324 行

```python
def _generate_signal(self, strategy, df, symbol, funding_history=None):
    try:
        if hasattr(strategy, 'analyze'):
            return strategy.analyze(df, symbol)   # <-- funding_history 被完全忽略
        return None
```

**问题分析**:
- `FundingArbitrageStrategy.analyze()` 的签名是 `analyze(df, symbol, funding_history=None)`, 不传 funding_history 则直接 return None
- `main.py:run_backtest()` 第 174 行确实获取了 `funding_history`, 并传给了 `run_backtest()`, 但引擎的 `_generate_signal()` 调用策略时没有转发
- 同样, `MarketMakingStrategy`, `OrderFlowImbalanceStrategy`, `VWAPReversionStrategy`, `SupportResistanceBounceStrategy` 都有额外参数 (`orderbook`, `current_inventory`, `current_timestamp`), 也全部没传

**影响**: **FundingArbitrageStrategy 在回测中永远产出 0 信号**; 其他需要 orderbook 的策略回测时只能依赖 K 线数据, 部分过滤条件无法工作。

---

## 二、逻辑缺陷 (4 个)

### 缺陷-1: [P1] `get_equity()` 没有加回持仓占用的保证金

**文件**: `backtesting/order_simulator.py` 第 246-258 行

```python
def get_equity(self, current_prices):
    equity = self.balance   # <-- balance 已扣除 margin
    for symbol, position in self.positions.items():
        # 只加了 unrealized PnL, 没加回被锁定的 margin
        equity += unrealized
    return equity
```

当前逻辑: `equity = (balance - margin_frozen) + unrealized_pnl`, 正确应该是 `equity = balance + margin_frozen + unrealized_pnl`。由于 `open_position` 时 `balance -= margin`, 所以这里 equity = 可用余额 + 浮盈, **少算了锁定的保证金**。

**影响**: 权益曲线在持仓期间偏低, 导致 Sharpe/Sortino/MaxDrawdown 等指标有偏差。

---

### 缺陷-2: [P1] PnL 未体现杠杆放大效果

**文件**: `backtesting/engine.py` 第 352-358 行, `backtesting/order_simulator.py` 第 177-180 行

```python
# close_position() 和 _close_remaining_positions() 中:
if position.side == PositionSide.LONG:
    pnl = (exit_price - position.entry_price) * position.quantity
```

在永续合约中, PnL 应为 `price_diff * quantity`, 其中 `quantity` 代表合约数量。但 `_calculate_position_size()` 返回的 quantity 计算方式为:

```python
position_value = risk_amount / stop_distance
quantity = position_value / entry_price
# 然后 leverage_adjustment = min(1.0, 20 / leverage)
# quantity *= leverage_adjustment  --> 杠杆越高, 仓位越小
```

这意味着高杠杆反而导致更小的仓位, **杠杆对 PnL 没有放大效果**, 与实际永续合约行为不一致。

---

### 缺陷-3: [P3] ROI 计算冗余, `total_pnl_percentage` 未赋值

**文件**: `backtesting/performance.py` 第 106 行

```python
metrics.roi = ((self.initial_capital + metrics.total_pnl - self.initial_capital) / self.initial_capital) * 100
```

- `initial_capital + total_pnl - initial_capital` 化简后就是 `total_pnl / initial_capital * 100`, 写法冗余
- `PerformanceMetrics.total_pnl_percentage` 字段始终为默认值 0 (从未被赋值)

---

### 缺陷-4: [P2] 回测只覆盖 5 种策略, 遗漏 4 种

**文件**: `main.py` 第 127-133 行

```python
strategies = [
    BreakoutScalpingStrategy(leverage=30),
    MomentumReversalStrategy(leverage=35),
    FundingArbitrageStrategy(leverage=20),
    LiquidationCascadeStrategy(leverage=45),
    MarketMakingStrategy(leverage=20)
]
```

项目共有 9 种策略 (含 BacktestStrategy), 但 `run_backtest()` 只注册了 5 种, 遗漏了:
- `OrderFlowImbalanceStrategy`
- `VWAPReversionStrategy`
- `SupportResistanceBounceStrategy`
- `BacktestStrategy` (专为回测设计, 反而没被使用)

---

## 三、接口不兼容 (策略签名差异)

| 策略 | `analyze()` 签名 | 回测引擎是否适配 |
|------|-----------------|----------------|
| BreakoutScalping | `(df, symbol)` | 兼容 |
| MomentumReversal | `(df, symbol)` | 兼容 |
| LiquidationCascade | `(df, symbol)` | 兼容 |
| BacktestStrategy | `(df, symbol)` | 兼容 |
| **FundingArbitrage** | `(df, symbol, funding_history=)` | **不兼容** - funding_history 未传 |
| **MarketMaking** | `(df, symbol, current_inventory=, funding_history=)` | **部分兼容** - 额外参数未传 |
| **OrderFlowImbalance** | `(df, symbol, ..., orderbook=, current_timestamp=)` | **不兼容** - orderbook 未传 |
| **VWAPReversion** | `(df, symbol, current_inventory=, funding_history=)` | **部分兼容** |
| **SupportResistanceBounce** | `(df, symbol, ..., funding_history=, current_timestamp=)` | **部分兼容** |

---

## 四、缺失功能

| 缺失项 | 说明 |
|--------|------|
| **无离线数据支持** | 回测必须实时从 AsterDEX API 拉取数据, 无法使用本地 CSV/Parquet 数据 |
| **无 Orderbook 回放** | 需要 orderbook 的策略在回测中无数据源, 永远跳过 |
| **无资金费率模拟结算** | `OrderSimulator` 定义了 `funding_rate`/`funding_interval_hours` 但 `update_positions()` **没有实际执行资金费率扣除** |
| **无开仓手续费** | 开仓时 `open_position()` 只扣除保证金, **未扣除 taker fee**, 仅关仓扣了一次 |
| **无 High/Low 穿透检测** | SL/TP 检测只用 `close` 价比较, 实际应用 K 线的 `high`/`low` 检测是否触及, 可能漏触发 |
| **无多币种并行** | 引擎一次只跑一个 symbol, `run_multi_strategy_backtest` 也只支持单 symbol 多策略 |
| **无结果可视化** | 没有图表输出功能 (equity curve、drawdown chart 等) |

---

## 五、问题严重程度分级总览

| 级别 | 问题 | 影响 |
|------|------|------|
| **P0 严重** | BUG-1: SL/TP 触发的交易不记录 | 绩效数据完全不可信 |
| **P0 严重** | BUG-2: entry_time 用真实时间 | 持仓时长指标全部错误 |
| **P1 重要** | BUG-3: funding_history 未透传 | FundingArbitrage 策略无法回测 |
| **P1 重要** | 缺陷-1: equity 计算少算保证金 | 风险指标有偏差 |
| **P1 重要** | 缺陷-2: PnL 未体现杠杆放大 | 收益计算可能与预期不符 |
| **P2 一般** | 缺陷-4: 只覆盖 5/9 种策略 | 功能不完整 |
| **P2 一般** | 无离线数据/无 orderbook 回放 | 适用场景受限 |
| **P3 优化** | 缺陷-3: ROI 写法冗余 | 代码可读性 |
| **P3 优化** | 缺少开仓手续费/资金费率结算 | 回测精度偏乐观 |

---

## 六、总结

回测模块的框架设计较为完整 (引擎-模拟器-分析器三层架构合理), 但存在 **3 个严重 BUG** 导致当前回测结果不可信赖:

1. **最致命**: BUG-1 (SL/TP 触发后交易不记录) -- 回测报告中大部分交易数据缺失
2. **次致命**: BUG-2 (entry_time 错误) -- 所有时间相关指标失真
3. **功能缺失**: BUG-3 (参数未透传) -- 部分策略在回测中完全无法工作

需要优先修复 P0/P1 级问题后, 回测功能才能产出有参考价值的结果。
