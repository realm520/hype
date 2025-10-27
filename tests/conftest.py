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
            use_mainnet=False,  # 测试模式使用 testnet
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


# ==================== Mock 对象 Fixtures ====================


@pytest.fixture
def mock_api_client(mocker):
    """Mock Hyperliquid API 客户端"""
    mock = mocker.MagicMock()
    mock.place_order.return_value = {
        "status": "success",
        "order_id": "mock_order_001",
    }
    mock.cancel_order.return_value = {"status": "success"}
    mock.get_order_status.return_value = {
        "status": "filled",
        "filled_size": "1.0",
    }
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
