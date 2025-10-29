"""Microprice 信号测试

测试 Microprice 信号的核心功能、边缘情况和配置验证。
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from src.core.types import Level, MarketData
from src.signals.microprice import MicropriceSignal

# ==================== Fixtures ====================


@pytest.fixture
def microprice_signal():
    """标准 Microprice 信号实例"""
    return MicropriceSignal(weight=0.3, scale_factor=100.0)


@pytest.fixture
def sample_market_data():
    """示例市场数据 - 平衡场景"""
    return MarketData(
        symbol="ETH",
        timestamp=1700000000000,
        bids=[
            Level(price=Decimal("3000.0"), size=Decimal("10.0")),
            Level(price=Decimal("2999.5"), size=Decimal("8.0")),
            Level(price=Decimal("2999.0"), size=Decimal("6.0")),
        ],
        asks=[
            Level(price=Decimal("3000.5"), size=Decimal("10.0")),
            Level(price=Decimal("3001.0"), size=Decimal("8.0")),
            Level(price=Decimal("3001.5"), size=Decimal("6.0")),
        ],
        trades=[],
        mid_price=Decimal("3000.25"),
    )


@pytest.fixture
def bid_heavy_market_data():
    """买盘压力大的市场数据"""
    return MarketData(
        symbol="ETH",
        timestamp=1700000000000,
        bids=[
            Level(price=Decimal("3000.0"), size=Decimal("50.0")),  # 大买盘
            Level(price=Decimal("2999.5"), size=Decimal("30.0")),
            Level(price=Decimal("2999.0"), size=Decimal("20.0")),
        ],
        asks=[
            Level(price=Decimal("3000.5"), size=Decimal("5.0")),  # 小卖盘
            Level(price=Decimal("3001.0"), size=Decimal("3.0")),
            Level(price=Decimal("3001.5"), size=Decimal("2.0")),
        ],
        trades=[],
        mid_price=Decimal("3000.25"),
    )


@pytest.fixture
def ask_heavy_market_data():
    """卖盘压力大的市场数据"""
    return MarketData(
        symbol="ETH",
        timestamp=1700000000000,
        bids=[
            Level(price=Decimal("3000.0"), size=Decimal("5.0")),  # 小买盘
            Level(price=Decimal("2999.5"), size=Decimal("3.0")),
            Level(price=Decimal("2999.0"), size=Decimal("2.0")),
        ],
        asks=[
            Level(price=Decimal("3000.5"), size=Decimal("50.0")),  # 大卖盘
            Level(price=Decimal("3001.0"), size=Decimal("30.0")),
            Level(price=Decimal("3001.5"), size=Decimal("20.0")),
        ],
        trades=[],
        mid_price=Decimal("3000.25"),
    )


# ==================== 基础功能测试 ====================


class TestMicropriceBasics:
    """测试 Microprice 基础功能"""

    def test_initialization(self):
        """测试初始化"""
        signal = MicropriceSignal(weight=0.3, scale_factor=100.0)

        assert signal.weight == 0.3
        assert signal.scale_factor == 100.0
        assert signal.get_weight() == 0.3
        assert signal._last_value is None

    def test_normal_calculation(self, microprice_signal, sample_market_data):
        """测试正常的 microprice 计算

        Microprice = (BestBid * AskSize + BestAsk * BidSize) / (BidSize + AskSize)
                   = (3000.0 * 10.0 + 3000.5 * 10.0) / (10.0 + 10.0)
                   = (30000 + 30005) / 20
                   = 3000.25

        Signal = (Microprice - MidPrice) / MidPrice * scale_factor
              = (3000.25 - 3000.25) / 3000.25 * 100
              = 0.0
        """
        result = microprice_signal.calculate(sample_market_data)

        # 平衡市场，microprice = mid_price，信号应该接近 0
        assert isinstance(result, float)
        assert abs(result) < 0.01  # 允许小误差
        assert microprice_signal._last_value == result

    def test_bid_heavy_scenario(self, microprice_signal, bid_heavy_market_data):
        """测试买盘压力大的场景

        Microprice = (3000.0 * 5.0 + 3000.5 * 50.0) / (50.0 + 5.0)
                   = (15000 + 150025) / 55
                   = 165025 / 55
                   ≈ 3000.4545

        Signal = (3000.4545 - 3000.25) / 3000.25 * 100
              ≈ 0.000068 * 100
              ≈ 0.0068
        """
        result = microprice_signal.calculate(bid_heavy_market_data)

        # 买盘压力大，microprice 应该 > mid_price，信号为正
        assert isinstance(result, float)
        assert result > 0  # 正信号
        assert 0.006 < result < 0.008  # 预期范围

    def test_ask_heavy_scenario(self, microprice_signal, ask_heavy_market_data):
        """测试卖盘压力大的场景

        Microprice = (3000.0 * 50.0 + 3000.5 * 5.0) / (5.0 + 50.0)
                   = (150000 + 15002.5) / 55
                   = 165002.5 / 55
                   ≈ 3000.0454

        Signal = (3000.0454 - 3000.25) / 3000.25 * 100
              ≈ -0.000068 * 100
              ≈ -0.0068
        """
        result = microprice_signal.calculate(ask_heavy_market_data)

        # 卖盘压力大，microprice 应该 < mid_price，信号为负
        assert isinstance(result, float)
        assert result < 0  # 负信号
        assert -0.008 < result < -0.006  # 预期范围

    def test_balanced_scenario(self, microprice_signal, sample_market_data):
        """测试平衡场景"""
        result = microprice_signal.calculate(sample_market_data)

        # 平衡市场，信号接近 0
        assert abs(result) < 0.1

    def test_scale_factor_impact(self, sample_market_data):
        """测试 scale_factor 对信号的影响"""
        signal_100 = MicropriceSignal(weight=0.3, scale_factor=100.0)
        signal_1000 = MicropriceSignal(weight=0.3, scale_factor=1000.0)

        result_100 = signal_100.calculate(sample_market_data)
        result_1000 = signal_1000.calculate(sample_market_data)

        # scale_factor 越大，信号值越大
        assert abs(result_1000) == pytest.approx(abs(result_100) * 10, rel=0.01)

    def test_caching_last_value(self, microprice_signal, sample_market_data):
        """测试 _last_value 缓存"""
        result1 = microprice_signal.calculate(sample_market_data)
        result2 = microprice_signal.calculate(sample_market_data)

        assert microprice_signal._last_value == result1
        assert result1 == result2


# ==================== 边缘情况测试 ====================


class TestMicropriceEdgeCases:
    """测试边缘情况"""

    def test_empty_bids(self, microprice_signal):
        """测试空买盘"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1700000000000,
            bids=[],
            asks=[
                Level(price=Decimal("3000.5"), size=Decimal("10.0")),
            ],
            trades=[],
            mid_price=Decimal("3000.25"),
        )

        result = microprice_signal.calculate(market_data)

        # 空买盘应该返回 0.0
        assert result == 0.0

    def test_empty_asks(self, microprice_signal):
        """测试空卖盘"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1700000000000,
            bids=[
                Level(price=Decimal("3000.0"), size=Decimal("10.0")),
            ],
            asks=[],
            trades=[],
            mid_price=Decimal("3000.25"),
        )

        result = microprice_signal.calculate(market_data)

        # 空卖盘应该返回 0.0
        assert result == 0.0

    def test_empty_bids_and_asks(self, microprice_signal):
        """测试买盘和卖盘都为空"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1700000000000,
            bids=[],
            asks=[],
            trades=[],
            mid_price=Decimal("3000.25"),
        )

        result = microprice_signal.calculate(market_data)

        # 买卖盘都为空应该返回 0.0
        assert result == 0.0

    def test_zero_bid_size(self, microprice_signal):
        """测试买盘数量为零

        当 bid_size = 0 时：
        Microprice = (3000.0 * 10.0 + 3000.5 * 0) / (0 + 10.0) = 3000.0
        Signal = (3000.0 - 3000.25) / 3000.25 * 100 ≈ -0.0083
        """
        market_data = MarketData(
            symbol="ETH",
            timestamp=1700000000000,
            bids=[
                Level(price=Decimal("3000.0"), size=Decimal("0")),
            ],
            asks=[
                Level(price=Decimal("3000.5"), size=Decimal("10.0")),
            ],
            trades=[],
            mid_price=Decimal("3000.25"),
        )

        result = microprice_signal.calculate(market_data)

        # bid_size 为零时，microprice 偏向 best_bid，信号为负
        assert result < 0
        assert -0.01 < result < -0.008

    def test_zero_ask_size(self, microprice_signal):
        """测试卖盘数量为零

        当 ask_size = 0 时：
        Microprice = (3000.0 * 0 + 3000.5 * 10.0) / (10.0 + 0) = 3000.5
        Signal = (3000.5 - 3000.25) / 3000.25 * 100 ≈ 0.0083
        """
        market_data = MarketData(
            symbol="ETH",
            timestamp=1700000000000,
            bids=[
                Level(price=Decimal("3000.0"), size=Decimal("10.0")),
            ],
            asks=[
                Level(price=Decimal("3000.5"), size=Decimal("0")),
            ],
            trades=[],
            mid_price=Decimal("3000.25"),
        )

        result = microprice_signal.calculate(market_data)

        # ask_size 为零时，microprice 偏向 best_ask，信号为正
        assert result > 0
        assert 0.008 < result < 0.01

    def test_zero_total_size(self, microprice_signal):
        """测试总数量为零"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1700000000000,
            bids=[
                Level(price=Decimal("3000.0"), size=Decimal("0")),
            ],
            asks=[
                Level(price=Decimal("3000.5"), size=Decimal("0")),
            ],
            trades=[],
            mid_price=Decimal("3000.25"),
        )

        result = microprice_signal.calculate(market_data)

        # 总数量为零应该返回 0.0
        assert result == 0.0

    def test_zero_mid_price(self, microprice_signal):
        """测试中间价为零"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1700000000000,
            bids=[
                Level(price=Decimal("3000.0"), size=Decimal("10.0")),
            ],
            asks=[
                Level(price=Decimal("3000.5"), size=Decimal("10.0")),
            ],
            trades=[],
            mid_price=Decimal("0"),
        )

        result = microprice_signal.calculate(market_data)

        # 中间价为零应该返回 0.0
        assert result == 0.0

    def test_exception_handling(self, microprice_signal, sample_market_data):
        """测试异常处理"""
        # Mock Decimal 计算抛出异常
        with patch("src.signals.microprice.Decimal", side_effect=Exception("Test error")):
            result = microprice_signal.calculate(sample_market_data)

            # 异常时应该返回 0.0
            assert result == 0.0


# ==================== 配置验证测试 ====================


class TestMicropriceValidation:
    """测试配置验证"""

    def test_valid_configuration(self):
        """测试有效配置"""
        signal = MicropriceSignal(weight=0.3, scale_factor=100.0)

        assert signal.validate() is True

    def test_invalid_weight_negative(self):
        """测试负权重"""
        signal = MicropriceSignal(weight=-0.5, scale_factor=100.0)

        assert signal.validate() is False

    def test_invalid_weight_too_large(self):
        """测试权重过大"""
        signal = MicropriceSignal(weight=1.5, scale_factor=100.0)

        assert signal.validate() is False

    def test_invalid_scale_factor_zero(self):
        """测试 scale_factor 为零"""
        signal = MicropriceSignal(weight=0.3, scale_factor=0.0)

        assert signal.validate() is False

    def test_invalid_scale_factor_negative(self):
        """测试 scale_factor 为负"""
        signal = MicropriceSignal(weight=0.3, scale_factor=-100.0)

        assert signal.validate() is False

    def test_valid_edge_weight(self):
        """测试边界权重（0 和 1）"""
        signal_zero = MicropriceSignal(weight=0.0, scale_factor=100.0)
        signal_one = MicropriceSignal(weight=1.0, scale_factor=100.0)

        assert signal_zero.validate() is True
        assert signal_one.validate() is True


# ==================== 性能监控测试 ====================


class TestMicropricePerformance:
    """测试性能监控"""

    def test_normal_performance(self, microprice_signal, sample_market_data):
        """测试正常性能"""
        # 正常计算不应该触发性能警告
        result = microprice_signal.calculate(sample_market_data)

        assert isinstance(result, float)
        assert microprice_signal.last_value == result

    @patch("src.signals.microprice.logger")
    def test_slow_calculation_warning(self, mock_logger, microprice_signal, sample_market_data):
        """测试慢计算警告"""
        # Mock time.time 模拟慢计算
        with patch("time.time") as mock_time:
            mock_time.side_effect = [0.0, 0.002]  # 2ms 计算时间

            _ = microprice_signal.calculate(sample_market_data)

            # 应该触发性能警告（> 1ms）
            assert mock_logger.warning.called


# ==================== 属性测试 ====================


class TestMicropriceProperties:
    """测试 Microprice 属性"""

    def test_get_weight(self, microprice_signal):
        """测试获取权重"""
        assert microprice_signal.get_weight() == 0.3

    def test_last_value_property(self, microprice_signal, sample_market_data):
        """测试 last_value 属性"""
        # 初始为 None
        assert microprice_signal.last_value is None

        # 计算后应该有值
        result = microprice_signal.calculate(sample_market_data)
        assert microprice_signal.last_value == result
        assert isinstance(microprice_signal.last_value, float)

    def test_repr(self, microprice_signal):
        """测试字符串表示"""
        repr_str = repr(microprice_signal)

        assert "MicropriceSignal" in repr_str
        assert "weight=0.3" in repr_str
        assert "scale_factor=100.0" in repr_str

    def test_normalize_function(self, microprice_signal):
        """测试归一化函数"""
        # 测试归一化到 [-1, 1]
        assert microprice_signal._normalize(0.5) == 0.5
        assert microprice_signal._normalize(2.0) == 1.0  # 超过最大值
        assert microprice_signal._normalize(-2.0) == -1.0  # 低于最小值
        assert microprice_signal._normalize(0.0) == 0.0
