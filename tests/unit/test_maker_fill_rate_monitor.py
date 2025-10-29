"""MakerFillRateMonitor 单元测试

测试 Maker 成交率监控器的核心功能：
1. 滑动窗口统计
2. 分置信度级别监控（HIGH/MEDIUM）
3. 告警机制（WARNING/CRITICAL）
4. 健康度检查
5. 统计数据追踪
"""

# 直接导入避免 scipy 依赖问题
import sys
from decimal import Decimal

from src.core.types import (
    ConfidenceLevel,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)

sys.path.insert(0, "/Users/harry/code/quants/hype")
from src.analytics.maker_fill_rate_monitor import MakerFillRateMonitor


def create_order(order_id: str, symbol: str = "BTC") -> Order:
    """测试辅助函数：创建 Order"""
    return Order(
        id=order_id,
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal("100000.0"),
        size=Decimal("0.01"),
        filled_size=Decimal("0.01"),
        status=OrderStatus.FILLED,
        created_at=1234567890,
        error_message=None,
    )


class TestInitialization:
    """测试初始化"""

    def test_default_initialization(self):
        """测试默认参数初始化"""
        monitor = MakerFillRateMonitor()

        assert monitor.window_size == 100
        assert monitor.alert_threshold_high == 0.80
        assert monitor.alert_threshold_medium == 0.75
        assert monitor.critical_threshold == 0.60

    def test_custom_initialization(self):
        """测试自定义参数初始化"""
        monitor = MakerFillRateMonitor(
            window_size=50,
            alert_threshold_high=0.85,
            alert_threshold_medium=0.70,
            critical_threshold=0.50,
        )

        assert monitor.window_size == 50
        assert monitor.alert_threshold_high == 0.85
        assert monitor.alert_threshold_medium == 0.70
        assert monitor.critical_threshold == 0.50


class TestRecordAttempts:
    """测试记录 Maker 尝试"""

    def test_record_high_confidence_filled(self):
        """测试记录 HIGH 置信度成交"""
        monitor = MakerFillRateMonitor(window_size=10)
        order = create_order("order_1")

        monitor.record_maker_attempt(order, ConfidenceLevel.HIGH, filled=True)

        stats = monitor.get_statistics()
        assert stats["high"]["total_attempts"] == 1
        assert stats["high"]["total_filled"] == 1
        assert stats["high"]["window_size"] == 1

    def test_record_high_confidence_timeout(self):
        """测试记录 HIGH 置信度超时"""
        monitor = MakerFillRateMonitor(window_size=10)
        order = create_order("order_2")

        monitor.record_maker_attempt(order, ConfidenceLevel.HIGH, filled=False)

        stats = monitor.get_statistics()
        assert stats["high"]["total_attempts"] == 1
        assert stats["high"]["total_filled"] == 0
        assert stats["high"]["window_size"] == 1

    def test_record_medium_confidence_filled(self):
        """测试记录 MEDIUM 置信度成交"""
        monitor = MakerFillRateMonitor(window_size=10)
        order = create_order("order_3")

        monitor.record_maker_attempt(order, ConfidenceLevel.MEDIUM, filled=True)

        stats = monitor.get_statistics()
        assert stats["medium"]["total_attempts"] == 1
        assert stats["medium"]["total_filled"] == 1
        assert stats["medium"]["window_size"] == 1

    def test_record_multiple_attempts(self):
        """测试记录多次尝试"""
        monitor = MakerFillRateMonitor(window_size=10)

        # HIGH: 3 成交, 1 超时
        for i in range(3):
            order = create_order(f"high_filled_{i}")
            monitor.record_maker_attempt(order, ConfidenceLevel.HIGH, filled=True)

        order_timeout = create_order("high_timeout")
        monitor.record_maker_attempt(order_timeout, ConfidenceLevel.HIGH, filled=False)

        # MEDIUM: 2 成交, 2 超时
        for i in range(2):
            order = create_order(f"medium_filled_{i}")
            monitor.record_maker_attempt(order, ConfidenceLevel.MEDIUM, filled=True)

        for i in range(2):
            order = create_order(f"medium_timeout_{i}")
            monitor.record_maker_attempt(
                order, ConfidenceLevel.MEDIUM, filled=False
            )

        # 验证统计
        stats = monitor.get_statistics()
        assert stats["high"]["total_attempts"] == 4
        assert stats["high"]["total_filled"] == 3
        assert stats["medium"]["total_attempts"] == 4
        assert stats["medium"]["total_filled"] == 2


class TestSlidingWindow:
    """测试滑动窗口"""

    def test_window_size_limit(self):
        """测试窗口大小限制"""
        monitor = MakerFillRateMonitor(window_size=5)

        # 记录 10 次尝试（超过窗口大小）
        for i in range(10):
            order = create_order(f"order_{i}")
            monitor.record_maker_attempt(
                order, ConfidenceLevel.HIGH, filled=(i % 2 == 0)
            )

        # 验证窗口大小不超过 5
        stats = monitor.get_statistics()
        assert stats["high"]["window_size"] == 5
        assert stats["high"]["total_attempts"] == 10  # 全局统计不受限制

    def test_window_based_vs_total_fill_rate(self):
        """测试窗口成交率 vs 全局成交率"""
        monitor = MakerFillRateMonitor(window_size=3)

        # 前 5 次：全部成交
        for i in range(5):
            order = create_order(f"order_{i}")
            monitor.record_maker_attempt(order, ConfidenceLevel.HIGH, filled=True)

        # 后 3 次：全部超时
        for i in range(3):
            order = create_order(f"timeout_{i}")
            monitor.record_maker_attempt(
                order, ConfidenceLevel.HIGH, filled=False
            )

        # 窗口只保留最近 3 次（全部超时）
        window_fill_rate = monitor.get_fill_rate(ConfidenceLevel.HIGH, window_based=True)
        assert window_fill_rate == 0.0  # 0/3

        # 全局统计 5 成交 / 8 尝试
        total_fill_rate = monitor.get_fill_rate(ConfidenceLevel.HIGH, window_based=False)
        assert total_fill_rate == 5 / 8


class TestFillRateCalculation:
    """测试成交率计算"""

    def test_get_fill_rate_no_data(self):
        """测试无数据时返回 None"""
        monitor = MakerFillRateMonitor()

        fill_rate = monitor.get_fill_rate(ConfidenceLevel.HIGH, window_based=True)
        assert fill_rate is None

    def test_get_fill_rate_100_percent(self):
        """测试 100% 成交率"""
        monitor = MakerFillRateMonitor(window_size=10)

        # 10 次全部成交
        for i in range(10):
            order = create_order(f"order_{i}")
            monitor.record_maker_attempt(order, ConfidenceLevel.HIGH, filled=True)

        fill_rate = monitor.get_fill_rate(ConfidenceLevel.HIGH, window_based=True)
        assert fill_rate == 1.0

    def test_get_fill_rate_0_percent(self):
        """测试 0% 成交率"""
        monitor = MakerFillRateMonitor(window_size=10)

        # 10 次全部超时
        for i in range(10):
            order = create_order(f"order_{i}")
            monitor.record_maker_attempt(
                order, ConfidenceLevel.HIGH, filled=False
            )

        fill_rate = monitor.get_fill_rate(ConfidenceLevel.HIGH, window_based=True)
        assert fill_rate == 0.0

    def test_get_fill_rate_50_percent(self):
        """测试 50% 成交率"""
        monitor = MakerFillRateMonitor(window_size=10)

        # 5 成交, 5 超时
        for i in range(10):
            order = create_order(f"order_{i}")
            monitor.record_maker_attempt(
                order, ConfidenceLevel.HIGH, filled=(i < 5)
            )

        fill_rate = monitor.get_fill_rate(ConfidenceLevel.HIGH, window_based=True)
        assert fill_rate == 0.5

    def test_get_fill_rate_low_confidence(self):
        """测试 LOW 置信度返回 None（不监控）"""
        monitor = MakerFillRateMonitor()

        fill_rate = monitor.get_fill_rate(ConfidenceLevel.LOW, window_based=True)
        assert fill_rate is None


class TestHealthCheck:
    """测试健康度检查"""

    def test_is_healthy_no_data(self):
        """测试无数据时默认健康"""
        monitor = MakerFillRateMonitor()

        assert monitor.is_healthy(ConfidenceLevel.HIGH) is True

    def test_is_healthy_above_threshold(self):
        """测试成交率高于阈值（健康）"""
        monitor = MakerFillRateMonitor(alert_threshold_high=0.80, window_size=10)

        # 9 成交, 1 超时 = 90%
        for i in range(9):
            order = create_order(f"order_{i}")
            monitor.record_maker_attempt(order, ConfidenceLevel.HIGH, filled=True)

        order_timeout = create_order("timeout")
        monitor.record_maker_attempt(order_timeout, ConfidenceLevel.HIGH, filled=False)

        assert monitor.is_healthy(ConfidenceLevel.HIGH) is True

    def test_is_healthy_below_threshold(self):
        """测试成交率低于阈值（不健康）"""
        monitor = MakerFillRateMonitor(alert_threshold_high=0.80, window_size=10)

        # 7 成交, 3 超时 = 70%
        for i in range(7):
            order = create_order(f"order_{i}")
            monitor.record_maker_attempt(order, ConfidenceLevel.HIGH, filled=True)

        for i in range(3):
            order = create_order(f"timeout_{i}")
            monitor.record_maker_attempt(
                order, ConfidenceLevel.HIGH, filled=False
            )

        assert monitor.is_healthy(ConfidenceLevel.HIGH) is False

    def test_is_healthy_different_thresholds(self):
        """测试不同置信度的不同阈值"""
        monitor = MakerFillRateMonitor(
            alert_threshold_high=0.80,
            alert_threshold_medium=0.75,
            window_size=10,
        )

        # HIGH: 70% 成交率（低于 80%，不健康）
        for i in range(10):
            order = create_order(f"high_{i}")
            monitor.record_maker_attempt(
                order, ConfidenceLevel.HIGH, filled=(i < 7)
            )

        # MEDIUM: 77% 成交率（高于 75%，健康）
        for i in range(10):
            order = create_order(f"medium_{i}")
            monitor.record_maker_attempt(
                order, ConfidenceLevel.MEDIUM, filled=(i < 8)
            )

        # HIGH 不健康，MEDIUM 健康
        assert monitor.is_healthy(ConfidenceLevel.HIGH) is False
        assert monitor.is_healthy(ConfidenceLevel.MEDIUM) is True


class TestCriticalAlert:
    """测试严重告警"""

    def test_is_critical_no_data(self):
        """测试无数据时不触发严重告警"""
        monitor = MakerFillRateMonitor()

        assert monitor.is_critical(ConfidenceLevel.HIGH) is False

    def test_is_critical_above_threshold(self):
        """测试成交率高于严重阈值（不严重）"""
        monitor = MakerFillRateMonitor(critical_threshold=0.60, window_size=10)

        # 7 成交, 3 超时 = 70%
        for i in range(10):
            order = create_order(f"order_{i}")
            monitor.record_maker_attempt(
                order, ConfidenceLevel.HIGH, filled=(i < 7)
            )

        assert monitor.is_critical(ConfidenceLevel.HIGH) is False

    def test_is_critical_below_threshold(self):
        """测试成交率低于严重阈值（严重）"""
        monitor = MakerFillRateMonitor(critical_threshold=0.60, window_size=10)

        # 5 成交, 5 超时 = 50%
        for i in range(10):
            order = create_order(f"order_{i}")
            monitor.record_maker_attempt(
                order, ConfidenceLevel.HIGH, filled=(i < 5)
            )

        assert monitor.is_critical(ConfidenceLevel.HIGH) is True


class TestStatistics:
    """测试统计功能"""

    def test_get_statistics_empty(self):
        """测试空统计数据"""
        monitor = MakerFillRateMonitor()

        stats = monitor.get_statistics()

        assert stats["high"]["window_fill_rate"] == 0.0
        assert stats["high"]["total_attempts"] == 0
        assert stats["medium"]["window_fill_rate"] == 0.0

    def test_get_statistics_with_data(self):
        """测试有数据的统计"""
        monitor = MakerFillRateMonitor(window_size=10)

        # HIGH: 8 成交, 2 超时
        for i in range(10):
            order = create_order(f"high_{i}")
            monitor.record_maker_attempt(
                order, ConfidenceLevel.HIGH, filled=(i < 8)
            )

        # MEDIUM: 6 成交, 4 超时
        for i in range(10):
            order = create_order(f"medium_{i}")
            monitor.record_maker_attempt(
                order, ConfidenceLevel.MEDIUM, filled=(i < 6)
            )

        stats = monitor.get_statistics()

        # HIGH 统计
        assert stats["high"]["window_fill_rate"] == 0.8
        assert stats["high"]["total_fill_rate"] == 0.8
        assert stats["high"]["total_attempts"] == 10
        assert stats["high"]["total_filled"] == 8

        # MEDIUM 统计
        assert stats["medium"]["window_fill_rate"] == 0.6
        assert stats["medium"]["total_fill_rate"] == 0.6
        assert stats["medium"]["total_attempts"] == 10
        assert stats["medium"]["total_filled"] == 6

    def test_reset_statistics(self):
        """测试重置统计数据"""
        monitor = MakerFillRateMonitor(window_size=10)

        # 记录一些数据
        for i in range(5):
            order = create_order(f"order_{i}")
            monitor.record_maker_attempt(order, ConfidenceLevel.HIGH, filled=True)

        # 重置
        monitor.reset_statistics()

        # 验证统计已清零
        stats = monitor.get_statistics()
        assert stats["high"]["total_attempts"] == 0
        assert stats["high"]["total_filled"] == 0
        assert stats["high"]["window_size"] == 0


class TestRepr:
    """测试字符串表示"""

    def test_repr_no_data(self):
        """测试无数据时的 __repr__"""
        monitor = MakerFillRateMonitor()

        repr_str = repr(monitor)

        assert "MakerFillRateMonitor" in repr_str
        assert "HIGH=0.00%" in repr_str
        assert "MEDIUM=0.00%" in repr_str

    def test_repr_with_data(self):
        """测试有数据时的 __repr__"""
        monitor = MakerFillRateMonitor(window_size=10)

        # HIGH: 80% 成交率
        for i in range(10):
            order = create_order(f"order_{i}")
            monitor.record_maker_attempt(
                order, ConfidenceLevel.HIGH, filled=(i < 8)
            )

        repr_str = repr(monitor)

        assert "MakerFillRateMonitor" in repr_str
        assert "HIGH=80.00%" in repr_str or "HIGH=0.80" in repr_str
        assert "window=10" in repr_str
