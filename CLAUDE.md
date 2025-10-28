# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个**纯盈利导向**的 Hyperliquid 高频交易系统，专注于通过**信号强度驱动**的策略实现可持续盈利。

**核心理念**：
- **IOC 优先**：确定性成交优于手续费优化
- **信号驱动**：Alpha（方向性收益）必须占 PnL 的 70% 以上
- **验证优先**：先证明 IOC-only 能盈利，再谈执行优化

**项目状态**：Week 1 IOC-only 基线开发中

---

## 核心原则

### 1. 盈利模型

```
E[trade] = p·g - (1-p)·l - fee - slip - impact
```

**关键指标**：
- **IC（信号质量）**：≥ 0.03（Spearman 相关性）
- **Alpha 占比**：≥ 70%（方向性收益主导）
- **成交成本**：Fee + Slip ≤ 25%
- **胜率**：≥ 60%（扣除成本后）
- **盈亏比**：≥ 1.5

### 2. 执行策略分级

| 置信度 | |Score| 范围 | 执行方式 | Week 1 状态 |
|--------|-------------|----------|-------------|
| **高** | > θ₁ | IOC/贴盘口限价 | ✅ 实现 |
| **中** | θ₂ ~ θ₁ | 浅被动（Week 2） | ⏳ 待实现 |
| **低** | ≤ θ₂ | 不交易 | ✅ 实现 |

### 3. 风控准则

**硬熔断（立即停机）**：
- 单笔亏损 > 0.8% 净值
- 日回撤 > 5%
- API 异常/预言机异常

**动态调整（Week 2）**：
- 高波动 → 放大止损/止盈
- 低流动性 → 只用 IOC、减小尺寸
- Funding 极端 → 禁逆势 carry

---

## 开发环境设置

### 环境要求

- **Python**：3.11+
- **包管理器**：UV（快速依赖解析）
- **操作系统**：macOS/Linux（推荐）

### 初始化环境

```bash
# 1. 创建虚拟环境
uv venv --python 3.11
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# 2. 安装依赖
uv pip install -e ".[dev]"

# 3. 验证安装
python --version  # 应显示 3.11+
pytest --version
```

### 环境变量配置

创建 `.env` 文件（**不要提交到 Git**）：

```bash
# Hyperliquid API 配置
HYPERLIQUID_API_KEY=your_api_key
HYPERLIQUID_API_SECRET=your_api_secret
HYPERLIQUID_WALLET_ADDRESS=your_wallet_address

# 环境选择
ENVIRONMENT=testnet  # testnet | mainnet | development

# 风控参数
MAX_SINGLE_LOSS_PCT=0.008  # 0.8%
MAX_DAILY_DRAWDOWN_PCT=0.05  # 5%
INITIAL_NAV=100000

# 信号参数
THETA_1=0.5  # 高置信度阈值
THETA_2=0.2  # 中置信度阈值

# 日志级别
LOG_LEVEL=INFO  # DEBUG | INFO | WARNING | ERROR
```

---

## Week 1 核心命令

### 开发工作流

```bash
# 代码质量检查
make lint          # Ruff 代码检查
make format        # Black 代码格式化
make typecheck     # Mypy 类型检查
make check         # 运行所有质量检查

# 测试
make test          # 运行所有测试
make test-cov      # 测试 + 覆盖率报告
make test-unit     # 仅单元测试
make test-integration  # 仅集成测试

# 提交前检查
make pre-commit    # format + check + test
```

### 数据获取与验证

```bash
# 1. 获取历史数据（用于信号验证）
python scripts/fetch_historical_data.py \
    --symbol BTC-USD \
    --days 30 \
    --output data/raw/btc_30d.parquet

# 2. 信号前瞻性验证
python scripts/validate_signals.py \
    --data data/raw/btc_30d.parquet \
    --config config/signals.yaml \
    --output docs/signal_validation_report.html

# 3. 回测 IOC-only 基线
python scripts/run_week1_baseline.py \
    --data data/raw/btc_30d.parquet \
    --config config/week1_ioc.yaml \
    --output docs/baseline_performance.html
```

### 实盘运行（testnet）

```bash
# 1. 启动交易系统（testnet）
python -m src.main \
    --config config/week1_ioc.yaml \
    --env testnet \
    --dry-run  # 先干跑验证

# 2. 正式运行（testnet）
python -m src.main \
    --config config/week1_ioc.yaml \
    --env testnet

# 3. 查看实时日志
tail -f logs/trading_$(date +%Y%m%d).log
```

---

## 项目架构

### 目录结构

```
hype/
├── src/                          # 核心代码
│   ├── core/                     # 基础设施
│   │   ├── data_feed.py          # WebSocket 数据接入
│   │   ├── orderbook.py          # 订单簿重建
│   │   └── types.py              # 核心数据类型
│   ├── signals/                  # 信号引擎
│   │   ├── base.py               # 信号基类
│   │   ├── obi.py                # Order Book Imbalance
│   │   ├── microprice.py         # Microprice 信号
│   │   └── impact.py             # 冲击信号
│   ├── execution/                # 执行引擎
│   │   ├── ioc_executor.py       # IOC 执行器（Week 1）
│   │   ├── order_manager.py      # 订单状态管理
│   │   └── slippage_estimator.py # 滑点估计
│   ├── risk/                     # 风控模块
│   │   ├── hard_limits.py        # 硬熔断（Week 1）
│   │   ├── position_manager.py   # 仓位管理
│   │   └── drawdown_tracker.py   # 回撤追踪
│   ├── analytics/                # 分析模块
│   │   ├── pnl_attribution.py    # PnL 归因
│   │   ├── signal_validation.py  # 信号前瞻性检验
│   │   ├── future_return_tracker.py  # 未来收益跟踪（含价格历史存储）
│   │   └── metrics.py            # 性能指标
│   └── hyperliquid/              # Hyperliquid 集成
│       ├── api_client.py         # REST API 客户端
│       └── websocket_client.py   # WebSocket 客户端
├── tests/                        # 测试代码
│   ├── unit/                     # 单元测试
│   ├── integration/              # 集成测试
│   └── fixtures/                 # 测试数据
├── config/                       # 配置文件
│   ├── base.yaml                 # 基础配置
│   ├── week1_ioc.yaml            # Week 1 IOC-only 配置
│   └── signals.yaml              # 信号参数配置
├── scripts/                      # 工具脚本
│   ├── fetch_historical_data.py  # 历史数据获取
│   ├── validate_signals.py       # 信号验证
│   └── run_week1_baseline.py     # Week 1 基线测试
├── data/                         # 数据目录
│   ├── raw/                      # 原始市场数据
│   └── processed/                # 处理后的数据
├── docs/                         # 文档
│   ├── strategy_review.md        # 策略评审方案
│   └── architecture_design.md    # 架构设计文档
├── logs/                         # 日志目录
├── CLAUDE.md                     # 开发指南（本文件）
├── pyproject.toml                # 项目配置
├── Makefile                      # 常用命令
└── .env.example                  # 环境变量模板
```

### 核心模块说明

#### 1. 数据层（src/core/）

**职责**：实时数据接入与订单簿维护

**关键文件**：
- `data_feed.py`：WebSocket 连接管理
- `orderbook.py`：L2 订单簿重建
- `types.py`：数据模型定义

**性能要求**：
- WebSocket 消息处理 < 5ms
- 订单簿更新延迟 < 5ms

#### 2. 信号层（src/signals/）

**职责**：生成交易信号并聚合评分

**Week 1 实现的信号**：
1. **OBI（Order Book Imbalance）**
   ```python
   OBI = (BidVolume - AskVolume) / (BidVolume + AskVolume)
   ```

2. **Microprice**
   ```python
   Microprice = (BestAsk × BidSize + BestBid × AskSize) / (BidSize + AskSize)
   ```

3. **Impact（冲击信号）**
   - 检测大单冲击
   - 识别价格异常波动

**质量标准**：
- IC（Spearman）≥ 0.03
- 分层收益（Top vs Bottom）> 8 bps
- 跨时段/品种稳健

#### 3. 执行层（src/execution/）

**职责**：订单执行与成交管理

**Week 1 策略**：
- **高置信度**：IOC/贴盘口限价
- **低置信度**：跳过交易

**关键指标**：
- 订单提交延迟 < 50ms（含网络）
- IOC 成交率 ≥ 95%
- 滑点估计误差 < 20%

#### 4. 风控层（src/risk/）

**职责**：风险管理与仓位控制

**Week 1 硬熔断**：
- 单笔亏损 > 0.8% 净值 → 停机
- 日回撤 > 5% → 停机
- API 异常 → 停机

#### 5. 分析层（src/analytics/）

**职责**：性能分析与 PnL 归因

**核心组件**：
- `future_return_tracker.py` - 未来收益跟踪器（含价格历史存储）
- `pnl_attribution.py` - PnL 归因分析
- `signal_validation.py` - 信号前瞻性检验
- `metrics.py` - 性能指标计算

**FutureReturnTracker 核心功能**（新增）：
1. **实时价格历史存储**：滚动保留 1 小时价格数据（< 4 MB 内存）
2. **T+n 未来收益计算**：自动计算信号的 T+10 分钟方向性收益
3. **测试后回填 IC**：测试结束后使用存储的价格计算多窗口 IC（T+5, T+10, T+15, T+30）
4. **自动清理机制**：超过窗口的旧价格自动清理，保持内存可控

**使用示例**：
```python
# 在测试结束时自动回填多窗口 IC
backfill_results = tracker.backfill_future_returns([5, 10, 15, 30])
# 返回：{signal_id: {window_minutes: future_return}}
```

**PnL 分解公式**：
```
Total PnL = Alpha + Rebate - Fee - Slippage - Impact
```

**健康标准**：
- Alpha 占比 ≥ 70%
- Fee + Slip ≤ 25%
- Rebate ≤ 10%（Week 1 为 0）

---

## 关键验证标准

### Week 1 结束时的必达指标

#### 1. 信号质量 ✓
- [ ] 至少 1 个信号 IC ≥ 0.03
- [ ] 分层收益 > 成交成本（8 bps）
- [ ] 跨时段稳健性验证通过
- [ ] 跨品种稳健性验证通过

#### 2. IOC-only 盈利性 ✓
- [ ] 去除 maker 后 E[trade] > 0
- [ ] 胜率 ≥ 60%（扣除成本）
- [ ] 盈亏比 ≥ 1.5
- [ ] 夏普比率 > 1.0

#### 3. PnL 结构健康 ✓
- [ ] Alpha 占比 ≥ 70%
- [ ] Fee + Slip ≤ 25%
- [ ] 成交成本与预估偏差 < 20%

#### 4. 系统稳定性 ✓
- [ ] 24h 运行无宕机
- [ ] API 成功率 ≥ 99.5%
- [ ] 端到端延迟 p99 < 150ms
- [ ] WebSocket 连接稳定性 99.9%

### 验证流程

```bash
# 1. 信号验证
make validate-signals

# 2. 回测验证
make backtest-week1

# 3. Testnet 验证（24h）
make run-testnet-24h

# 4. 生成验证报告
make generate-report
```

---

## 性能优化指南

### 延迟优化

**目标**：端到端延迟 < 100ms

**优化点**：
1. **WebSocket 处理**：使用 asyncio，避免阻塞
2. **订单簿更新**：增量更新，避免全量重建
3. **信号计算**：缓存中间结果，避免重复计算
4. **订单提交**：连接池复用，减少握手时间

**监控工具**：
```python
from src.analytics.metrics import latency_tracker

@latency_tracker("signal_calculation")
def calculate_signal(market_data):
    # 信号计算逻辑
    pass
```

### 内存优化

**目标**：内存使用 < 2GB

**优化点**：
1. 使用 `polars` 替代 `pandas` 处理高频数据
2. 限制历史数据窗口大小
3. 定期清理过期数据

---

## 常见问题与解决方案

### 1. 信号 IC 不达标

**症状**：IC < 0.03 或不稳定

**排查步骤**：
1. 检查数据质量（是否有异常值/缺失）
2. 调整信号参数（窗口大小、档位数量）
3. 检查延迟（是否存在前瞻偏差）
4. 分时段分析（找出失效时段）

**工具**：
```bash
python scripts/diagnose_signal.py --signal obi --data data/raw/btc_30d.parquet
```

### 2. 滑点超预期

**症状**：实际滑点 > 预估滑点 20%

**排查步骤**：
1. 检查订单尺寸（是否过大导致冲击）
2. 检查流动性（是否在低流动性时段交易）
3. 检查延迟（是否订单提交过慢）

**解决方案**：
- 减小订单尺寸
- 避开低流动性时段
- 优化网络连接

### 3. API 限流

**症状**：API 返回 429 错误

**解决方案**：
1. 降低请求频率
2. 使用 WebSocket 替代轮询
3. 实现请求队列和限流

```python
from src.hyperliquid.api_client import RateLimiter

limiter = RateLimiter(max_requests=100, window_seconds=60)
```

### 4. 风控误触发

**症状**：正常交易被硬熔断拦截

**排查步骤**：
1. 查看日志确认触发原因
2. 检查阈值设置是否合理
3. 分析历史数据验证阈值

**调整建议**：
- 单笔亏损阈值：0.8% → 1.0%
- 日回撤阈值：5% → 6%（需谨慎）

---

## 代码规范

### 命名约定

- **文件名**：`snake_case.py`
- **类名**：`PascalCase`
- **函数/变量**：`snake_case`
- **常量**：`UPPER_SNAKE_CASE`

### 类型注解

**必须使用类型注解**：

```python
from decimal import Decimal
from typing import Optional, List

def calculate_size(
    signal_score: float,
    position: Position,
    nav: Decimal
) -> Optional[Decimal]:
    """计算订单尺寸"""
    if abs(signal_score) < THRESHOLD:
        return None

    return min(
        abs(signal_score) * nav * Decimal('0.01'),
        MAX_POSITION_SIZE
    )
```

### 异常处理

**必须处理所有网络/IO 异常**：

```python
import httpx
from src.core.exceptions import APIError

async def fetch_data(url: str) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=5.0)
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException:
        raise APIError("API request timeout")
    except httpx.HTTPStatusError as e:
        raise APIError(f"API error: {e.response.status_code}")
```

### 日志记录

#### 日志系统架构

项目使用 **structlog** 实现生产级日志系统，支持：
- **文件日志**：JSON 格式，按日轮转，保留 30 天
- **控制台日志**：彩色格式，便于开发调试
- **审计日志**：关键操作独立记录（订单执行、风控触发）

#### 日志配置

日志系统在 `src/main.py` 启动时自动初始化：

```python
from src.core.logging import setup_logging

# 配置日志系统（从环境变量读取配置）
setup_logging()
```

环境变量配置（`.env`）：

```bash
LOG_LEVEL=INFO              # DEBUG | INFO | WARNING | ERROR | CRITICAL
LOG_DIR=logs                # 日志文件目录
LOG_RETENTION_DAYS=30       # 日志保留天数
ENABLE_AUDIT_LOG=true       # 是否启用审计日志
```

#### 日志文件结构

```
logs/
├── trading.log             # 当日交易日志（JSON 格式）
├── trading.log.20251025    # 历史日志（自动轮转）
├── audit.log               # 当日审计日志
└── audit.log.20251025      # 历史审计日志
```

#### 使用结构化日志

**普通日志**：

```python
import structlog

logger = structlog.get_logger(__name__)

logger.info(
    "order_submitted",
    order_id=order.id,
    symbol=order.symbol,
    side=order.side,
    size=float(order.size),
    price=float(order.price)
)
```

**审计日志**（关键操作）：

```python
from src.core.logging import get_audit_logger

audit_logger = get_audit_logger()

# 订单执行
audit_logger.info(
    "order_executed",
    order_id=order.id,
    symbol=symbol,
    side=side.name,
    size=float(size),
    price=float(price),
    status=status.name,
    signal_value=signal_score.value,
)

# 风控触发
audit_logger.critical(
    "risk_control_triggered",
    event="hard_limit_breached",
    reason=reason,
    current_nav=float(nav),
    action="stop_trading",
)
```

#### 日志级别使用规范

- **DEBUG**：调试信息（开发环境）
- **INFO**：正常操作（订单提交、信号计算、健康检查）
- **WARNING**：需要关注的事件（延迟高、信号质量下降）
- **ERROR**：错误但不影响系统运行（API 调用失败、订单失败）
- **CRITICAL**：严重错误需要立即处理（风控触发、系统停机）

#### 日志格式示例

**文件日志（JSON）**：

```json
{
  "event": "trade_completed",
  "timestamp": "2025-10-26T21:30:15.123Z",
  "level": "info",
  "logger": "src.main",
  "symbol": "BTC",
  "order_id": "abc123",
  "side": "BUY",
  "size": 0.1,
  "pnl": 12.5,
  "alpha_pct": 75.3
}
```

**审计日志（JSON）**：

```json
{
  "event": "risk_control_triggered",
  "timestamp": "2025-10-26T21:35:00.000Z",
  "level": "critical",
  "logger": "audit",
  "trigger": "max_daily_drawdown",
  "value": 0.052,
  "threshold": 0.05,
  "action": "stop_trading"
}
```

**控制台日志（彩色）**：

```
2025-10-26T21:30:15.123Z [info     ] trade_completed         symbol=BTC order_id=abc123 side=BUY size=0.1 pnl=12.5
```

#### 故障排查

**查看实时日志**：

```bash
# 查看最新日志
tail -f logs/trading.log

# 查看审计日志
tail -f logs/audit.log

# 查看特定日期日志
cat logs/trading.log.20251025
```

**搜索特定事件**：

```bash
# 查找所有错误
grep '"level": "error"' logs/trading.log | jq .

# 查找特定订单
grep 'abc123' logs/trading.log | jq .

# 查找风控触发
grep 'risk_control_triggered' logs/audit.log | jq .
```

**日志分析工具**：

```python
import json

# 解析 JSON 日志
with open('logs/trading.log') as f:
    for line in f:
        log = json.loads(line)
        if log['event'] == 'trade_completed':
            print(f"Trade: {log['symbol']} {log['side']} {log['size']}")
```

---

## 测试要求

### 单元测试

**覆盖率要求**：≥ 80%

```python
import pytest
from src.signals.obi import OBISignal

def test_obi_calculation():
    """测试 OBI 信号计算"""
    signal = OBISignal(levels=5)
    market_data = create_mock_market_data()

    result = signal.calculate(market_data)

    assert -1.0 <= result <= 1.0
    assert isinstance(result, float)
```

### 集成测试

**测试实际 API 交互**（使用 testnet）：

```python
@pytest.mark.integration
async def test_ioc_execution():
    """测试 IOC 执行器"""
    executor = IOCExecutor(api_client, slippage_estimator)
    signal = SignalScore(value=0.6, confidence=ConfidenceLevel.HIGH)

    result = await executor.execute(signal, position)

    assert result is not None
    assert result.fill_size > 0
    assert abs(result.slippage) < MAX_SLIPPAGE
```

---

## Hyperliquid 平台特性

### API 端点

- **Mainnet REST API**：https://api.hyperliquid.xyz
- **Mainnet WebSocket**：wss://api.hyperliquid.xyz/ws
- **Testnet REST API**：https://api.hyperliquid-testnet.xyz
- **Testnet WebSocket**：wss://api.hyperliquid-testnet.xyz/ws

### 订单类型

| 类型 | 说明 | Week 1 使用 |
|------|------|-------------|
| **IOC** | 立即成交或取消 | ✅ 主要使用 |
| **Limit** | 限价单 | ⏳ Week 2 浅被动 |
| **Market** | 市价单 | ❌ 不使用（滑点大） |
| **Stop** | 触发单 | ❌ 不使用 |

### 费率结构

**Level 0 费率（14天成交量 ≤ $5,000,000）**：
- **Taker 费率（IOC）**：+0.045%（4.5 bps）- 消耗流动性
- **Maker 费率（限价单）**：+0.015%（1.5 bps）- 提供流动性，但仍是正费率
- **资金费率**：每 8 小时结算

**重要说明**：
- Maker **不是** rebate（负费率），是正费率，只是比 Taker 便宜 3 bps
- 只有达到做市商返佣等级（14天成交量占比>0.5%）才有负费率
- VIP 等级（>$5M/14天）可进一步降低费率

**Week 1 成本**：
- 纯 Taker 费：4.5 bps/单边
- 预估滑点：2-5 bps
- 总成本：6.5-9.5 bps

### 限制与注意事项

1. **API 限流**：
   - REST API：100 请求/分钟
   - WebSocket：无限制（推荐使用）

2. **精度要求**：
   - 价格精度：根据交易对不同
   - 数量精度：最小 0.001

3. **杠杆风险**：
   - 最大 50x 杠杆
   - 强制平仓触发：维持保证金率 < 3%

---

## 部署清单

### Testnet 部署（Week 1）

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，设置 testnet 密钥

# 2. 验证配置
python -m src.main --check-config

# 3. 运行验证脚本
make validate-all

# 4. 启动交易系统
python -m src.main --config config/week1_ioc.yaml --env testnet

# 5. 监控运行状态
tail -f logs/trading_$(date +%Y%m%d).log
```

### Mainnet 部署（需谨慎）

**前置条件**：
- [ ] Testnet 运行 ≥ 7 天
- [ ] 所有 Week 1 指标达标
- [ ] 风控充分测试
- [ ] 代码审核通过

```bash
# 1. 更新环境变量
ENVIRONMENT=mainnet

# 2. 小额启动（初始资金 < 5% 总资金）
INITIAL_NAV=5000 python -m src.main --config config/week1_ioc.yaml --env mainnet

# 3. 密切监控 24h
watch -n 60 'tail -20 logs/trading_$(date +%Y%m%d).log'

# 4. 验证通过后逐步放大
```

---

## 参考资源

### 文档

- [策略评审方案](docs/strategy_review.md)
- [架构设计文档](docs/architecture_design.md)
- [Hyperliquid API 文档](https://hyperliquid.gitbook.io/)

### 工具

- [UV 包管理器](https://github.com/astral-sh/uv)
- [Ruff 代码检查](https://docs.astral.sh/ruff/)
- [Black 代码格式化](https://black.readthedocs.io/)

### 社区

- Hyperliquid Discord
- Hyperliquid Twitter

---

## 开发注意事项

### 安全

1. **私钥管理**
   - 使用环境变量，不要硬编码
   - 考虑硬件钱包集成
   - 定期轮换 API 密钥

2. **权限控制**
   - API 密钥最小权限原则
   - 生产环境独立密钥

3. **审计日志**
   - 记录所有交易操作
   - 定期审查异常行为

### 性能

1. **异步优先**
   - 所有 I/O 操作使用 async/await
   - 避免阻塞主线程

2. **资源管理**
   - 及时关闭连接
   - 定期清理内存

3. **监控告警**
   - 设置延迟告警（p99 > 200ms）
   - 设置错误率告警（> 1%）

### 质量

1. **测试覆盖**
   - 单元测试覆盖率 ≥ 80%
   - 关键路径必须有集成测试

2. **代码审查**
   - 涉及资金操作的代码必须 review
   - 风控逻辑必须 review

3. **文档同步**
   - 代码变更时同步更新文档
   - 配置变更时更新 README

---

**文档版本**：v1.0
**最后更新**：2025-10-25
**维护者**：开发团队
