"""SignalDeduplicator 单元测试

测试覆盖：
    - 时间窗口去重
    - 信号变化阈值去重
    - 持仓状态去重
    - 信号衰减机制
    - 重置功能
"""

import time
from decimal import Decimal

import pytest

from src.core.types import (
    ConfidenceLevel,
    Level,
    MarketData,
    OrderSide,
    Position,
    SignalScore,
)
from src.execution.signal_deduplicator import SignalDeduplicator


@pytest.fixture
def deduplicator():
    """创建去重器"""
    return SignalDeduplicator(
        cooldown_seconds=5.0,
        change_threshold=0.15,
        decay_factor=0.85,
        max_same_direction=3,
    )


@pytest.fixture
def market_data():
    """创建市场数据"""
    return MarketData(
        symbol="BTC",
        timestamp=int(time.time() * 1000),
        bids=[Level(Decimal("100"), Decimal("1"))],
        asks=[Level(Decimal("101"), Decimal("1"))],
        mid_price=Decimal("100.5"),
    )


@pytest.fixture
def signal_high():
    """创建 HIGH 信号"""
    return SignalScore(
        value=0.6,
        confidence=ConfidenceLevel.HIGH,
        individual_scores=[0.6, 0.5, 0.7],
        timestamp=int(time.time() * 1000),
    )


class TestCooldownMechanism:
    """时间窗口去重测试"""

    def test_first_signal_accepted(self, deduplicator, signal_high, market_data):
        """测试首次信号通过"""
        result = deduplicator.filter(signal_high, market_data, None)
        assert result is not None
        assert result.value == 0.6

    def test_signal_rejected_within_cooldown(
        self, deduplicator, signal_high, market_data
    ):
        """测试冷却期内信号被拒绝"""
        # 第一次信号
        deduplicator.filter(signal_high, market_data, None)

        # 立即第二次信号（冷却期内）
        result = deduplicator.filter(signal_high, market_data, None)
        assert result is None

    def test_signal_accepted_after_cooldown(
        self, deduplicator, signal_high, market_data
    ):
        """测试冷却期后信号通过"""
        # 第一次信号
        deduplicator.filter(signal_high, market_data, None)

        # 等待冷却期
        time.sleep(5.1)

        # 第二次信号应该通过
        new_signal = SignalScore(
            value=0.8,
            confidence=ConfidenceLevel.HIGH,
            individual_scores=[0.8, 0.7, 0.9],
            timestamp=int(time.time() * 1000),
        )
        result = deduplicator.filter(new_signal, market_data, None)
        assert result is not None


class TestChangeThreshold:
    """信号变化阈值测试"""

    def test_signal_rejected_no_change(self, deduplicator, signal_high, market_data):
        """测试信号变化不足被拒绝"""
        # 第一次信号
        deduplicator.filter(signal_high, market_data, None)

        # 等待冷却期
        time.sleep(5.1)

        # 信号变化不足（0.6 → 0.65，变化 0.05 < 0.15）
        small_change_signal = SignalScore(
            value=0.65,
            confidence=ConfidenceLevel.HIGH,
            individual_scores=[0.65, 0.6, 0.7],
            timestamp=int(time.time() * 1000),
        )
        result = deduplicator.filter(small_change_signal, market_data, None)
        assert result is None

    def test_signal_accepted_with_change(self, deduplicator, signal_high, market_data):
        """测试信号变化足够通过"""
        # 第一次信号
        deduplicator.filter(signal_high, market_data, None)

        # 等待冷却期
        time.sleep(5.1)

        # 信号变化足够（0.6 → 0.8，变化 0.2 > 0.15）
        changed_signal = SignalScore(
            value=0.8,
            confidence=ConfidenceLevel.HIGH,
            individual_scores=[0.8, 0.7, 0.9],
            timestamp=int(time.time() * 1000),
        )
        result = deduplicator.filter(changed_signal, market_data, None)
        assert result is not None


class TestPositionStateDedup:
    """持仓状态去重测试"""

    def test_signal_rejected_same_direction_as_position(
        self, deduplicator, market_data
    ):
        """测试同方向信号被拒绝"""
        # 创建多头持仓
        long_position = Position(
            symbol="BTC", size=Decimal("1.0"), entry_price=Decimal("100")
        )

        # 创建买入信号（与持仓同方向）
        buy_signal = SignalScore(
            value=0.6,
            confidence=ConfidenceLevel.HIGH,
            individual_scores=[0.6, 0.5, 0.7],
            timestamp=int(time.time() * 1000),
        )

        result = deduplicator.filter(buy_signal, market_data, long_position)
        assert result is None

    def test_signal_accepted_opposite_direction(self, deduplicator, market_data):
        """测试反方向信号通过"""
        # 创建多头持仓
        long_position = Position(
            symbol="BTC", size=Decimal("1.0"), entry_price=Decimal("100")
        )

        # 创建卖出信号（与持仓反方向）
        sell_signal = SignalScore(
            value=-0.6,
            confidence=ConfidenceLevel.HIGH,
            individual_scores=[-0.6, -0.5, -0.7],
            timestamp=int(time.time() * 1000),
        )

        result = deduplicator.filter(sell_signal, market_data, long_position)
        assert result is not None


class TestDecayMechanism:
    """信号衰减机制测试"""

    def test_consecutive_same_direction_decay(self, deduplicator, market_data):
        """测试连续同方向信号衰减"""
        # 第一次买入信号（无衰减）
        signal1 = SignalScore(
            value=0.6,
            confidence=ConfidenceLevel.HIGH,
            individual_scores=[0.6, 0.5, 0.7],
            timestamp=int(time.time() * 1000),
        )
        result1 = deduplicator.filter(signal1, market_data, None)
        assert result1.value == 0.6

        # 等待冷却
        time.sleep(5.1)

        # 第二次买入信号（衰减 0.85）
        signal2 = SignalScore(
            value=0.8,
            confidence=ConfidenceLevel.HIGH,
            individual_scores=[0.8, 0.7, 0.9],
            timestamp=int(time.time() * 1000),
        )
        result2 = deduplicator.filter(signal2, market_data, None)
        expected_value = 0.8 * 0.85
        assert abs(result2.value - expected_value) < 0.001

    def test_direction_change_resets_decay(self, deduplicator, market_data):
        """测试方向改变重置衰减"""
        # 买入信号
        buy_signal = SignalScore(
            value=0.6,
            confidence=ConfidenceLevel.HIGH,
            individual_scores=[0.6, 0.5, 0.7],
            timestamp=int(time.time() * 1000),
        )
        deduplicator.filter(buy_signal, market_data, None)

        time.sleep(5.1)

        # 卖出信号（方向改变，重置衰减）
        sell_signal = SignalScore(
            value=-0.6,
            confidence=ConfidenceLevel.HIGH,
            individual_scores=[-0.6, -0.5, -0.7],
            timestamp=int(time.time() * 1000),
        )
        result = deduplicator.filter(sell_signal, market_data, None)
        assert result.value == -0.6  # 无衰减

    def test_max_consecutive_rejection(self, deduplicator, market_data):
        """测试超过最大连续次数拒绝"""
        # 连续 3 次买入信号（max_same_direction=3）
        for i in range(3):
            signal = SignalScore(
                value=0.6 + i * 0.2,
                confidence=ConfidenceLevel.HIGH,
                individual_scores=[0.6, 0.5, 0.7],
                timestamp=int(time.time() * 1000),
            )
            result = deduplicator.filter(signal, market_data, None)
            assert result is not None
            time.sleep(5.1)

        # 第 4 次应该被拒绝
        signal4 = SignalScore(
            value=0.9,
            confidence=ConfidenceLevel.HIGH,
            individual_scores=[0.9, 0.8, 1.0],
            timestamp=int(time.time() * 1000),
        )
        result4 = deduplicator.filter(signal4, market_data, None)
        assert result4 is None


class TestResetFunctionality:
    """重置功能测试"""

    def test_reset_clears_state(self, deduplicator, signal_high, market_data):
        """测试重置清空状态"""
        # 执行一次信号
        deduplicator.filter(signal_high, market_data, None)

        # 重置
        deduplicator.reset_symbol("BTC")

        # 立即再次执行应该通过（因为状态已清空）
        result = deduplicator.filter(signal_high, market_data, None)
        assert result is not None


class TestStats:
    """统计信息测试"""

    def test_get_stats(self, deduplicator, signal_high, market_data):
        """测试获取统计信息"""
        # 执行一次信号
        deduplicator.filter(signal_high, market_data, None)

        stats = deduplicator.get_stats("BTC")
        assert stats["last_signal_value"] == 0.6
        assert stats["last_direction"] == "BUY"
        assert stats["consecutive_direction_count"] == 1
