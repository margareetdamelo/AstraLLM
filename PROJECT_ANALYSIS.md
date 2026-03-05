# AstraLLM 项目功能分析清单

> **项目定位**: 专为 AsterDEX 打造的机构级 AI 自动化交易平台
> **技术栈**: Python 3 + FastAPI + SQLite + Web3.py + Pandas/NumPy
> **目标交易所**: AsterDEX (去中心化永续合约交易所)

---

## 一、项目整体架构

```
AstraLLM/
├── main.py                    # 主入口 (支持 live / dry-run / backtest 三种模式)
├── run_bot.py                 # 快速启动实盘
├── run_api.py                 # 启动 REST API 服务
├── run_backtest.py            # 快速启动回测
├── demo_dashboard.py          # 模拟数据 Dashboard 演示
├── config/
│   └── config.py              # 配置中心 (Pydantic Settings, .env)
├── core/
│   ├── aster_client.py        # AsterDEX API 客户端 (期货 + 现货)
│   ├── bot_state.py           # SQLite 持久化状态管理
│   ├── risk_manager.py        # 风险管理系统
│   ├── strategy_selector.py   # 动态策略选择器
│   └── market_regime.py       # 市场状态检测系统
├── bot/
│   └── trading_bot.py         # 交易机器人主类
├── strategies/
│   ├── base_strategy.py       # 策略基类
│   ├── breakout_scalping.py   # 突破剥头皮策略
│   ├── momentum_reversal.py   # 动量反转策略
│   ├── funding_arbitrage.py   # 资金费率套利策略
│   ├── liquidation_cascade.py # 清算级联策略
│   ├── market_making.py       # 做市策略
│   ├── order_flow_imbalance.py# 订单流失衡策略
│   ├── vwap_reversion.py      # VWAP 均值回归策略
│   ├── support_resistance_bounce.py # 支撑阻力反弹策略
│   ├── liquidity_waterfall.py # 流动性瀑布策略
│   └── backtest_strategy.py   # 回测专用简化策略
├── backtesting/
│   ├── engine.py              # 回测引擎
│   ├── performance.py         # 绩效分析器
│   └── order_simulator.py     # 订单模拟器
├── api/
│   └── main.py                # FastAPI REST API 服务
└── dashboard/                 # Dashboard 前端 (HTML)
```

---

## 二、核心模块功能清单

### 2.1 交易机器人 (`bot/trading_bot.py`)

| 功能 | 描述 | 代码逻辑 |
|------|------|---------|
| **多策略初始化** | 根据配置开关初始化 8 种策略实例 | `_init_strategies()`: 检查 `settings.enable_xxx` 开关,仅加载启用的策略 |
| **实盘/Dry-Run 双模式** | 支持真实下单和模拟下单两种模式 | `dry_run=True` 时所有下单操作只打印日志不实际执行 |
| **动态策略选择** | 自动根据市场状态选择最优策略 | `use_dynamic_selector=True` 时,每次迭代由 `StrategySelector` 评分选择 |
| **市场数据获取** | 从 AsterDEX 拉取 K 线数据 | `get_market_data()`: 调用 API 获取 OHLCV, 返回 DataFrame |
| **信号执行** | 收到策略信号后执行开仓全流程 | `execute_signal()`: 设杠杆 -> 市价开仓 -> 下止损单 -> 下止盈单 |
| **持仓同步** | 启动时从交易所同步已有持仓 | `sync_positions_from_exchange()`: 恢复 SL/TP 订单 ID |
| **孤儿订单清理** | 清理无对应持仓的止损/止盈挂单 | `cleanup_orphan_orders()`: 遍历所有挂单,取消无持仓关联的 SL/TP 单 |
| **持仓检查与闭合** | 定期检测持仓状态,自动处理闭合事件 | `check_positions()`: 对比交易所持仓和本地跟踪,检测触发的 SL/TP |
| **余额跟踪初始化** | 首次运行记录初始余额到 DB | `_init_balance_tracking()`: 从 Aster API 获取真实余额并持久化 |
| **循环迭代** | 按固定间隔执行分析-检查-交易循环 | `start()`: while 循环, 每 60 秒执行 `run_iteration()` |

**数据示例 - 信号执行流程:**
```python
signal = {
    'action': 'LONG',           # 方向: LONG / SHORT
    'entry_price': 67500.0,     # 入场价格
    'stop_loss': 66825.0,       # 止损价 (约 -1%)
    'take_profit': 68850.0,     # 止盈价 (约 +2%)
    'leverage': 20,             # 杠杆倍数
    'confidence': 0.78,         # 策略置信度 0~1
    'reason': 'Breakout with vol spike 3.2x, RSI 62'  # 信号原因
}
```

---

### 2.2 AsterDEX API 客户端 (`core/aster_client.py`)

#### 2.2.1 期货客户端 `AsterFuturesClient`

| 功能分类 | API 端点 | 描述 |
|---------|---------|------|
| **认证** | Web3 以太坊签名 | 使用私钥 + ABI 编码 + Keccak 哈希 + EIP-191 签名 |
| **交易所信息** | `GET /fapi/v1/exchangeInfo` | 获取交易规则、精度信息 (LOT_SIZE) |
| **深度数据** | `GET /fapi/v1/depth` | 获取买卖盘挂单深度 |
| **最新价格** | `GET /fapi/v1/ticker/price` | 获取单个或全部交易对价格 |
| **24h 统计** | `GET /fapi/v1/ticker/24hr` | 获取 24 小时涨跌、成交量 |
| **K 线数据** | `GET /fapi/v1/klines` | 获取历史 K 线 (1m/5m/15m/1h...) |
| **资金费率** | `GET /fapi/v1/fundingRate` | 获取历史资金费率 |
| **下单** | `POST /fapi/v3/order` | 创建 MARKET / LIMIT / STOP_MARKET / TAKE_PROFIT_MARKET 订单 |
| **撤单** | `DELETE /fapi/v3/order` | 取消指定订单 |
| **批量撤单** | `DELETE /fapi/v3/allOpenOrders` | 取消指定币对所有挂单 |
| **查询订单** | `GET /fapi/v3/order` | 查询订单状态 |
| **挂单列表** | `GET /fapi/v3/openOrders` | 获取所有未成交订单 |
| **账户信息** | `GET /fapi/v3/account` | 获取总钱包余额、维持保证金等 |
| **余额查询** | `GET /fapi/v3/balance` | 获取账户余额 |
| **持仓查询** | `GET /fapi/v3/positionRisk` | 获取当前持仓、强平价等 |
| **调整杠杆** | `POST /fapi/v3/leverage` | 修改合约杠杆 |
| **保证金模式** | `POST /fapi/v3/marginType` | 切换逐仓/全仓模式 |
| **收入记录** | `GET /fapi/v3/income` | 获取收入历史 |
| **成交记录** | `GET /fapi/v3/userTrades` | 获取账户成交明细 |

**数据示例 - 精度缓存:**
```python
symbol_precision = {
    'BTCUSDT': 3,   # BTC 数量精度 3 位 (如 0.001)
    'ETHUSDT': 4,   # ETH 数量精度 4 位 (如 0.0001)
}
```

**数据示例 - 签名流程:**
```
1. 参数 JSON: {"quantity":"0.001","side":"BUY","symbol":"BTCUSDT","type":"MARKET"}
2. ABI 编码: encode(['string','address','address','uint256'], [json, user, signer, nonce])
3. Keccak 哈希: 0xabc123...
4. EIP-191 签名: 0xdef456... (65 bytes)
```

#### 2.2.2 现货客户端 `AsterSpotClient`

| 功能 | 描述 |
|------|------|
| 交易所信息 | 获取现货交易对信息 |
| 深度/成交/K线 | 现货市场数据 |
| 下单/撤单 | 现货订单管理 |
| 账户信息 | 现货账户余额和交易历史 |

---

### 2.3 风险管理系统 (`core/risk_manager.py`)

| 功能 | 描述 | 逻辑 & 数据示例 |
|------|------|-----------------|
| **开仓检查** | 4 重开仓前安全校验 | 1) 日亏损限制 2) 最大持仓数 3) 重复币种检查 4) 最低资金门槛 |
| **仓位计算** | 基于风险百分比和波动率计算仓位 | `risk_amount = capital * 0.02`, 高波动时乘以 `max(0.5, 1 - vol*2)` 因子 |
| **止损计算** | 基于 ATR 和杠杆动态计算止损 | `stop_distance = ATR * multiplier * leverage_factor`, 剥头皮用 1x ATR, 正常用 1.5x |
| **止盈计算** | 基于风险收益比计算止盈 | `TP = entry + stop_distance * RR_ratio`, 默认 RR = 2.0 |
| **强平价计算** | 计算清算价格 | LONG: `entry * (1 - 1/leverage + 0.005)`, SHORT: `entry * (1 + 1/leverage - 0.005)` |
| **安全检查** | 止损必须在强平价之前 | LONG: `stop_loss > liquidation_price`, SHORT: `stop_loss < liquidation_price` |
| **日亏损限制** | 每日最大亏损自动重置 | `max_daily_loss = 2%`, 超过后当日不再开仓 |
| **资金曲线统计** | 计算胜率、盈亏比、最大回撤等 | 遍历历史交易累积资金曲线, 跟踪 peak 计算 drawdown |
| **交易持久化** | 关仓时自动保存到 SQLite | `close_position()` 调用 `db_manager.save_trade()` |

**数据示例 - 风险参数 (安全模式):**
```python
RiskManager(
    initial_capital=10000.0,   # 初始资金 $10,000
    max_leverage=5,            # 最大杠杆 5x (安全模式下从 50x 降低)
    risk_per_trade=0.005,      # 单笔风险 0.5% (从 2% 降低)
    max_daily_loss=0.02,       # 日最大亏损 2% (从 10% 降低)
    max_open_positions=2       # 最大同时持仓 2 个 (从 5 降低)
)
```

**数据示例 - 仓位计算流程:**
```
资金: $10,000 | 风险比例: 0.5% | 风险金额: $50
入场价: $67,500 | 止损价: $66,825 | 止损距离: 1%
仓位价值: $50 / 0.01 = $5,000
数量: $5,000 / $67,500 = 0.074 BTC
杠杆调整 (20x): 0.074 * min(1.0, 20/20) = 0.074 BTC
```

---

### 2.4 市场状态检测 (`core/market_regime.py`)

| 市场状态 (Regime) | 枚举值 | 典型特征 | 推荐策略 |
|-------------------|--------|---------|---------|
| **高波动趋势** | `high_vol_trending` | 波动率 > 3%, ADX > 40, 动量强 | Breakout Scalping, Momentum Reversal |
| **低波动区间** | `low_vol_ranging` | 波动率 < 1.5%, ADX < 25, 动量弱 | Market Making, VWAP Reversion |
| **动量耗竭** | `momentum_exhaustion` | RSI 极端 (<25 或 >75), 量价背离 | Momentum Reversal, VWAP Reversion |
| **混合** | `mixed` | 各信号矛盾 | Order Flow Imbalance, VWAP Reversion |

**检测信号 (RegimeSignals):**

| 信号 | 计算方式 | 范围 |
|------|---------|------|
| `volatility` | 20 周期收益率标准差 | 0~1 |
| `trend_strength` | ADX 指标 (14 周期) | 0~100 |
| `volume_trend` | 近 5 根 / 近 20 根均量比 | -1~1 |
| `orderbook_imbalance` | (买单深度 - 卖单深度) / 总深度 (前 10 档) | -1~1 |
| `funding_rate` | 当前资金费率 | -0.01~0.01 |
| `funding_trend` | 线性回归斜率 (近 10 期) | -1~1 |
| `rsi` | 14 周期 RSI | 0~100 |
| `price_momentum` | 10 周期 ROC 归一化 | -1~1 |
| `liquidity_score` | 成交量比 + 订单簿深度综合 | 0~1 |

**数据示例 - 状态检测评分:**
```
当前市场信号:
  volatility: 0.035 (高于 3% 阈值)  -> HIGH_VOL_TRENDING +3.0
  trend_strength: 52 (高于 40 阈值) -> HIGH_VOL_TRENDING +2.5
  price_momentum: 0.6              -> HIGH_VOL_TRENDING +2.0
  volume_trend: 0.4                -> HIGH_VOL_TRENDING +1.5

评分: HIGH_VOL_TRENDING=9.0, LOW_VOL=1.0, EXHAUSTION=2.5, MIXED=0.5
置信度: 9.0 / 13.0 = 0.69
结果: HIGH_VOL_TRENDING (69%)
```

---

### 2.5 动态策略选择器 (`core/strategy_selector.py`)

| 功能 | 描述 |
|------|------|
| **策略评分** | `score = regime_match * 0.7 + performance * 0.3` |
| **自动降级** | 10 笔交易后胜率低于 35% 自动禁用策略 |
| **自动恢复** | 被禁用策略胜率回升到 45% 以上自动恢复 |
| **级联尝试** | 最优策略无信号时,按评分依次尝试下一个策略 |
| **绩效跟踪** | 维护每个策略近 20 笔交易的滑动窗口统计 |

**数据示例 - 策略选择过程:**
```
市场状态: HIGH_VOL_TRENDING (置信度 69%)
推荐策略优先级: [Breakout Scalping, Momentum Reversal, S/R Bounce, Order Flow]

策略评分:
  Breakout Scalping:  regime_score=1.0*0.69, perf_score=0.7 -> 综合=0.69
  Momentum Reversal:  regime_score=0.8*0.69, perf_score=0.5 -> 综合=0.54
  VWAP Reversion:     regime_score=0.2*0.69, perf_score=0.6 -> 综合=0.28

选择: Breakout Scalping (0.69)
-> 分析信号 -> 有信号则执行
-> 无信号 -> 尝试 Momentum Reversal...
```

---

### 2.6 持久化状态管理 (`core/bot_state.py`)

#### SQLite 数据表:

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `bot_state` | KV 存储 (初始余额、首次启动时间等) | key, value, updated_at |
| `trades` | 所有已关闭的交易记录 | symbol, strategy, side, entry_price, exit_price, pnl, leverage... |
| `positions_history` | 持仓快照 | symbol, entry_price, unrealized_pnl, snapshot_time |
| `market_conditions` | 交易时的市场状况 | price, volatility, rsi, trend_strength, event_type |
| `strategy_performance` | 按策略按日聚合统计 | strategy, date, total_trades, win_rate, total_pnl |
| `signals` | 所有生成的信号 (含未执行的) | strategy, action, confidence, executed, rejection_reason |

**数据示例 - trades 表记录:**
```sql
INSERT INTO trades VALUES (
    aster_trade_id = '123456',
    symbol = 'BTCUSDT',
    strategy = 'Breakout Scalping',
    side = 'LONG',
    entry_price = 67500.0,
    exit_price = 68175.0,
    quantity = 0.074,
    leverage = 20,
    pnl = 49.95,
    pnl_percentage = 1.0,
    entry_time = '2025-03-01 14:30:00',
    exit_time = '2025-03-01 15:45:00',
    hold_duration_seconds = 4500,
    stop_loss = 66825.0,
    take_profit = 68850.0,
    exit_reason = 'take_profit'
);
```

**数据示例 - 从 Aster 导入历史交易:**
```python
import_stats = {
    'total_fetched': 200,    # 从交易所拉取 200 条
    'imported': 85,          # 新导入 85 条
    'duplicates': 112,       # 重复跳过 112 条
    'errors': 3              # 错误 3 条
}
```

---

## 三、策略引擎 (9 种策略)

### 3.1 策略基类 (`strategies/base_strategy.py`)

所有策略继承 `BaseStrategy`, 提供公共技术指标计算:

| 公共方法 | 描述 | 返回值 |
|---------|------|--------|
| `calculate_atr(df, period=14)` | 平均真实波幅 | Series |
| `calculate_rsi(df, period=14)` | 相对强弱指数 | Series |
| `calculate_ema(df, period)` | 指数移动平均 | Series |
| `calculate_sma(df, period)` | 简单移动平均 | Series |
| `calculate_bollinger_bands(df, period=20, std=2)` | 布林带 | (upper, middle, lower) |
| `calculate_macd(df)` | MACD (12,26,9) | (macd, signal, histogram) |
| `calculate_volatility(df, period=20)` | 波动率 (标准差) | float |
| `analyze(df, symbol)` | 生成交易信号 (抽象方法) | Dict 或 None |

---

### 3.2 突破剥头皮 (`BreakoutScalpingStrategy`)

| 属性 | 值 |
|------|---|
| **策略逻辑** | 检测价格突破布林带 + 成交量放大 + ATR 确认波动, 快速进出 |
| **默认杠杆** | 20x |
| **止损距离** | 1x ATR (紧止损) |
| **风险收益比** | 1.5:1 |

**触发条件:**
1. 当前价格突破布林带上轨 (做多) 或下轨 (做空)
2. 当前成交量 >= 平均成交量的 4 倍 (Volume Spike)
3. ATR% >= 1.5% (波动率足够)
4. RSI 30~70 之间 (排除超买/超卖极端)

**数据示例:**
```python
# 做多信号
{
    'action': 'LONG',
    'entry_price': 67500.0,
    'stop_loss': 67200.0,      # entry - 1x ATR
    'take_profit': 67950.0,    # entry + 1.5x ATR  
    'leverage': 20,
    'confidence': 0.82,
    'reason': 'Breakout above upper BB with vol spike 4.5x, ATR 1.8%'
}
```

---

### 3.3 动量反转 (`MomentumReversalStrategy`)

| 属性 | 值 |
|------|---|
| **策略逻辑** | 检测趋势极端 + 背离信号, 逆势入场捕捉反转 |
| **默认杠杆** | 25x |
| **止损距离** | 1.5x ATR |
| **风险收益比** | 2.0:1 |

**触发条件 (做多反转):**
1. RSI < 25 (超卖)
2. 价格低于布林带下轨 (偏离均值)
3. MACD 柱状图由负转正 (金叉确认)
4. 近 5 根 K 线成交量递增 (抄底资金进场)

**数据示例:**
```python
# 做多反转信号
{
    'action': 'LONG',
    'entry_price': 65800.0,
    'stop_loss': 65200.0,
    'take_profit': 67000.0,
    'leverage': 25,
    'confidence': 0.71,
    'reason': 'Momentum reversal: RSI=22, below lower BB, MACD bullish crossover'
}
```

---

### 3.4 资金费率套利 (`FundingArbitrageStrategy`)

| 属性 | 值 |
|------|---|
| **策略逻辑** | 当资金费率极端时反向开仓, 赚取资金费 + 均值回归收益 |
| **默认杠杆** | 20x |
| **所需数据** | K 线 + 资金费率历史 (funding_history) |

**触发条件:**
1. 当前资金费率绝对值 > 0.02% (极端)
2. 资金费率趋势 (线性回归) 方向与当前费率一致 (持续极端)
3. 价格动量与高费率方向一致 (过度拥挤)
4. RSI 确认不在极端反向区间

**逻辑**: 资金费率为正 -> 多头过度拥挤 -> 做空收取费率; 资金费率为负 -> 空头过度拥挤 -> 做多收取费率

**数据示例:**
```python
# 资金费率历史 (来自交易所)
funding_history = [
    {'fundingRate': '0.00035', 'fundingTime': 1709280000000},  # 正费率持续
    {'fundingRate': '0.00042', 'fundingTime': 1709308800000},  
    {'fundingRate': '0.00051', 'fundingTime': 1709337600000},  # 费率走高
]
# -> 正费率极端 -> 做空信号 (赚资金费 + 预期均值回归)
```

---

### 3.5 做市策略 (`MarketMakingStrategy`)

| 属性 | 值 |
|------|---|
| **策略逻辑** | 在低波动区间市场挂双边单赚价差, 检测最佳入场时机 |
| **默认杠杆** | 15x |
| **适用市场** | 低波动 + 高流动性 |

**触发条件 (做多):**
1. 波动率 < 2% (低波动环境)
2. 价格接近布林带下轨 (相对便宜)
3. RSI 30~50 (不超卖但处于低位)
4. 成交量适中 (不过高也不过低)

**数据示例:**
```python
{
    'action': 'LONG',
    'entry_price': 67300.0,
    'stop_loss': 66960.0,      # 约 -0.5%
    'take_profit': 67640.0,    # 约 +0.5%
    'leverage': 15,
    'confidence': 0.65,
    'reason': 'Market making: low vol 1.2%, near lower BB, RSI 38'
}
```

---

### 3.6 清算级联 (`LiquidationCascadeStrategy`)

| 属性 | 值 |
|------|---|
| **策略逻辑** | 检测大量杠杆仓位即将被清算的连锁效应, 顺势追击 |
| **默认杠杆** | 45x (高杠杆快进快出) |
| **信号源** | 大额成交量 + 价格快速移动 + 订单簿不对称 |

**触发条件:**
1. 成交量 > 平均 5 倍以上 (异常放量)
2. 价格在短时间内快速单方向移动
3. RSI 极端 (< 20 或 > 80)
4. ATR 放大 (波动加剧)

---

### 3.7 订单流失衡 (`OrderFlowImbalanceStrategy`)

| 属性 | 值 |
|------|---|
| **策略逻辑** | 分析订单簿买卖压力失衡, 跟随大单方向入场 |
| **默认杠杆** | 20x |
| **所需数据** | K 线 + 实时订单簿 (orderbook) |

**触发条件 (做多):**
1. 买单深度 / 卖单深度 > 1.5 (买压显著)
2. 趋势方向确认 (EMA 排列)
3. 成交量放大确认
4. 冷却期: 上次交易后至少 15 分钟

**数据示例 - 订单簿分析:**
```python
orderbook = {
    'bids': [[67500, 10.5], [67490, 8.2], ...],  # 总买单 285 BTC
    'asks': [[67510, 3.1], [67520, 4.7], ...],    # 总卖单 120 BTC
}
# imbalance = (285 - 120) / (285 + 120) = 0.407 -> 买压强
```

---

### 3.8 VWAP 均值回归 (`VWAPReversionStrategy`)

| 属性 | 值 |
|------|---|
| **策略逻辑** | 计算 AMM 调整后的 VWAP, 当价格偏离 VWAP 时反向入场 |
| **默认杠杆** | 15x |
| **DEX 特化** | VWAP 计算加入 AMM 滑点因子调整 |

**触发条件 (做多):**
1. 当前价格低于 VWAP (低于加权平均成本)
2. 偏离幅度 > 0.5% (足够的回归空间)
3. RSI < 45 (不处于超买)
4. 成交量未异常放大 (非趋势性下跌)

**VWAP 计算:**
```python
# 标准 VWAP
vwap = cumsum(typical_price * volume) / cumsum(volume)
# AMM 调整: 考虑 DEX 滑点, 对 VWAP 做微调
typical_price = (high + low + close) / 3
```

**数据示例:**
```python
{
    'action': 'LONG',
    'entry_price': 67200.0,
    'stop_loss': 66860.0,
    'take_profit': 67540.0,     # 目标回归到 VWAP
    'leverage': 15,
    'confidence': 0.73,
    'reason': 'VWAP reversion: price 0.8% below VWAP, RSI 38'
}
```

---

### 3.9 支撑阻力反弹 (`SupportResistanceBounceStrategy`)

| 属性 | 值 |
|------|---|
| **策略逻辑** | 自动检测关键支撑/阻力位, 在价格触及后反弹时入场 |
| **默认杠杆** | 20x |
| **核心算法** | 基于近期高低点 Pivot 检测关键价位 |

**触发条件 (做多):**
1. 价格接近已识别的支撑位 (在支撑位 0.3% 范围内)
2. 出现反弹信号 (从低点回升)
3. RSI 30~50 (超卖但开始回升)
4. 成交量放大 (支撑有效的确认)

---

### 3.10 流动性瀑布 (`LiquidityWaterfallStrategy`)

| 属性 | 值 |
|------|---|
| **策略逻辑** | DEX 专属策略, 检测流动性池的大额撤退/注入, 预判价格冲击 |
| **默认杠杆** | 20x |
| **DEX 特化** | 分析 AMM 流动性深度变化 |

---

### 3.11 回测专用策略 (`BacktestStrategy`)

| 属性 | 值 |
|------|---|
| **用途** | 仅用于回测, 放宽过滤条件以产生更多交易信号 |
| **默认杠杆** | 5x |
| **成交量阈值** | 1.5x (生产策略为 4x) |
| **ATR 阈值** | 3% (生产策略为 1.5%) |

---

## 四、回测引擎

### 4.1 回测引擎 (`backtesting/engine.py`)

| 功能 | 描述 |
|------|------|
| **数据预处理** | 计算 returns, log_returns, volatility, ATR |
| **逐 K 线回测** | 遍历历史 K 线, 每根 K 线执行: 更新持仓 -> 检查 SL/TP -> 生成信号 -> 开仓 |
| **滑点模拟** | `slippage = base + volatility * factor`, 范围 [0.01%, 0.1%] |
| **仓位计算** | 与实盘一致的风险百分比仓位计算 |
| **多策略对比** | `run_multi_strategy_backtest()`: 对同一数据跑多个策略, 输出对比 |
| **结果保存** | 输出 JSON 包含 trades, equity_curve, metrics |

**数据示例 - 回测结果:**
```json
{
    "symbol": "BTCUSDT",
    "strategy": "Breakout Scalping",
    "initial_capital": 10000.0,
    "final_capital": 11240.5,
    "signals_generated": 45,
    "trades_executed": 32,
    "metrics": {
        "total_trades": 32,
        "win_rate": 62.5,
        "total_pnl": 1240.5,
        "roi": 12.41,
        "sharpe_ratio": 1.85,
        "max_drawdown": 4.2,
        "profit_factor": 2.1,
        "avg_hold_time_seconds": 3600
    }
}
```

### 4.2 订单模拟器 (`backtesting/order_simulator.py`)

| 功能 | 描述 |
|------|------|
| **仓位管理** | 开/关仓, 跟踪 margin 和 balance |
| **滑点模拟** | 买入加滑点, 卖出减滑点 |
| **手续费** | Maker 0.04%, Taker 0.07% |
| **SL/TP 触发** | 自动检测止损/止盈/强平 |
| **资金费率** | 模拟每 8 小时 0.01% 资金费率 |
| **强平模拟** | 计算并检测强平价触发 |

**数据示例 - 回测配置:**
```python
BacktestConfig(
    initial_capital=10000.0,
    maker_fee=0.0004,               # 0.04%
    taker_fee=0.0007,               # 0.07%
    slippage_base=0.0002,           # 0.02% 基础滑点
    slippage_volatility_factor=0.0001,
    min_slippage=0.0001,            # 0.01%
    max_slippage=0.001,             # 0.1%
    funding_rate=0.0001,            # 0.01%
    funding_interval_hours=8
)
```

### 4.3 绩效分析器 (`backtesting/performance.py`)

| 指标 | 计算方式 |
|------|---------|
| 总交易数 / 胜率 | 盈利笔数 / 总笔数 |
| 盈亏因子 (Profit Factor) | 总盈利 / 总亏损 |
| 夏普比率 (Sharpe Ratio) | `mean(returns) / std(returns) * sqrt(年化因子)` |
| 索提诺比率 (Sortino Ratio) | 仅考虑下行风险的夏普比率 |
| 最大回撤 (Max Drawdown) | 权益从峰值到谷值的最大百分比下降 |
| 卡尔马比率 (Calmar Ratio) | 年化收益 / 最大回撤 |
| 波动率 | 收益率标准差 |
| 平均持仓时间 | 所有交易持仓秒数的均值 |
| 最大连胜/连亏 | 连续盈利/亏损交易的最大次数 |
| **按策略分组统计** | 每个策略独立的胜率、PnL |
| **按日期分组统计** | 每天的交易数、PnL |
| **按币种分组统计** | 每个币种的交易数、PnL |

---

## 五、REST API 服务 (`api/main.py`)

### 5.1 需认证的管理端点 (X-API-Key)

| 端点 | 方法 | 描述 |
|------|------|------|
| `POST /bot/start` | POST | 启动机器人 (指定币对、策略、间隔) |
| `POST /bot/stop` | POST | 停止机器人 |
| `GET /bot/status` | GET | 获取机器人运行状态 + 策略选择器状态 |
| `GET /positions` | GET | 获取所有持仓列表 |
| `GET /positions/{symbol}` | GET | 获取指定币对持仓详情 |
| `DELETE /positions/{symbol}` | DELETE | 手动平仓指定币对 |
| `GET /statistics` | GET | 获取交易统计 (胜率/PnL/回撤) |
| `GET /trades` | GET | 获取交易历史 (最近 N 笔) |
| `GET /market/{symbol}` | GET | 获取指定币对市场数据 |
| `POST /manual-trade` | POST | 手动下单 (指定币对/方向/数量/杠杆/SL/TP) |

### 5.2 无需认证的 Dashboard 端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /` | GET | Dashboard 首页 (HTML) |
| `GET /admin-dashboard` | GET | 管理后台 Dashboard |
| `GET /health` | GET | Docker 健康检查 |
| `GET /dashboard/summary` | GET | 完整的 Dashboard 汇总数据 |
| `GET /dashboard/closed-positions` | GET | 已关闭持仓历史 |
| `GET /api/bot/metrics` | GET | 前端团队用: 全局指标 + 策略模型列表 |
| `GET /api/chart/performance` | GET | 前端团队用: 图表性能数据 (含插值) |
| `GET /api/bot/positions` | GET | 前端团队用: 实时持仓数据 |

### 5.3 `/dashboard/summary` 返回数据结构

```json
{
    "timestamp": "2025-03-04T10:30:00",
    "bot_status": {
        "running": true,
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "dynamic_selector": true,
        "agent_address": "0xabc...",
        "blockchain": "ethereum"
    },
    "statistics": {
        "current_capital": 10245.50,
        "initial_capital": 10000.00,
        "maintenance_margin": 125.30,
        "unrealized_pnl": -12.50,
        "total_pnl": 245.50,
        "roi": 2.46,
        "win_rate": 62.5,
        "total_trades": 48,
        "winning_trades": 30,
        "losing_trades": 18,
        "daily_pnl": 35.20,
        "max_drawdown": 4.2,
        "current_drawdown": 1.1,
        "avg_hold_time_hours": 2.5
    },
    "regime_info": {
        "current_regime": "high_vol_trending",
        "confidence": 0.72,
        "selected_strategy": "Breakout Scalping",
        "regime_distribution": {
            "high_vol_trending": 45,
            "low_vol_ranging": 30,
            "momentum_exhaustion": 15,
            "mixed": 10
        }
    },
    "strategy_performance": {
        "Breakout Scalping": {
            "total_trades": 20,
            "winning_trades": 13,
            "total_pnl": 180.50,
            "win_rate": 65.0
        }
    },
    "open_positions": [...],
    "recent_trades": [...],
    "all_internal_trades": [...]
}
```

---

## 六、配置系统 (`config/config.py`)

| 配置项 | 默认值 (安全模式) | 说明 |
|--------|-----------------|------|
| `default_leverage` | 3 | 默认杠杆 |
| `max_leverage` | 5 | 最大允许杠杆 |
| `risk_per_trade` | 0.005 (0.5%) | 单笔风险比例 |
| `max_daily_loss` | 0.02 (2%) | 日最大亏损 |
| `max_open_positions` | 2 | 最大同时持仓数 |
| `enable_breakout_scalping` | True | 突破剥头皮 |
| `enable_vwap_reversion` | True | VWAP 均值回归 |
| `enable_momentum_reversal` | False | 动量反转 (禁用) |
| `enable_market_making` | False | 做市 (禁用,主要亏损来源) |
| `enable_funding_arbitrage` | False | 资金费率套利 (禁用) |
| `enable_liquidation_cascade` | False | 清算级联 (禁用) |
| `enable_order_flow_imbalance` | False | 订单流失衡 (禁用) |
| `enable_support_resistance` | False | 支撑阻力 (禁用) |
| `backtest_initial_capital` | 10000 | 回测初始资金 |

---

## 七、Demo Dashboard (`demo_dashboard.py`)

| 功能 | 描述 |
|------|------|
| **模拟数据** | 不连接真实交易所, 生成模拟交易和持仓 |
| **自动更新** | 每 15 秒模拟: 10% 概率切换市场状态, 15% 概率产生新交易, 20% 概率开仓 |
| **快速体验** | 无需任何 API 密钥即可启动, 查看 Dashboard 界面效果 |
| **API 兼容** | 提供与生产版相同的 `/dashboard/summary` 端点 |

---

## 八、运行模式总结

| 模式 | 启动命令 | 说明 |
|------|---------|------|
| **实盘交易** | `python main.py --symbols BTCUSDT ETHUSDT` | 真实下单, 需要 .env 配置 |
| **模拟交易** | `python main.py --dry-run --symbols BTCUSDT` | 不下单只打印日志 |
| **历史回测** | `python main.py --backtest --symbols BTCUSDT` | 使用历史数据回测 |
| **API 服务** | `python run_api.py` | 启动 REST API + Dashboard |
| **Demo** | `python demo_dashboard.py` | 模拟数据 Dashboard 演示 |

---

## 九、数据流整体链路

```
AsterDEX API (K线/深度/资金费率/账户)
        │
        ▼
  AsterFuturesClient (HTTP + Web3 签名)
        │
        ▼
  TradingBot.get_market_data()  →  DataFrame [timestamp, O, H, L, C, V]
        │
        ├──→ MarketRegimeDetector  →  detect regime (4 类)
        │         │
        │         ▼
        ├──→ StrategySelector  →  score & rank strategies
        │         │
        │         ▼
        ├──→ Strategy.analyze(df, symbol)  →  signal {action, entry, SL, TP, leverage, confidence}
        │         │
        │         ▼
        ├──→ RiskManager.can_open_position()  →  4 重安全检查
        │         │
        │         ▼
        ├──→ RiskManager.calculate_position_size()  →  quantity
        │         │
        │         ▼
        ├──→ TradingBot.execute_signal()  →  下单 (Market + SL + TP)
        │         │
        │         ▼
        └──→ BotStateManager.save_trade()  →  SQLite 持久化
                  │
                  ▼
            FastAPI /dashboard/summary  →  前端 Dashboard 展示
```
