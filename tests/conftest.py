"""Pytest 配置和通用 fixtures"""

import time
from decimal import Decimal

import pytest

from src.core.types import (
    ConfidenceLevel,
    Level,
    MarketData,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    SignalScore,
)

# ==================== 市场数据 Fixtures ====================


@pytest.fixture
def sample_levels() -> dict:
    """标准订单簿深度数据"""
    return {
        "bids": [
            Level(price=Decimal("1500.0"), size=Decimal("10.0")),
            Level(price=Decimal("1499.5"), size=Decimal("15.0")),
            Level(price=Decimal("1499.0"), size=Decimal("20.0")),
        ],
        "asks": [
            Level(price=Decimal("1500.5"), size=Decimal("12.0")),
            Level(price=Decimal("1501.0"), size=Decimal("18.0")),
            Level(price=Decimal("1501.5"), size=Decimal("25.0")),
        ],
    }


@pytest.fixture
def sample_market_data(sample_levels) -> MarketData:
    """标准市场数据"""
    return MarketData(
        symbol="ETH",
        timestamp=int(time.time() * 1000),
        bids=sample_levels["bids"],
        asks=sample_levels["asks"],
        mid_price=Decimal("1500.25"),
    )


@pytest.fixture
def wide_spread_market_data() -> MarketData:
    """宽点差市场数据（流动性差）"""
    return MarketData(
        symbol="ETH",
        timestamp=int(time.time() * 1000),
        bids=[
            Level(price=Decimal("1500.0"), size=Decimal("5.0")),
            Level(price=Decimal("1495.0"), size=Decimal("8.0")),
        ],
        asks=[
            Level(price=Decimal("1505.0"), size=Decimal("6.0")),
            Level(price=Decimal("1510.0"), size=Decimal("10.0")),
        ],
        mid_price=Decimal("1502.5"),
    )


@pytest.fixture
def imbalanced_market_data() -> MarketData:
    """买卖不平衡市场数据（强偏向）"""
    return MarketData(
        symbol="ETH",
        timestamp=int(time.time() * 1000),
        bids=[
            Level(price=Decimal("1500.0"), size=Decimal("100.0")),  # 大买单
            Level(price=Decimal("1499.5"), size=Decimal("80.0")),
        ],
        asks=[
            Level(price=Decimal("1500.5"), size=Decimal("5.0")),  # 小卖单
            Level(price=Decimal("1501.0"), size=Decimal("8.0")),
        ],
        mid_price=Decimal("1500.25"),
    )


# ==================== 信号 Fixtures ====================


@pytest.fixture
def high_confidence_buy_signal() -> SignalScore:
    """高置信度买入信号"""
    return SignalScore(
        value=0.85,
        confidence=ConfidenceLevel.HIGH,
        individual_scores=[0.3, 0.35, 0.2],
        timestamp=int(time.time() * 1000),
    )


@pytest.fixture
def high_confidence_sell_signal() -> SignalScore:
    """高置信度卖出信号"""
    return SignalScore(
        value=-0.82,
        confidence=ConfidenceLevel.HIGH,
        individual_scores=[-0.3, -0.32, -0.2],
        timestamp=int(time.time() * 1000),
    )


@pytest.fixture
def medium_confidence_signal() -> SignalScore:
    """中等置信度信号"""
    return SignalScore(
        value=0.55,
        confidence=ConfidenceLevel.MEDIUM,
        individual_scores=[0.2, 0.25, 0.1],
        timestamp=int(time.time() * 1000),
    )


@pytest.fixture
def low_confidence_signal() -> SignalScore:
    """低置信度信号"""
    return SignalScore(
        value=0.35,
        confidence=ConfidenceLevel.LOW,
        individual_scores=[0.1, 0.15, 0.1],
        timestamp=int(time.time() * 1000),
    )


# ==================== 订单 Fixtures ====================


@pytest.fixture
def sample_buy_order() -> Order:
    """标准买入订单"""
    return Order(
        id="test_buy_001",
        symbol="ETH",
        side=OrderSide.BUY,
        order_type=OrderType.IOC,
        price=Decimal("1500.5"),
        size=Decimal("1.0"),
        filled_size=Decimal("1.0"),
        status=OrderStatus.FILLED,
        created_at=int(time.time() * 1000),
    )


@pytest.fixture
def sample_sell_order() -> Order:
    """标准卖出订单"""
    return Order(
        id="test_sell_001",
        symbol="ETH",
        side=OrderSide.SELL,
        order_type=OrderType.IOC,
        price=Decimal("1499.5"),
        size=Decimal("1.0"),
        filled_size=Decimal("1.0"),
        status=OrderStatus.FILLED,
        created_at=int(time.time() * 1000),
    )


@pytest.fixture
def partially_filled_order() -> Order:
    """部分成交订单"""
    return Order(
        id="test_partial_001",
        symbol="ETH",
        side=OrderSide.BUY,
        order_type=OrderType.IOC,
        price=Decimal("1500.0"),
        size=Decimal("10.0"),
        filled_size=Decimal("6.0"),
        status=OrderStatus.PARTIAL_FILLED,
        created_at=int(time.time() * 1000),
    )


@pytest.fixture
def cancelled_order() -> Order:
    """已取消订单"""
    return Order(
        id="test_cancelled_001",
        symbol="ETH",
        side=OrderSide.BUY,
        order_type=OrderType.IOC,
        price=Decimal("1500.0"),
        size=Decimal("5.0"),
        filled_size=Decimal("0.0"),
        status=OrderStatus.CANCELLED,
        created_at=int(time.time() * 1000),
    )


# ==================== 配置 Fixtures ====================


@pytest.fixture
def test_config():
    """测试配置对象"""
    from src.core.config import (
        Config,
        ExecutionConfig,
        HyperliquidConfig,
        RiskConfig,
        SignalConfig,
        SignalThresholdsConfig,
    )

    return Config(
        hyperliquid=HyperliquidConfig(
            wallet_address="0x0000000000000000000000000000000000000001",
            private_key="test_private_key",
            use_mainnet=True,
            symbols=["ETH", "BTC"],
        ),
        signals=SignalConfig(
            obi_levels=5,
            obi_weight=0.35,
            microprice_weight=0.40,
            impact_window_ms=5000,
            impact_weight=0.25,
            thresholds=SignalThresholdsConfig(
                theta_1=0.75,  # HIGH
                theta_2=0.50,  # MEDIUM
            ),
        ),
        risk=RiskConfig(
            max_single_loss_pct=0.008,  # 0.8%
            max_daily_drawdown_pct=0.05,  # 5%
            max_position_size_usd=10000.0,
        ),
        execution=ExecutionConfig(
            max_slippage_bps=20.0,  # 20 bps
            default_size_usd=1000.0,
        ),
        initial_nav=100000.0,  # 10万美金
    )


# ==================== 环境变量设置 ====================


@pytest.fixture(scope="session", autouse=True)
def setup_test_env(monkeypatch_session):
    """自动设置测试环境变量（整个测试会话生效）"""
    import os

    # 设置测试用的钱包配置（避免使用真实凭证）
    os.environ.setdefault("HYPERLIQUID_WALLET_ADDRESS", "0x" + "0" * 40)
    os.environ.setdefault("HYPERLIQUID_PRIVATE_KEY", "0x" + "1" * 64)

    # 降低日志级别，减少测试输出噪音
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    os.environ.setdefault("ENABLE_AUDIT_LOG", "false")

    # 测试模式标识
    os.environ.setdefault("TESTING", "true")

    yield


@pytest.fixture(scope="session")
def monkeypatch_session():
    """Session 级别的 monkeypatch（用于环境变量设置）"""
    from _pytest.monkeypatch import MonkeyPatch

    m = MonkeyPatch()
    yield m
    m.undo()


# ==================== Mock 对象 Fixtures ====================


@pytest.fixture
def mock_api_client():
    """
    Mock Hyperliquid API 客户端（异步方法版本）

    注意：不再接受 mocker 参数，直接使用 unittest.mock
    这样可以避免与 Hyperliquid SDK 初始化的冲突
    """
    from unittest.mock import AsyncMock, MagicMock

    mock = MagicMock(spec=["place_order", "cancel_order", "get_order_status", "get_account_state", "wallet_address"])

    # 正确配置异步方法（返回 AsyncMock）
    mock.place_order = AsyncMock(return_value={
        "status": "ok",
        "response": {
            "type": "order",
            "data": {
                "statuses": [{
                    "resting": {
                        "oid": "mock_order_001"
                    }
                }]
            }
        }
    })

    mock.cancel_order = AsyncMock(return_value={
        "status": "ok",
        "response": {"type": "cancel", "data": {"statuses": ["success"]}}
    })

    mock.get_order_status = AsyncMock(return_value={
        "status": "filled",
        "filled_size": "1.0",
    })

    mock.get_account_state = AsyncMock(return_value={
        "marginSummary": {"accountValue": "100000.0"},
        "assetPositions": []
    })

    # 模拟钱包地址
    mock.wallet_address = "0x" + "0" * 40

    return mock


@pytest.fixture
def mock_websocket(mocker):
    """Mock WebSocket 客户端"""
    mock = mocker.MagicMock()
    mock.subscribe.return_value = None
    mock.is_connected.return_value = True
    return mock


# ==================== 时间序列数据 Fixtures ====================


@pytest.fixture
def price_series_uptrend() -> list[Decimal]:
    """上涨趋势价格序列"""
    base = 1500.0
    return [Decimal(str(base + i * 5)) for i in range(20)]


@pytest.fixture
def price_series_downtrend() -> list[Decimal]:
    """下跌趋势价格序列"""
    base = 1500.0
    return [Decimal(str(base - i * 5)) for i in range(20)]


@pytest.fixture
def price_series_volatile() -> list[Decimal]:
    """震荡价格序列"""
    base = 1500.0
    import math

    return [
        Decimal(str(base + 50 * math.sin(i * 0.5)))
        for i in range(20)
    ]


# ==================== 辅助函数 ====================


@pytest.fixture
def create_market_data():
    """创建自定义市场数据的工厂函数"""

    def _create(
        symbol: str = "ETH",
        mid_price: float = 1500.0,
        spread_bps: float = 5.0,
        depth: int = 3,
    ) -> MarketData:
        """
        创建市场数据

        Args:
            symbol: 交易对
            mid_price: 中间价
            spread_bps: 买卖价差（基点）
            depth: 深度档位数量
        """
        spread = mid_price * spread_bps / 10000

        bids = [
            Level(
                price=Decimal(str(mid_price - spread / 2 - i * 0.5)),
                size=Decimal(str(10.0 + i * 2))
            )
            for i in range(depth)
        ]

        asks = [
            Level(
                price=Decimal(str(mid_price + spread / 2 + i * 0.5)),
                size=Decimal(str(12.0 + i * 2))
            )
            for i in range(depth)
        ]

        return MarketData(
            symbol=symbol,
            timestamp=int(time.time() * 1000),
            bids=bids,
            asks=asks,
            mid_price=Decimal(str(mid_price)),
        )

    return _create


@pytest.fixture
def create_signal():
    """创建自定义信号的工厂函数"""

    def _create(
        value: float,
        confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM,
    ) -> SignalScore:
        """创建信号评分"""
        return SignalScore(
            value=value,
            confidence=confidence,
            individual_scores=[value * 0.35, value * 0.40, value * 0.25],
            timestamp=int(time.time() * 1000),
        )

    return _create


# ==================== Week 2 Phase 2 Fixtures ====================


@pytest.fixture
def mock_tp_sl_manager():
    """Mock TP/SL Manager"""
    from unittest.mock import MagicMock

    from src.core.types import Position

    mock = MagicMock()

    # 默认行为：不触发平仓
    mock.check_position_risk.return_value = (False, "")

    # 提供辅助方法设置触发行为
    def set_trigger(should_close: bool, reason: str):
        mock.check_position_risk.return_value = (should_close, reason)

    mock.set_trigger = set_trigger

    return mock


@pytest.fixture
def mock_position_manager():
    """Mock Position Manager"""
    from unittest.mock import MagicMock

    from src.core.types import Position

    mock = MagicMock()

    # 默认行为
    mock.get_position.return_value = None
    mock.is_position_stale.return_value = False
    mock.get_position_age_seconds.return_value = 0.0

    # 辅助方法：设置持仓
    def set_position(position: Position | None):
        mock.get_position.return_value = position

    # 辅助方法：设置超时状态
    def set_stale(is_stale: bool, age_seconds: float = 1800.0):
        mock.is_position_stale.return_value = is_stale
        mock.get_position_age_seconds.return_value = age_seconds

    mock.set_position = set_position
    mock.set_stale = set_stale

    return mock


@pytest.fixture
def mock_ioc_executor():
    """Mock IOC Executor"""
    from unittest.mock import AsyncMock, MagicMock

    from src.core.types import Order, OrderSide, OrderStatus, OrderType

    mock = MagicMock()

    # 默认成功执行
    default_order = Order(
        id="mock_close_001",
        symbol="ETH",
        side=OrderSide.SELL,
        order_type=OrderType.IOC,
        price=Decimal("1500.0"),
        size=Decimal("1.0"),
        filled_size=Decimal("1.0"),
        status=OrderStatus.FILLED,
        created_at=int(time.time() * 1000),
    )

    mock.execute = AsyncMock(return_value=default_order)

    # 辅助方法：设置执行结果
    def set_execute_result(order: Order | None):
        mock.execute = AsyncMock(return_value=order)

    mock.set_execute_result = set_execute_result

    return mock


@pytest.fixture
def create_position():
    """创建持仓的工厂函数"""
    from src.core.types import Position

    def _create(
        symbol: str = "ETH",
        size: float = 1.0,
        entry_price: float = 1500.0,
        unrealized_pnl: float = 0.0,
        open_timestamp: int | None = None,
    ) -> Position:
        """
        创建持仓对象

        Args:
            symbol: 交易对
            size: 持仓尺寸（正数=多头，负数=空头）
            entry_price: 开仓价格
            unrealized_pnl: 未实现盈亏
            open_timestamp: 开仓时间戳（默认当前时间）
        """
        return Position(
            symbol=symbol,
            size=Decimal(str(size)),
            entry_price=Decimal(str(entry_price)),
            unrealized_pnl=Decimal(str(unrealized_pnl)),
            open_timestamp=open_timestamp or int(time.time() * 1000),
        )

    return _create


@pytest.fixture
def market_data_dict_factory(create_market_data):
    """创建市场数据字典的工厂函数"""

    def _create(
        symbols: list[str] = ["ETH", "BTC"],
        mid_prices: dict[str, float] | None = None,
    ) -> dict:
        """
        创建市场数据字典

        Args:
            symbols: 交易对列表
            mid_prices: symbol -> mid_price 映射（可选）
        """
        prices = mid_prices or {symbol: 1500.0 + i * 100 for i, symbol in enumerate(symbols)}

        return {
            symbol: create_market_data(symbol=symbol, mid_price=prices.get(symbol, 1500.0))
            for symbol in symbols
        }

    return _create


# ==================== 日志系统隔离 Fixtures ====================


@pytest.fixture(scope="function", autouse=False)
def isolated_logging(tmp_path, monkeypatch):
    """
    为每个测试提供隔离的日志系统环境

    使用方法：
    1. 在需要隔离日志的测试类或函数上添加此 fixture
    2. 它会自动创建临时日志目录
    3. 重置全局日志配置
    4. 测试结束后清理
    """
    import logging

    import structlog

    # 强制关闭所有日志处理器（彻底清理）
    logging.shutdown()

    # 保存原始日志配置
    original_handlers = logging.root.handlers[:]
    original_level = logging.root.level

    # 清除所有现有处理器
    for handler in logging.root.handlers[:]:
        handler.close()
        logging.root.removeHandler(handler)

    # 重置 structlog
    structlog.reset_defaults()

    # 设置临时日志目录
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setenv("LOG_DIR", str(log_dir))

    yield log_dir

    # 清理：强制刷新并关闭所有处理器
    logging.shutdown()
    for handler in logging.root.handlers[:]:
        handler.flush()
        handler.close()
        logging.root.removeHandler(handler)

    # 恢复原始配置
    for handler in original_handlers:
        logging.root.addHandler(handler)
    logging.root.setLevel(original_level)

    # 重置 structlog
    structlog.reset_defaults()
