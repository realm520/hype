"""Impact 信号测试

测试 Impact 信号的核心功能：
- 成交量计算
- 时间窗口过滤
- 信号归一化
- 边缘情况处理
"""

from decimal import Decimal

import pytest

from src.core.types import Level, MarketData, OrderSide, Trade
from src.signals.impact import ImpactSignal

# ==================== Fixtures ====================


@pytest.fixture
def impact_signal():
    """Impact 信号实例（默认 100ms 窗口）"""
    return ImpactSignal(window_ms=100, weight=0.3)


@pytest.fixture
def sample_market_data():
    """示例市场数据（含成交）"""
    return MarketData(
        symbol="ETH",
        timestamp=1000,  # Unix ms
        bids=[Level(price=Decimal("3000"), size=Decimal("10"))],
        asks=[Level(price=Decimal("3001"), size=Decimal("12"))],
        mid_price=Decimal("3000.5"),
        trades=[
            Trade(
                symbol="ETH",
                timestamp=950,  # 50ms ago
                price=Decimal("3000.5"),
                size=Decimal("2.0"),
                side=OrderSide.BUY,
            ),
            Trade(
                symbol="ETH",
                timestamp=980,  # 20ms ago
                price=Decimal("3000.4"),
                size=Decimal("1.5"),
                side=OrderSide.SELL,
            ),
        ],
    )


# ==================== 基础功能测试 ====================


class TestImpactBasics:
    """测试 Impact 信号基础功能"""

    def test_initialization(self):
        """测试初始化"""
        signal = ImpactSignal(window_ms=200, weight=0.5)

        assert signal.window_ms == 200
        assert signal.weight == 0.5
        assert signal._last_value is None  # BaseSignal 初始化为 None

    def test_impact_no_trades(self, impact_signal):
        """测试无成交数据返回 0"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1000,
            bids=[Level(price=Decimal("3000"), size=Decimal("10"))],
            asks=[Level(price=Decimal("3001"), size=Decimal("12"))],
            mid_price=Decimal("3000.5"),
            trades=[],  # 无成交
        )

        result = impact_signal.calculate(market_data)

        assert result == 0.0

    def test_impact_single_buy_trade(self, impact_signal):
        """测试单笔买入成交"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1000,
            bids=[Level(price=Decimal("3000"), size=Decimal("10"))],
            asks=[Level(price=Decimal("3001"), size=Decimal("12"))],
            mid_price=Decimal("3000.5"),
            trades=[
                Trade(
                    symbol="ETH",
                    timestamp=950,
                    price=Decimal("3000.5"),
                    size=Decimal("2.0"),
                    side=OrderSide.BUY,
                )
            ],
        )

        result = impact_signal.calculate(market_data)

        # 纯买入，impact = 1.0
        assert result == 1.0

    def test_impact_single_sell_trade(self, impact_signal):
        """测试单笔卖出成交"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1000,
            bids=[Level(price=Decimal("3000"), size=Decimal("10"))],
            asks=[Level(price=Decimal("3001"), size=Decimal("12"))],
            mid_price=Decimal("3000.5"),
            trades=[
                Trade(
                    symbol="ETH",
                    timestamp=950,
                    price=Decimal("3000.5"),
                    size=Decimal("2.0"),
                    side=OrderSide.SELL,
                )
            ],
        )

        result = impact_signal.calculate(market_data)

        # 纯卖出，impact = -1.0
        assert result == -1.0

    def test_impact_mixed_trades(self, impact_signal, sample_market_data):
        """测试买卖混合成交"""
        result = impact_signal.calculate(sample_market_data)

        # 买入 2.0，卖出 1.5
        # impact = (2.0 - 1.5) / (2.0 + 1.5) = 0.5 / 3.5 ≈ 0.143
        assert -1.0 <= result <= 1.0
        assert result > 0  # 买入主导

    def test_impact_equal_volume(self, impact_signal):
        """测试买卖量相等返回 0"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1000,
            bids=[Level(price=Decimal("3000"), size=Decimal("10"))],
            asks=[Level(price=Decimal("3001"), size=Decimal("12"))],
            mid_price=Decimal("3000.5"),
            trades=[
                Trade(
                    symbol="ETH",
                    timestamp=950,
                    price=Decimal("3000.5"),
                    size=Decimal("2.0"),
                    side=OrderSide.BUY,
                ),
                Trade(
                    symbol="ETH",
                    timestamp=980,
                    price=Decimal("3000.4"),
                    size=Decimal("2.0"),
                    side=OrderSide.SELL,
                ),
            ],
        )

        result = impact_signal.calculate(market_data)

        # 买卖平衡
        assert result == 0.0

    def test_impact_calculation_complete(self, impact_signal):
        """测试完整计算流程"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1000,
            bids=[Level(price=Decimal("3000"), size=Decimal("10"))],
            asks=[Level(price=Decimal("3001"), size=Decimal("12"))],
            mid_price=Decimal("3000.5"),
            trades=[
                Trade(
                    symbol="ETH",
                    timestamp=920,
                    price=Decimal("3000.5"),
                    size=Decimal("5.0"),
                    side=OrderSide.BUY,
                ),
                Trade(
                    symbol="ETH",
                    timestamp=950,
                    price=Decimal("3000.4"),
                    size=Decimal("3.0"),
                    side=OrderSide.SELL,
                ),
                Trade(
                    symbol="ETH",
                    timestamp=980,
                    price=Decimal("3000.6"),
                    size=Decimal("2.0"),
                    side=OrderSide.BUY,
                ),
            ],
        )

        result = impact_signal.calculate(market_data)

        # 买入 7.0，卖出 3.0
        # impact = (7 - 3) / (7 + 3) = 4/10 = 0.4
        assert result == pytest.approx(0.4, abs=0.01)


# ==================== 时间窗口过滤测试 ====================


class TestImpactTimeWindow:
    """测试 Impact 信号时间窗口过滤"""

    def test_filter_trades_within_window(self, impact_signal):
        """测试窗口内成交"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1000,
            bids=[Level(price=Decimal("3000"), size=Decimal("10"))],
            asks=[Level(price=Decimal("3001"), size=Decimal("12"))],
            mid_price=Decimal("3000.5"),
            trades=[
                # 在窗口内（1000 - 100 = 900）
                Trade(
                    symbol="ETH",
                    timestamp=950,  # 在窗口内
                    price=Decimal("3000.5"),
                    size=Decimal("2.0"),
                    side=OrderSide.BUY,
                ),
                Trade(
                    symbol="ETH",
                    timestamp=920,  # 在窗口内
                    price=Decimal("3000.4"),
                    size=Decimal("1.0"),
                    side=OrderSide.SELL,
                ),
            ],
        )

        result = impact_signal.calculate(market_data)

        # 应该计算两笔成交
        assert result != 0.0

    def test_filter_trades_outside_window(self, impact_signal):
        """测试窗口外成交被过滤"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1000,
            bids=[Level(price=Decimal("3000"), size=Decimal("10"))],
            asks=[Level(price=Decimal("3001"), size=Decimal("12"))],
            mid_price=Decimal("3000.5"),
            trades=[
                # 窗口外（1000 - 100 = 900，这些都 < 900）
                Trade(
                    symbol="ETH",
                    timestamp=800,
                    price=Decimal("3000.5"),
                    size=Decimal("2.0"),
                    side=OrderSide.BUY,
                ),
                Trade(
                    symbol="ETH",
                    timestamp=850,
                    price=Decimal("3000.4"),
                    size=Decimal("1.0"),
                    side=OrderSide.SELL,
                ),
            ],
        )

        result = impact_signal.calculate(market_data)

        # 无窗口内成交，应返回 0
        assert result == 0.0

    def test_filter_trades_boundary(self, impact_signal):
        """测试边界时间处理"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1000,
            bids=[Level(price=Decimal("3000"), size=Decimal("10"))],
            asks=[Level(price=Decimal("3001"), size=Decimal("12"))],
            mid_price=Decimal("3000.5"),
            trades=[
                # 恰好在边界上（1000 - 100 = 900）
                Trade(
                    symbol="ETH",
                    timestamp=900,  # 边界值
                    price=Decimal("3000.5"),
                    size=Decimal("2.0"),
                    side=OrderSide.BUY,
                ),
            ],
        )

        result = impact_signal.calculate(market_data)

        # 边界值应该被包含（>=）
        assert result == 1.0

    def test_no_recent_trades(self, impact_signal):
        """测试无窗口内成交"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1000,
            bids=[Level(price=Decimal("3000"), size=Decimal("10"))],
            asks=[Level(price=Decimal("3001"), size=Decimal("12"))],
            mid_price=Decimal("3000.5"),
            trades=[
                Trade(
                    symbol="ETH",
                    timestamp=500,  # 很久以前
                    price=Decimal("3000.5"),
                    size=Decimal("2.0"),
                    side=OrderSide.BUY,
                )
            ],
        )

        result = impact_signal.calculate(market_data)

        assert result == 0.0


# ==================== 成交量计算测试 ====================


class TestImpactVolumeCalculation:
    """测试成交量计算逻辑"""

    def test_calculate_volumes_buy_only(self, impact_signal):
        """测试纯买入成交量计算"""
        trades = [
            Trade(
                symbol="ETH",
                timestamp=950,
                price=Decimal("3000.5"),
                size=Decimal("2.0"),
                side=OrderSide.BUY,
            ),
            Trade(
                symbol="ETH",
                timestamp=960,
                price=Decimal("3000.6"),
                size=Decimal("3.0"),
                side=OrderSide.BUY,
            ),
        ]

        buy_volume, sell_volume = impact_signal._calculate_volumes(trades)

        assert buy_volume == Decimal("5.0")
        assert sell_volume == Decimal("0")

    def test_calculate_volumes_sell_only(self, impact_signal):
        """测试纯卖出成交量计算"""
        trades = [
            Trade(
                symbol="ETH",
                timestamp=950,
                price=Decimal("3000.5"),
                size=Decimal("2.0"),
                side=OrderSide.SELL,
            ),
            Trade(
                symbol="ETH",
                timestamp=960,
                price=Decimal("3000.4"),
                size=Decimal("1.5"),
                side=OrderSide.SELL,
            ),
        ]

        buy_volume, sell_volume = impact_signal._calculate_volumes(trades)

        assert buy_volume == Decimal("0")
        assert sell_volume == Decimal("3.5")

    def test_calculate_volumes_mixed(self, impact_signal):
        """测试混合成交量计算"""
        trades = [
            Trade(
                symbol="ETH",
                timestamp=950,
                price=Decimal("3000.5"),
                size=Decimal("2.0"),
                side=OrderSide.BUY,
            ),
            Trade(
                symbol="ETH",
                timestamp=960,
                price=Decimal("3000.4"),
                size=Decimal("1.5"),
                side=OrderSide.SELL,
            ),
            Trade(
                symbol="ETH",
                timestamp=970,
                price=Decimal("3000.6"),
                size=Decimal("1.0"),
                side=OrderSide.BUY,
            ),
        ]

        buy_volume, sell_volume = impact_signal._calculate_volumes(trades)

        assert buy_volume == Decimal("3.0")
        assert sell_volume == Decimal("1.5")

    def test_calculate_volumes_zero(self, impact_signal):
        """测试零成交量"""
        trades = []

        buy_volume, sell_volume = impact_signal._calculate_volumes(trades)

        assert buy_volume == Decimal("0")
        assert sell_volume == Decimal("0")


# ==================== 边缘情况测试 ====================


class TestImpactEdgeCases:
    """测试边缘情况"""

    def test_zero_total_volume(self, impact_signal):
        """测试总成交量为零（理论上不应出现）"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1000,
            bids=[Level(price=Decimal("3000"), size=Decimal("10"))],
            asks=[Level(price=Decimal("3001"), size=Decimal("12"))],
            mid_price=Decimal("3000.5"),
            trades=[
                Trade(
                    symbol="ETH",
                    timestamp=950,
                    price=Decimal("3000.5"),
                    size=Decimal("0"),  # 零成交量
                    side=OrderSide.BUY,
                )
            ],
        )

        result = impact_signal.calculate(market_data)

        # 应该返回 0 而不是崩溃
        assert result == 0.0

    def test_large_volume_imbalance(self, impact_signal):
        """测试极端不平衡"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1000,
            bids=[Level(price=Decimal("3000"), size=Decimal("10"))],
            asks=[Level(price=Decimal("3001"), size=Decimal("12"))],
            mid_price=Decimal("3000.5"),
            trades=[
                Trade(
                    symbol="ETH",
                    timestamp=950,
                    price=Decimal("3000.5"),
                    size=Decimal("1000.0"),
                    side=OrderSide.BUY,
                ),
                Trade(
                    symbol="ETH",
                    timestamp=960,
                    price=Decimal("3000.4"),
                    size=Decimal("0.1"),
                    side=OrderSide.SELL,
                ),
            ],
        )

        result = impact_signal.calculate(market_data)

        # 应该接近 1.0
        assert result > 0.99

    def test_performance_many_trades(self, impact_signal):
        """测试大量成交的性能"""
        # 生成 1000 笔成交
        trades = [
            Trade(
                symbol="ETH",
                timestamp=950 + i,
                price=Decimal("3000.5"),
                size=Decimal("1.0"),
                side=OrderSide.BUY if i % 2 == 0 else OrderSide.SELL,
            )
            for i in range(1000)
        ]

        market_data = MarketData(
            symbol="ETH",
            timestamp=2000,
            bids=[Level(price=Decimal("3000"), size=Decimal("10"))],
            asks=[Level(price=Decimal("3001"), size=Decimal("12"))],
            mid_price=Decimal("3000.5"),
            trades=trades,
        )

        import time
        start = time.time()
        result = impact_signal.calculate(market_data)
        latency_ms = (time.time() - start) * 1000

        # 应该在 5ms 内完成
        assert latency_ms < 5.0
        # 买卖平衡，应接近 0
        assert abs(result) < 0.1

    def test_calculation_exception(self, impact_signal, mocker):
        """测试异常处理"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1000,
            bids=[Level(price=Decimal("3000"), size=Decimal("10"))],
            asks=[Level(price=Decimal("3001"), size=Decimal("12"))],
            mid_price=Decimal("3000.5"),
            trades=[
                Trade(
                    symbol="ETH",
                    timestamp=950,
                    price=Decimal("3000.5"),
                    size=Decimal("2.0"),
                    side=OrderSide.BUY,
                )
            ],
        )

        # Mock _calculate_volumes 抛出异常
        mocker.patch.object(
            impact_signal,
            "_calculate_volumes",
            side_effect=Exception("Mock error"),
        )

        # 应该捕获异常并返回 0
        result = impact_signal.calculate(market_data)

        assert result == 0.0


# ==================== 配置验证测试 ====================


class TestImpactValidation:
    """测试配置验证"""

    def test_validate_valid_config(self):
        """测试有效配置"""
        signal = ImpactSignal(window_ms=100, weight=0.5)

        assert signal.validate() is True

    def test_validate_invalid_window_zero(self):
        """测试无效窗口（零）"""
        signal = ImpactSignal(window_ms=0, weight=0.5)

        assert signal.validate() is False

    def test_validate_invalid_window_negative(self):
        """测试无效窗口（负数）"""
        signal = ImpactSignal(window_ms=-100, weight=0.5)

        assert signal.validate() is False

    def test_validate_invalid_weight_negative(self):
        """测试无效权重（负数）"""
        signal = ImpactSignal(window_ms=100, weight=-0.1)

        assert signal.validate() is False

    def test_validate_invalid_weight_too_large(self):
        """测试无效权重（>1）"""
        signal = ImpactSignal(window_ms=100, weight=1.5)

        assert signal.validate() is False

    def test_repr(self):
        """测试字符串表示"""
        signal = ImpactSignal(window_ms=200, weight=0.4)

        repr_str = repr(signal)

        assert "ImpactSignal" in repr_str
        assert "200" in repr_str
        assert "0.4" in repr_str
