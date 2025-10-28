"""FutureReturnTracker 单元测试"""

import time
from decimal import Decimal
from unittest.mock import Mock

import pytest

from src.analytics.future_return_tracker import FutureReturnTracker


@pytest.fixture
def mock_callback():
    """模拟回调函数"""
    return Mock()


@pytest.fixture
def tracker(mock_callback):
    """创建跟踪器实例"""
    return FutureReturnTracker(
        window_minutes=10,
        update_callback=mock_callback,
        price_history_window_seconds=3600,  # 1 小时
    )


class TestPriceHistoryRecording:
    """测试价格历史记录功能"""

    def test_record_signal_stores_price_history(self, tracker):
        """测试 record_signal 是否正确存储价格历史"""
        # 记录信号
        tracker.record_signal(
            signal_id=1,
            signal_value=0.5,
            symbol="BTC",
            price=Decimal("50000.0"),
        )

        # 验证价格历史已存储
        assert "BTC" in tracker._price_history
        assert len(tracker._price_history["BTC"]) == 1

        timestamp, price = tracker._price_history["BTC"][0]
        assert price == Decimal("50000.0")
        assert isinstance(timestamp, float)

    def test_multiple_symbols_price_history(self, tracker):
        """测试多币种价格历史"""
        symbols = ["BTC", "ETH", "SOL"]
        prices = [Decimal("50000"), Decimal("3000"), Decimal("100")]

        for symbol, price in zip(symbols, prices):
            tracker.record_signal(
                signal_id=1, signal_value=0.5, symbol=symbol, price=price
            )

        # 验证所有币种都有价格历史
        for symbol in symbols:
            assert symbol in tracker._price_history
            assert len(tracker._price_history[symbol]) == 1

    def test_price_history_accumulation(self, tracker):
        """测试价格历史累积"""
        symbol = "BTC"
        prices = [Decimal("50000"), Decimal("50100"), Decimal("50200")]

        for i, price in enumerate(prices):
            tracker.record_signal(
                signal_id=i, signal_value=0.5, symbol=symbol, price=price
            )
            time.sleep(0.01)  # 确保时间戳不同

        # 验证价格历史累积
        assert len(tracker._price_history[symbol]) == 3

        # 验证价格按时间顺序存储
        stored_prices = [price for _, price in tracker._price_history[symbol]]
        assert stored_prices == prices


class TestPriceHistoryCleanup:
    """测试价格历史自动清理"""

    def test_old_prices_are_removed(self):
        """测试旧价格被自动清理"""
        callback = Mock()
        # 使用很短的窗口（1秒）
        tracker = FutureReturnTracker(
            window_minutes=10,
            update_callback=callback,
            price_history_window_seconds=1,
        )

        # 记录第一个价格
        tracker.record_signal(
            signal_id=1,
            signal_value=0.5,
            symbol="BTC",
            price=Decimal("50000"),
        )

        assert len(tracker._price_history["BTC"]) == 1

        # 等待超过窗口时间
        time.sleep(1.5)

        # 记录新价格（应该触发清理）
        tracker.record_signal(
            signal_id=2,
            signal_value=0.5,
            symbol="BTC",
            price=Decimal("51000"),
        )

        # 验证旧价格被清理
        assert len(tracker._price_history["BTC"]) == 1

        # 验证保留的是新价格
        _, latest_price = tracker._price_history["BTC"][0]
        assert latest_price == Decimal("51000")

    def test_cleanup_preserves_recent_prices(self, tracker):
        """测试清理不影响最近的价格"""
        symbol = "BTC"

        # 快速记录多个价格
        for i in range(5):
            tracker.record_signal(
                signal_id=i,
                signal_value=0.5,
                symbol=symbol,
                price=Decimal(f"{50000 + i * 100}"),
            )
            time.sleep(0.01)

        # 所有价格应该都保留（因为在窗口内）
        assert len(tracker._price_history[symbol]) == 5


class TestGetPriceAtTime:
    """测试价格时间序列查询"""

    def test_get_exact_price(self, tracker):
        """测试获取精确时间的价格"""
        target_time = time.time()
        tracker._record_price("BTC", Decimal("50000"), target_time)

        # 查询精确时间的价格
        price = tracker._get_price_at_time("BTC", target_time, tolerance_seconds=1.0)

        assert price == Decimal("50000")

    def test_get_closest_price(self, tracker):
        """测试获取最接近时间的价格"""
        base_time = time.time()

        # 记录几个价格
        tracker._record_price("BTC", Decimal("50000"), base_time)
        tracker._record_price("BTC", Decimal("50100"), base_time + 10)
        tracker._record_price("BTC", Decimal("50200"), base_time + 20)

        # 查询 base_time + 12 的价格（应该返回 base_time + 10 的价格）
        price = tracker._get_price_at_time(
            "BTC", base_time + 12, tolerance_seconds=5.0
        )

        assert price == Decimal("50100")

    def test_get_price_outside_tolerance(self, tracker):
        """测试超出容忍范围返回 None"""
        base_time = time.time()
        tracker._record_price("BTC", Decimal("50000"), base_time)

        # 查询远超容忍范围的时间
        price = tracker._get_price_at_time(
            "BTC", base_time + 100, tolerance_seconds=10.0
        )

        assert price is None

    def test_get_price_for_unknown_symbol(self, tracker):
        """测试查询不存在的币种返回 None"""
        price = tracker._get_price_at_time("UNKNOWN", time.time())
        assert price is None


class TestBackfillFutureReturns:
    """测试回填计算功能"""

    def test_single_window_backfill(self, tracker):
        """测试单窗口回填计算"""
        base_time = time.time()

        # 记录信号（做多信号）
        tracker.record_signal(
            signal_id=1,
            signal_value=0.5,  # 做多
            symbol="BTC",
            price=Decimal("50000"),
        )

        # 模拟 5 分钟后价格上涨
        future_time = base_time + (5 * 60)
        tracker._record_price("BTC", Decimal("51000"), future_time)  # +2% 上涨

        # 回填计算
        results = tracker.backfill_future_returns([5])

        # 验证结果
        assert 1 in results
        assert 5 in results[1]

        # 做多信号 + 价格上涨 = 正收益
        future_return = results[1][5]
        assert future_return > 0
        assert abs(future_return - 0.02) < 0.001  # 约 2%

    def test_multiple_windows_backfill(self, tracker):
        """测试多窗口回填计算"""
        base_time = time.time()

        # 记录信号
        tracker.record_signal(
            signal_id=1,
            signal_value=0.5,
            symbol="BTC",
            price=Decimal("50000"),
        )

        # 模拟不同时间点的价格
        for minutes, price in [
            (5, Decimal("50500")),
            (10, Decimal("51000")),
            (15, Decimal("51500")),
        ]:
            future_time = base_time + (minutes * 60)
            tracker._record_price("BTC", price, future_time)

        # 回填多个窗口
        results = tracker.backfill_future_returns([5, 10, 15])

        # 验证所有窗口都有结果
        assert 1 in results
        assert set(results[1].keys()) == {5, 10, 15}

        # 验证收益递增（价格持续上涨）
        assert results[1][5] < results[1][10] < results[1][15]

    def test_short_signal_backfill(self, tracker):
        """测试做空信号的回填计算"""
        base_time = time.time()

        # 记录做空信号
        tracker.record_signal(
            signal_id=1,
            signal_value=-0.5,  # 做空
            symbol="BTC",
            price=Decimal("50000"),
        )

        # 模拟价格下跌
        future_time = base_time + (5 * 60)
        tracker._record_price("BTC", Decimal("49000"), future_time)  # -2% 下跌

        # 回填计算
        results = tracker.backfill_future_returns([5])

        # 做空信号 + 价格下跌 = 正收益
        future_return = results[1][5]
        assert future_return > 0
        assert abs(future_return - 0.02) < 0.001

    def test_multiple_signals_backfill(self, tracker):
        """测试多个信号的回填计算"""
        base_time = time.time()

        # 记录多个信号
        for i in range(3):
            tracker.record_signal(
                signal_id=i,
                signal_value=0.5,
                symbol="BTC",
                price=Decimal("50000"),
            )
            time.sleep(0.01)

        # 模拟未来价格
        future_time = base_time + (5 * 60)
        tracker._record_price("BTC", Decimal("51000"), future_time)

        # 回填计算
        results = tracker.backfill_future_returns([5])

        # 验证所有信号都有结果
        assert len(results) == 3
        for signal_id in range(3):
            assert signal_id in results
            assert 5 in results[signal_id]

    def test_missing_price_backfill(self, tracker):
        """测试价格缺失时的回填处理"""
        # 记录信号但不记录未来价格
        tracker.record_signal(
            signal_id=1,
            signal_value=0.5,
            symbol="BTC",
            price=Decimal("50000"),
        )

        # 回填计算（无未来价格）
        results = tracker.backfill_future_returns([5])

        # 验证信号存在但无回填结果
        assert 1 in results
        assert len(results[1]) == 0  # 无有效窗口结果

    def test_cross_symbol_backfill(self, tracker):
        """测试跨币种回填计算"""
        base_time = time.time()

        # 记录不同币种的信号
        symbols_and_prices = [
            ("BTC", Decimal("50000"), Decimal("51000")),
            ("ETH", Decimal("3000"), Decimal("3060")),
            ("SOL", Decimal("100"), Decimal("102")),
        ]

        for i, (symbol, init_price, future_price) in enumerate(symbols_and_prices):
            # 记录信号
            tracker.record_signal(
                signal_id=i, signal_value=0.5, symbol=symbol, price=init_price
            )

            # 记录未来价格
            future_time = base_time + (5 * 60)
            tracker._record_price(symbol, future_price, future_time)

        # 回填计算
        results = tracker.backfill_future_returns([5])

        # 验证每个币种的信号都有结果
        assert len(results) == 3
        for i in range(3):
            assert i in results
            assert 5 in results[i]
            # 所有币种都应该有正收益（价格都上涨）
            assert results[i][5] > 0


class TestStatistics:
    """测试统计信息"""

    def test_statistics_includes_price_history(self, tracker):
        """测试统计信息包含价格历史"""
        # 记录一些信号
        tracker.record_signal(1, 0.5, "BTC", Decimal("50000"))
        tracker.record_signal(2, 0.5, "ETH", Decimal("3000"))
        tracker.record_signal(3, 0.5, "BTC", Decimal("50100"))

        stats = tracker.get_statistics()

        # 验证价格历史统计
        assert "price_history_symbols" in stats
        assert "price_history_points" in stats

        assert set(stats["price_history_symbols"]) == {"BTC", "ETH"}
        assert stats["price_history_points"] == 3  # 3 个价格点


class TestDirectionalReturn:
    """测试方向性收益计算"""

    def test_long_signal_with_price_increase(self, tracker):
        """测试做多信号 + 价格上涨"""
        future_return = tracker._calculate_directional_return(
            old_price=Decimal("50000"),
            new_price=Decimal("51000"),  # +2%
            signal_value=0.5,  # 做多
        )

        assert future_return > 0
        assert abs(future_return - 0.02) < 0.001

    def test_long_signal_with_price_decrease(self, tracker):
        """测试做多信号 + 价格下跌"""
        future_return = tracker._calculate_directional_return(
            old_price=Decimal("50000"),
            new_price=Decimal("49000"),  # -2%
            signal_value=0.5,  # 做多
        )

        assert future_return < 0
        assert abs(future_return + 0.02) < 0.001

    def test_short_signal_with_price_decrease(self, tracker):
        """测试做空信号 + 价格下跌"""
        future_return = tracker._calculate_directional_return(
            old_price=Decimal("50000"),
            new_price=Decimal("49000"),  # -2%
            signal_value=-0.5,  # 做空
        )

        assert future_return > 0
        assert abs(future_return - 0.02) < 0.001

    def test_short_signal_with_price_increase(self, tracker):
        """测试做空信号 + 价格上涨"""
        future_return = tracker._calculate_directional_return(
            old_price=Decimal("50000"),
            new_price=Decimal("51000"),  # +2%
            signal_value=-0.5,  # 做空
        )

        assert future_return < 0
        assert abs(future_return + 0.02) < 0.001
