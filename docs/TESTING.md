# Week 1 IOC 交易系统测试指南

## 测试架构

### 测试层级

```
tests/
├── conftest.py           # 通用 fixtures 和配置
├── unit/                 # 单元测试
│   ├── test_signals.py   # 信号层测试
│   ├── test_risk.py      # 风控层测试
│   └── test_analytics.py # 分析层测试
├── integration/          # 集成测试
│   └── test_trading_flow.py  # 端到端流程测试
└── fixtures/             # 测试数据
```

### 测试覆盖

| 模块 | 测试文件 | 覆盖范围 |
|------|----------|----------|
| 信号层 | `test_signals.py` | OBI, Microprice, Impact, Aggregator |
| 风控层 | `test_risk.py` | HardLimits, PositionManager |
| 分析层 | `test_analytics.py` | PnLAttribution, MetricsCollector |
| 集成 | `test_trading_flow.py` | 完整交易流程 |

## 快速开始

### 安装测试依赖

```bash
# 使用 make（推荐）
make install-dev

# 或者直接使用 uv
uv pip install -e ".[dev]"
```

### 运行测试

```bash
# 运行所有测试
make test

# 运行单元测试
pytest tests/unit/ -v

# 运行集成测试
pytest tests/integration/ -v

# 运行特定文件的测试
pytest tests/unit/test_signals.py -v

# 运行特定测试
pytest tests/unit/test_signals.py::TestOBISignal::test_obi_calculation_basic -v

# 显示测试覆盖率
make test-cov
```

### 测试标记

使用 pytest 标记来选择性运行测试：

```bash
# 只运行单元测试
pytest -m unit

# 只运行集成测试
pytest -m integration

# 跳过慢速测试
pytest -m "not slow"

# 只运行异步测试
pytest -m asyncio
```

## 测试详解

### 1. 单元测试

#### 信号层测试 (`test_signals.py`)

**测试内容**：
- OBI 计算逻辑（正常/极端情况）
- 微观价格计算和偏离度
- 市场冲击信号和时间窗口
- 信号聚合和置信度分类

**示例**：
```python
def test_obi_calculation_basic(self, sample_market_data):
    """测试基础 OBI 计算"""
    signal = OBISignal(levels=3)
    value = signal.calculate(sample_market_data)
    assert -1.0 <= value <= 1.0
```

**关键测试场景**：
- ✅ 正常市场数据
- ✅ 买卖失衡数据
- ✅ 宽点差数据
- ✅ 空订单簿边界情况

#### 风控层测试 (`test_risk.py`)

**测试内容**：
- 单笔损失限制检查
- 持仓规模限制检查
- 日内回撤限制检查
- 持仓管理和 PnL 计算

**示例**：
```python
def test_single_loss_limit(self, sample_buy_order, sample_market_data):
    """测试单笔损失限制"""
    limits = HardLimits(
        initial_nav=Decimal("100000.0"),
        max_single_loss_pct=0.008,
        max_daily_drawdown_pct=0.05,
        max_position_size_usd=10000.0,
    )

    is_allowed, reason = limits.check_order(...)
    assert is_allowed
```

**关键测试场景**：
- ✅ 正常订单通过
- ✅ 超大订单拒绝
- ✅ 累计回撤触发
- ✅ 持仓平仓逻辑

#### 分析层测试 (`test_analytics.py`)

**测试内容**：
- PnL 分解（Alpha/Fee/Slippage/Impact）
- Alpha 健康度检查（≥70%）
- IC 计算（信号质量）
- 执行指标统计

**示例**：
```python
def test_attribute_buy_trade(self, sample_buy_order):
    """测试买入交易归因"""
    attribution = PnLAttribution()

    result = attribution.attribute_trade(
        order=sample_buy_order,
        signal_value=0.8,
        reference_price=Decimal("1500.0"),
        actual_fill_price=Decimal("1500.5"),
        best_price=Decimal("1500.5"),
    )

    # Total = Alpha + Fee + Slippage + Impact + Rebate
    assert result.total_pnl != 0
```

**关键测试场景**：
- ✅ 买入/卖出归因
- ✅ 手续费计算正确
- ✅ Alpha 占比验证
- ✅ IC 计算（需≥10个样本）

### 2. 集成测试

#### 交易流程测试 (`test_trading_flow.py`)

**测试内容**：
- 完整交易周期（数据→信号→风控→执行→归因）
- 错误处理（数据缺失、订单失败）
- 并发处理（多交易对）
- 配置变化场景

**示例**：
```python
@pytest.mark.asyncio
async def test_complete_trading_cycle(self, test_config, sample_market_data):
    """测试完整交易周期"""
    engine = TradingEngine(test_config)

    # 模拟市场数据
    engine.data_manager.get_market_data = MagicMock(
        return_value=sample_market_data
    )

    # 处理交易对
    await engine._process_symbol("ETH")

    # 验证无异常
    assert True
```

**关键测试场景**：
- ✅ 端到端成功流程
- ✅ 风控拒绝订单
- ✅ 订单执行失败恢复
- ✅ 风控突破停止交易
- ✅ 并发多交易对处理

## 测试 Fixtures

### 市场数据 Fixtures

```python
@pytest.fixture
def sample_market_data(sample_levels) -> MarketData:
    """标准市场数据"""
    # ETH 价格 1500, 正常点差

@pytest.fixture
def wide_spread_market_data() -> MarketData:
    """宽点差市场数据（流动性差）"""
    # 点差 5 USD

@pytest.fixture
def imbalanced_market_data() -> MarketData:
    """买卖不平衡市场数据（强偏向）"""
    # 买单 100 ETH vs 卖单 5 ETH
```

### 信号 Fixtures

```python
@pytest.fixture
def high_confidence_buy_signal() -> SignalScore:
    """高置信度买入信号（value=0.85）"""

@pytest.fixture
def medium_confidence_signal() -> SignalScore:
    """中等置信度信号（value=0.55）"""
```

### 订单 Fixtures

```python
@pytest.fixture
def sample_buy_order() -> Order:
    """标准买入订单（1 ETH @ 1500.5）"""

@pytest.fixture
def partially_filled_order() -> Order:
    """部分成交订单（6/10 filled）"""
```

### 工厂 Fixtures

```python
@pytest.fixture
def create_market_data():
    """创建自定义市场数据的工厂函数"""
    def _create(symbol="ETH", mid_price=1500.0, spread_bps=5.0):
        # ...
    return _create

@pytest.fixture
def create_signal():
    """创建自定义信号的工厂函数"""
    def _create(value, confidence=SignalConfidence.MEDIUM):
        # ...
    return _create
```

## Mock 对象

### Mock API Client

```python
@pytest.fixture
def mock_api_client(mocker):
    """Mock Hyperliquid API 客户端"""
    mock = mocker.MagicMock()
    mock.place_order.return_value = {
        "status": "success",
        "order_id": "mock_order_001",
    }
    return mock
```

### Mock WebSocket

```python
@pytest.fixture
def mock_websocket(mocker):
    """Mock WebSocket 客户端"""
    mock = mocker.MagicMock()
    mock.is_connected.return_value = True
    return mock
```

## 测试最佳实践

### 1. 使用 Fixtures

❌ **不好**：
```python
def test_signal():
    data = MarketData(...)  # 每个测试都重复创建
    signal = OBISignal()
    result = signal.calculate(data)
```

✅ **好**：
```python
def test_signal(sample_market_data):
    signal = OBISignal()
    result = signal.calculate(sample_market_data)
```

### 2. 明确测试意图

❌ **不好**：
```python
def test_stuff():
    # 测试多个不相关的东西
```

✅ **好**：
```python
def test_obi_buy_imbalance():
    """测试买单失衡场景（买单明显多于卖单）"""
    # 单一明确的测试目标
```

### 3. 异步测试

```python
@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result is not None
```

### 4. Mock 外部依赖

```python
with patch("src.main.HyperliquidWebSocket") as mock_ws:
    mock_ws.return_value = MagicMock()
    # 测试逻辑
```

## 测试数据生成

### 价格序列

```python
def test_with_uptrend(price_series_uptrend):
    """使用上涨趋势测试"""
    # price_series_uptrend: [1500, 1505, 1510, ...]
```

### 自定义数据

```python
def test_custom_market(create_market_data):
    """使用工厂创建自定义数据"""
    data = create_market_data(
        symbol="BTC",
        mid_price=30000.0,
        spread_bps=10.0,
        depth=5,
    )
```

## 持续集成

### GitHub Actions（示例）

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install uv
          uv pip install -e ".[dev]"
      - name: Run tests
        run: pytest
```

## 测试覆盖率目标

| 模块 | 目标覆盖率 | 当前状态 |
|------|-----------|---------|
| 信号层 | ≥90% | ✅ |
| 风控层 | ≥95% | ✅ |
| 分析层 | ≥90% | ✅ |
| 执行层 | ≥85% | ⏳ |
| 数据层 | ≥80% | ⏳ |

**查看覆盖率报告**：
```bash
make test-cov
open htmlcov/index.html
```

## 故障排查

### 常见问题

1. **AsyncIO 警告**
   ```
   RuntimeWarning: coroutine 'test' was never awaited
   ```
   **解决**：添加 `@pytest.mark.asyncio` 装饰器

2. **Fixture 未找到**
   ```
   fixture 'sample_market_data' not found
   ```
   **解决**：检查 `conftest.py` 是否正确放置

3. **Import 错误**
   ```
   ModuleNotFoundError: No module named 'src'
   ```
   **解决**：确保在项目根目录运行测试

4. **Mock 不工作**
   ```
   AttributeError: Mock object has no attribute...
   ```
   **解决**：检查 patch 路径是否正确

### 调试技巧

```bash
# 详细输出
pytest -vv

# 显示 print 输出
pytest -s

# 遇到第一个失败就停止
pytest -x

# 进入调试器
pytest --pdb

# 只运行失败的测试
pytest --lf
```

## Week 1 验证清单

### 单元测试验证
- ✅ 信号计算正确性
- ✅ 风控限制有效性
- ✅ PnL 归因准确性
- ✅ 指标收集完整性

### 集成测试验证
- ✅ 端到端流程正确
- ✅ 错误恢复机制
- ✅ 并发处理能力
- ✅ 配置变化适应

### 性能测试（待 24h Mainnet 验证）
- ⏳ 单次处理 < 100ms
- ⏳ Alpha ≥ 70%
- ⏳ IC ≥ 0.03
- ⏳ 系统稳定性（无崩溃）

## 下一步

完成单元测试和集成测试后：

1. **24 小时 Mainnet 验证**
   - 使用真实 Mainnet 数据
   - 监控 Alpha 占比
   - 记录 IC 和延迟
   - 验证风控有效性

2. **性能优化**
   - 根据测试结果优化瓶颈
   - 调整配置参数
   - 优化信号计算

3. **Week 2 准备**
   - 评估 Week 1 结果
   - 规划 Maker 订单策略
   - 设计更复杂的信号组合

---

**测试是质量保证的基础。Week 1 的目标是通过测试验证系统的正确性和稳定性。**
