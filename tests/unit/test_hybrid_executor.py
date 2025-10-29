"""HybridExecutor 单元测试

测试混合执行协调器的核心功能：
1. HIGH 置信度路由（Maker → IOC 回退）
2. MEDIUM 置信度路由（Maker → 超时跳过）
3. LOW 置信度跳过
4. 统计数据追踪
5. 异常处理
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

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
from src.execution.hybrid_executor import HybridExecutor


def create_signal(value: float, confidence: ConfidenceLevel) -> SignalScore:
    """测试辅助函数：创建 SignalScore"""
    return SignalScore(
        value=value,
        confidence=confidence,
        individual_scores=[value],
        timestamp=1234567890,
    )


def create_order(order_id: str, status: OrderStatus, filled_size: str = "0.01") -> Order:
    """测试辅助函数：创建 Order"""
    return Order(
        id=order_id,
        symbol="BTC",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal("100000.0"),
        size=Decimal("0.01"),
        filled_size=Decimal(filled_size),
        status=status,
        created_at=1234567890,
        error_message=None,
    )


@pytest.fixture
def mock_shallow_maker():
    """Mock ShallowMakerExecutor"""
    executor = MagicMock()
    executor.execute = AsyncMock()
    return executor


@pytest.fixture
def mock_ioc_executor():
    """Mock IOCExecutor"""
    executor = MagicMock()
    executor.execute = AsyncMock()
    return executor


@pytest.fixture
def hybrid_executor(mock_shallow_maker, mock_ioc_executor):
    """创建 HybridExecutor 实例"""
    return HybridExecutor(
        shallow_maker_executor=mock_shallow_maker,
        ioc_executor=mock_ioc_executor,
        enable_fallback=True,
        fallback_on_medium=False,  # Week 1.5 默认：MEDIUM 不回退
    )


@pytest.fixture
def market_data():
    """创建测试市场数据"""
    return MarketData(
        symbol="BTC",
        timestamp=1234567890,
        bids=[
            Level(price=Decimal("100000.0"), size=Decimal("1.0")),
            Level(price=Decimal("99999.9"), size=Decimal("0.5")),
        ],
        asks=[
            Level(price=Decimal("100000.1"), size=Decimal("1.0")),
            Level(price=Decimal("100000.2"), size=Decimal("0.5")),
        ],
        mid_price=Decimal("100000.05"),
        trades=[],
    )


class TestInitialization:
    """测试初始化"""

    def test_default_initialization(self, mock_shallow_maker, mock_ioc_executor):
        """测试默认参数初始化"""
        executor = HybridExecutor(
            shallow_maker_executor=mock_shallow_maker,
            ioc_executor=mock_ioc_executor,
        )

        assert executor.enable_fallback is True
        assert executor.fallback_on_medium is False
        assert executor._stats["total_signals"] == 0

    def test_custom_initialization(self, mock_shallow_maker, mock_ioc_executor):
        """测试自定义参数初始化"""
        executor = HybridExecutor(
            shallow_maker_executor=mock_shallow_maker,
            ioc_executor=mock_ioc_executor,
            enable_fallback=False,
            fallback_on_medium=True,
        )

        assert executor.enable_fallback is False
        assert executor.fallback_on_medium is True


class TestHighConfidenceRouting:
    """测试 HIGH 置信度路由（Maker → IOC 回退）"""

    @pytest.mark.asyncio
    async def test_high_confidence_maker_success(
        self, hybrid_executor, mock_shallow_maker, mock_ioc_executor, market_data
    ):
        """测试 HIGH 置信度 Maker 成交成功"""
        signal = create_signal(value=0.6, confidence=ConfidenceLevel.HIGH)

        # Mock Maker 成交成功
        maker_order = create_order("maker_123", OrderStatus.FILLED)
        mock_shallow_maker.execute.return_value = maker_order

        result = await hybrid_executor.execute(signal, market_data)

        # 验证返回 Maker 订单
        assert result == maker_order
        mock_shallow_maker.execute.assert_called_once()
        mock_ioc_executor.execute.assert_not_called()  # 不应该回退

        # 验证统计
        stats = hybrid_executor.get_statistics()
        assert stats["high_confidence_count"] == 1
        assert stats["maker_executions"] == 1
        assert stats["ioc_executions"] == 0
        assert stats["fallback_executions"] == 0

    @pytest.mark.asyncio
    async def test_high_confidence_maker_timeout_fallback_ioc(
        self, hybrid_executor, mock_shallow_maker, mock_ioc_executor, market_data
    ):
        """测试 HIGH 置信度 Maker 超时后回退 IOC"""
        signal = create_signal(value=0.6, confidence=ConfidenceLevel.HIGH)

        # Mock Maker 超时（返回 None）
        mock_shallow_maker.execute.return_value = None

        # Mock IOC 回退成功
        ioc_order = create_order("ioc_456", OrderStatus.FILLED)
        mock_ioc_executor.execute.return_value = ioc_order

        result = await hybrid_executor.execute(signal, market_data)

        # 验证返回 IOC 订单
        assert result == ioc_order
        mock_shallow_maker.execute.assert_called_once()
        mock_ioc_executor.execute.assert_called_once()

        # 验证统计
        stats = hybrid_executor.get_statistics()
        assert stats["high_confidence_count"] == 1
        assert stats["maker_executions"] == 0
        assert stats["ioc_executions"] == 1
        assert stats["fallback_executions"] == 1

    @pytest.mark.asyncio
    async def test_high_confidence_maker_timeout_fallback_disabled(
        self, mock_shallow_maker, mock_ioc_executor, market_data
    ):
        """测试 HIGH 置信度 Maker 超时但回退被禁用"""
        signal = create_signal(value=0.6, confidence=ConfidenceLevel.HIGH)

        # 禁用回退
        executor = HybridExecutor(
            shallow_maker_executor=mock_shallow_maker,
            ioc_executor=mock_ioc_executor,
            enable_fallback=False,
        )

        # Mock Maker 超时
        mock_shallow_maker.execute.return_value = None

        result = await executor.execute(signal, market_data)

        # 验证返回 None（不回退）
        assert result is None
        mock_shallow_maker.execute.assert_called_once()
        mock_ioc_executor.execute.assert_not_called()

        # 验证统计
        stats = executor.get_statistics()
        assert stats["skipped_signals"] == 1

    @pytest.mark.asyncio
    async def test_high_confidence_fallback_ioc_also_fails(
        self, hybrid_executor, mock_shallow_maker, mock_ioc_executor, market_data
    ):
        """测试 HIGH 置信度 Maker 超时且 IOC 回退也失败"""
        signal = create_signal(value=0.6, confidence=ConfidenceLevel.HIGH)

        # Mock Maker 超时
        mock_shallow_maker.execute.return_value = None

        # Mock IOC 回退也失败
        mock_ioc_executor.execute.return_value = None

        result = await hybrid_executor.execute(signal, market_data)

        # 验证返回 None
        assert result is None
        mock_shallow_maker.execute.assert_called_once()
        mock_ioc_executor.execute.assert_called_once()

        # 验证统计
        stats = hybrid_executor.get_statistics()
        assert stats["high_confidence_count"] == 1
        assert stats["skipped_signals"] == 1


class TestMediumConfidenceRouting:
    """测试 MEDIUM 置信度路由（Maker → 超时跳过）"""

    @pytest.mark.asyncio
    async def test_medium_confidence_maker_success(
        self, hybrid_executor, mock_shallow_maker, mock_ioc_executor, market_data
    ):
        """测试 MEDIUM 置信度 Maker 成交成功"""
        signal = create_signal(value=0.35, confidence=ConfidenceLevel.MEDIUM)

        # Mock Maker 成交成功
        maker_order = create_order("maker_medium", OrderStatus.FILLED)
        mock_shallow_maker.execute.return_value = maker_order

        result = await hybrid_executor.execute(signal, market_data)

        # 验证返回 Maker 订单
        assert result == maker_order
        mock_shallow_maker.execute.assert_called_once()
        mock_ioc_executor.execute.assert_not_called()

        # 验证统计
        stats = hybrid_executor.get_statistics()
        assert stats["medium_confidence_count"] == 1
        assert stats["maker_executions"] == 1

    @pytest.mark.asyncio
    async def test_medium_confidence_maker_timeout_no_fallback(
        self, hybrid_executor, mock_shallow_maker, mock_ioc_executor, market_data
    ):
        """测试 MEDIUM 置信度 Maker 超时后不回退（Week 1.5 默认）"""
        signal = create_signal(value=0.35, confidence=ConfidenceLevel.MEDIUM)

        # Mock Maker 超时
        mock_shallow_maker.execute.return_value = None

        result = await hybrid_executor.execute(signal, market_data)

        # 验证返回 None（不回退 IOC）
        assert result is None
        mock_shallow_maker.execute.assert_called_once()
        mock_ioc_executor.execute.assert_not_called()

        # 验证统计
        stats = hybrid_executor.get_statistics()
        assert stats["medium_confidence_count"] == 1
        assert stats["maker_executions"] == 0
        assert stats["ioc_executions"] == 0
        assert stats["fallback_executions"] == 0
        assert stats["skipped_signals"] == 1

    @pytest.mark.asyncio
    async def test_medium_confidence_maker_timeout_with_fallback_enabled(
        self, mock_shallow_maker, mock_ioc_executor, market_data
    ):
        """测试 MEDIUM 置信度 Maker 超时且启用回退"""
        signal = create_signal(value=0.35, confidence=ConfidenceLevel.MEDIUM)

        # 启用 MEDIUM 回退
        executor = HybridExecutor(
            shallow_maker_executor=mock_shallow_maker,
            ioc_executor=mock_ioc_executor,
            enable_fallback=True,
            fallback_on_medium=True,  # 启用 MEDIUM 回退
        )

        # Mock Maker 超时
        mock_shallow_maker.execute.return_value = None

        # Mock IOC 回退成功
        ioc_order = create_order("ioc_medium", OrderStatus.FILLED)
        mock_ioc_executor.execute.return_value = ioc_order

        result = await executor.execute(signal, market_data)

        # 验证返回 IOC 订单
        assert result == ioc_order
        mock_shallow_maker.execute.assert_called_once()
        mock_ioc_executor.execute.assert_called_once()

        # 验证统计
        stats = executor.get_statistics()
        assert stats["medium_confidence_count"] == 1
        assert stats["ioc_executions"] == 1
        assert stats["fallback_executions"] == 1


class TestLowConfidenceRouting:
    """测试 LOW 置信度路由（直接跳过）"""

    @pytest.mark.asyncio
    async def test_low_confidence_skipped(
        self, hybrid_executor, mock_shallow_maker, mock_ioc_executor, market_data
    ):
        """测试 LOW 置信度直接跳过"""
        signal = create_signal(value=0.1, confidence=ConfidenceLevel.LOW)

        result = await hybrid_executor.execute(signal, market_data)

        # 验证返回 None
        assert result is None
        mock_shallow_maker.execute.assert_not_called()
        mock_ioc_executor.execute.assert_not_called()

        # 验证统计
        stats = hybrid_executor.get_statistics()
        assert stats["low_confidence_count"] == 1
        assert stats["skipped_signals"] == 1


class TestStatistics:
    """测试统计功能"""

    @pytest.mark.asyncio
    async def test_get_statistics_multiple_executions(
        self, hybrid_executor, mock_shallow_maker, mock_ioc_executor, market_data
    ):
        """测试多次执行后的统计数据"""
        # HIGH 成交
        signal_high = create_signal(value=0.6, confidence=ConfidenceLevel.HIGH)
        mock_shallow_maker.execute.return_value = create_order("maker_1", OrderStatus.FILLED)
        await hybrid_executor.execute(signal_high, market_data)

        # MEDIUM 成交
        signal_medium = create_signal(value=0.35, confidence=ConfidenceLevel.MEDIUM)
        mock_shallow_maker.execute.return_value = create_order("maker_2", OrderStatus.FILLED)
        await hybrid_executor.execute(signal_medium, market_data)

        # LOW 跳过
        signal_low = create_signal(value=0.1, confidence=ConfidenceLevel.LOW)
        await hybrid_executor.execute(signal_low, market_data)

        # HIGH 超时回退 IOC
        signal_high_timeout = create_signal(value=0.7, confidence=ConfidenceLevel.HIGH)
        mock_shallow_maker.execute.return_value = None
        mock_ioc_executor.execute.return_value = create_order("ioc_1", OrderStatus.FILLED)
        await hybrid_executor.execute(signal_high_timeout, market_data)

        # 验证统计
        stats = hybrid_executor.get_statistics()
        assert stats["total_signals"] == 4
        assert stats["high_confidence_count"] == 2
        assert stats["medium_confidence_count"] == 1
        assert stats["low_confidence_count"] == 1
        assert stats["maker_executions"] == 2
        assert stats["ioc_executions"] == 1
        assert stats["fallback_executions"] == 1
        assert stats["skipped_signals"] == 1

        # 验证百分比计算
        assert stats["maker_fill_rate"] == 50.0  # 2/4 = 50%
        assert stats["ioc_fill_rate"] == 25.0  # 1/4 = 25%
        assert stats["fallback_rate"] == 25.0  # 1/4 = 25%

    def test_reset_statistics(self, hybrid_executor):
        """测试重置统计数据"""
        hybrid_executor._stats["total_signals"] = 10
        hybrid_executor._stats["maker_executions"] = 5

        hybrid_executor.reset_statistics()

        stats = hybrid_executor.get_statistics()
        assert stats["total_signals"] == 0
        assert stats["maker_executions"] == 0


class TestErrorHandling:
    """测试异常处理"""

    @pytest.mark.asyncio
    async def test_exception_in_maker_executor(
        self, hybrid_executor, mock_shallow_maker, mock_ioc_executor, market_data
    ):
        """测试 Maker 执行器抛出异常"""
        signal = create_signal(value=0.6, confidence=ConfidenceLevel.HIGH)

        # Mock Maker 抛出异常
        mock_shallow_maker.execute.side_effect = Exception("Maker Error")

        result = await hybrid_executor.execute(signal, market_data)

        # 验证返回 None
        assert result is None

        # 验证统计
        stats = hybrid_executor.get_statistics()
        assert stats["skipped_signals"] == 1

    @pytest.mark.asyncio
    async def test_exception_in_ioc_executor(
        self, hybrid_executor, mock_shallow_maker, mock_ioc_executor, market_data
    ):
        """测试 IOC 执行器抛出异常"""
        signal = create_signal(value=0.6, confidence=ConfidenceLevel.HIGH)

        # Mock Maker 超时
        mock_shallow_maker.execute.return_value = None

        # Mock IOC 抛出异常
        mock_ioc_executor.execute.side_effect = Exception("IOC Error")

        result = await hybrid_executor.execute(signal, market_data)

        # 验证返回 None（异常被捕获）
        assert result is None

        # 验证统计
        stats = hybrid_executor.get_statistics()
        assert stats["skipped_signals"] == 1


class TestRepr:
    """测试字符串表示"""

    def test_repr(self, hybrid_executor):
        """测试 __repr__ 方法"""
        repr_str = repr(hybrid_executor)

        assert "HybridExecutor" in repr_str
        assert "enable_fallback=True" in repr_str
        assert "fallback_on_medium=False" in repr_str
