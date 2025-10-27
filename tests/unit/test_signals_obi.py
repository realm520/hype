"""OBI (Order Book Imbalance) 信号测试

测试 OBI 信号的核心功能、边缘情况和配置验证。
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from src.core.types import Level, MarketData
from src.signals.obi import OBISignal

# ==================== Fixtures ====================


@pytest.fixture
def obi_signal():
    """标准 OBI 信号实例（加权）"""
    return OBISignal(levels=5, weight=0.4, use_weighted=True)


@pytest.fixture
def obi_signal_unweighted():
    """非加权 OBI 信号实例"""
    return OBISignal(levels=5, weight=0.4, use_weighted=False)


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
            Level(price=Decimal("2998.5"), size=Decimal("4.0")),
            Level(price=Decimal("2998.0"), size=Decimal("2.0")),
        ],
        asks=[
            Level(price=Decimal("3000.5"), size=Decimal("10.0")),
            Level(price=Decimal("3001.0"), size=Decimal("8.0")),
            Level(price=Decimal("3001.5"), size=Decimal("6.0")),
            Level(price=Decimal("3002.0"), size=Decimal("4.0")),
            Level(price=Decimal("3002.5"), size=Decimal("2.0")),
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
            Level(price=Decimal("3000.0"), size=Decimal("50.0")),
            Level(price=Decimal("2999.5"), size=Decimal("40.0")),
            Level(price=Decimal("2999.0"), size=Decimal("30.0")),
            Level(price=Decimal("2998.5"), size=Decimal("20.0")),
            Level(price=Decimal("2998.0"), size=Decimal("10.0")),
        ],
        asks=[
            Level(price=Decimal("3000.5"), size=Decimal("5.0")),
            Level(price=Decimal("3001.0"), size=Decimal("4.0")),
            Level(price=Decimal("3001.5"), size=Decimal("3.0")),
            Level(price=Decimal("3002.0"), size=Decimal("2.0")),
            Level(price=Decimal("3002.5"), size=Decimal("1.0")),
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
            Level(price=Decimal("3000.0"), size=Decimal("5.0")),
            Level(price=Decimal("2999.5"), size=Decimal("4.0")),
            Level(price=Decimal("2999.0"), size=Decimal("3.0")),
            Level(price=Decimal("2998.5"), size=Decimal("2.0")),
            Level(price=Decimal("2998.0"), size=Decimal("1.0")),
        ],
        asks=[
            Level(price=Decimal("3000.5"), size=Decimal("50.0")),
            Level(price=Decimal("3001.0"), size=Decimal("40.0")),
            Level(price=Decimal("3001.5"), size=Decimal("30.0")),
            Level(price=Decimal("3002.0"), size=Decimal("20.0")),
            Level(price=Decimal("3002.5"), size=Decimal("10.0")),
        ],
        trades=[],
        mid_price=Decimal("3000.25"),
    )


# ==================== 基础功能测试 ====================


class TestOBIBasics:
    """测试 OBI 基础功能"""

    def test_initialization(self):
        """测试初始化"""
        signal = OBISignal(levels=5, weight=0.4, use_weighted=True)

        assert signal.levels == 5
        assert signal.weight == 0.4
        assert signal.use_weighted is True
        assert signal.get_weight() == 0.4
        assert signal._last_value is None

    def test_balanced_scenario_weighted(self, obi_signal, sample_market_data):
        """测试平衡场景（加权）

        加权 OBI：
        Bid Volume = 10*5 + 8*4 + 6*3 + 4*2 + 2*1 = 50 + 32 + 18 + 8 + 2 = 110
        Ask Volume = 10*5 + 8*4 + 6*3 + 4*2 + 2*1 = 50 + 32 + 18 + 8 + 2 = 110
        OBI = (110 - 110) / (110 + 110) = 0
        """
        result = obi_signal.calculate(sample_market_data)

        assert isinstance(result, float)
        assert abs(result) < 0.01  # 平衡市场，OBI 接近 0

    def test_balanced_scenario_unweighted(self, obi_signal_unweighted, sample_market_data):
        """测试平衡场景（非加权）

        非加权 OBI：
        Bid Volume = 10 + 8 + 6 + 4 + 2 = 30
        Ask Volume = 10 + 8 + 6 + 4 + 2 = 30
        OBI = (30 - 30) / (30 + 30) = 0
        """
        result = obi_signal_unweighted.calculate(sample_market_data)

        assert isinstance(result, float)
        assert abs(result) < 0.01  # 平衡市场，OBI 接近 0

    def test_bid_heavy_scenario_weighted(self, obi_signal, bid_heavy_market_data):
        """测试买盘压力大的场景（加权）

        加权 OBI：
        Bid Volume = 50*5 + 40*4 + 30*3 + 20*2 + 10*1 = 250 + 160 + 90 + 40 + 10 = 550
        Ask Volume = 5*5 + 4*4 + 3*3 + 2*2 + 1*1 = 25 + 16 + 9 + 4 + 1 = 55
        OBI = (550 - 55) / (550 + 55) = 495 / 605 ≈ 0.818
        """
        result = obi_signal.calculate(bid_heavy_market_data)

        assert isinstance(result, float)
        assert result > 0.8  # 买盘压力大，OBI 为正且较大
        assert result < 0.85

    def test_bid_heavy_scenario_unweighted(self, obi_signal_unweighted, bid_heavy_market_data):
        """测试买盘压力大的场景（非加权）

        非加权 OBI：
        Bid Volume = 50 + 40 + 30 + 20 + 10 = 150
        Ask Volume = 5 + 4 + 3 + 2 + 1 = 15
        OBI = (150 - 15) / (150 + 15) = 135 / 165 ≈ 0.818
        """
        result = obi_signal_unweighted.calculate(bid_heavy_market_data)

        assert isinstance(result, float)
        assert result > 0.8  # 买盘压力大，OBI 为正且较大
        assert result < 0.85

    def test_ask_heavy_scenario_weighted(self, obi_signal, ask_heavy_market_data):
        """测试卖盘压力大的场景（加权）

        加权 OBI：
        Bid Volume = 5*5 + 4*4 + 3*3 + 2*2 + 1*1 = 25 + 16 + 9 + 4 + 1 = 55
        Ask Volume = 50*5 + 40*4 + 30*3 + 20*2 + 10*1 = 250 + 160 + 90 + 40 + 10 = 550
        OBI = (55 - 550) / (55 + 550) = -495 / 605 ≈ -0.818
        """
        result = obi_signal.calculate(ask_heavy_market_data)

        assert isinstance(result, float)
        assert result < -0.8  # 卖盘压力大，OBI 为负且较大
        assert result > -0.85

    def test_ask_heavy_scenario_unweighted(self, obi_signal_unweighted, ask_heavy_market_data):
        """测试卖盘压力大的场景（非加权）

        非加权 OBI：
        Bid Volume = 5 + 4 + 3 + 2 + 1 = 15
        Ask Volume = 50 + 40 + 30 + 20 + 10 = 150
        OBI = (15 - 150) / (15 + 150) = -135 / 165 ≈ -0.818
        """
        result = obi_signal_unweighted.calculate(ask_heavy_market_data)

        assert isinstance(result, float)
        assert result < -0.8  # 卖盘压力大，OBI 为负且较大
        assert result > -0.85

    def test_levels_parameter(self):
        """测试不同档位数的影响"""
        signal_3 = OBISignal(levels=3, weight=0.4)
        signal_10 = OBISignal(levels=10, weight=0.4)

        market_data = MarketData(
            symbol="ETH",
            timestamp=1700000000000,
            bids=[Level(price=Decimal(f"{3000 - i * 0.5}"), size=Decimal(f"{10 - i}")) for i in range(15)],
            asks=[Level(price=Decimal(f"{3001 + i * 0.5}"), size=Decimal(f"{10 - i}")) for i in range(15)],
            trades=[],
            mid_price=Decimal("3000.5"),
        )

        result_3 = signal_3.calculate(market_data)
        result_10 = signal_10.calculate(market_data)

        # 不同档位数会影响结果
        assert isinstance(result_3, float)
        assert isinstance(result_10, float)

    def test_caching_last_value(self, obi_signal, sample_market_data):
        """测试 _last_value 缓存"""
        result1 = obi_signal.calculate(sample_market_data)
        result2 = obi_signal.calculate(sample_market_data)

        assert obi_signal._last_value == result1
        assert result1 == result2


# ==================== 边缘情况测试 ====================


class TestOBIEdgeCases:
    """测试边缘情况"""

    def test_empty_bids(self, obi_signal):
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

        result = obi_signal.calculate(market_data)

        # 空买盘应该返回 0.0
        assert result == 0.0

    def test_empty_asks(self, obi_signal):
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

        result = obi_signal.calculate(market_data)

        # 空卖盘应该返回 0.0
        assert result == 0.0

    def test_empty_bids_and_asks(self, obi_signal):
        """测试买盘和卖盘都为空"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1700000000000,
            bids=[],
            asks=[],
            trades=[],
            mid_price=Decimal("3000.25"),
        )

        result = obi_signal.calculate(market_data)

        # 买卖盘都为空应该返回 0.0
        assert result == 0.0

    def test_zero_total_volume(self, obi_signal):
        """测试总量为零"""
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

        result = obi_signal.calculate(market_data)

        # 总量为零应该返回 0.0
        assert result == 0.0

    def test_less_levels_than_requested_weighted(self, obi_signal):
        """测试订单簿档位少于请求档位（加权）"""
        market_data = MarketData(
            symbol="ETH",
            timestamp=1700000000000,
            bids=[
                Level(price=Decimal("3000.0"), size=Decimal("10.0")),
                Level(price=Decimal("2999.5"), size=Decimal("8.0")),
            ],  # 只有2档
            asks=[
                Level(price=Decimal("3000.5"), size=Decimal("10.0")),
                Level(price=Decimal("3001.0"), size=Decimal("8.0")),
            ],  # 只有2档
            trades=[],
            mid_price=Decimal("3000.25"),
        )

        result = obi_signal.calculate(market_data)

        # 应该只使用可用的档位
        assert isinstance(result, float)
        assert abs(result) < 0.1  # 平衡市场

    def test_exception_handling(self, obi_signal, sample_market_data):
        """测试异常处理"""
        # Mock Decimal 计算抛出异常
        with patch("src.signals.obi.Decimal", side_effect=Exception("Test error")):
            result = obi_signal.calculate(sample_market_data)

            # 异常时应该返回 0.0
            assert result == 0.0


# ==================== 配置验证测试 ====================


class TestOBIValidation:
    """测试配置验证"""

    def test_valid_configuration(self):
        """测试有效配置"""
        signal = OBISignal(levels=5, weight=0.4, use_weighted=True)

        assert signal.validate() is True

    def test_invalid_weight_negative(self):
        """测试负权重"""
        signal = OBISignal(levels=5, weight=-0.5, use_weighted=True)

        assert signal.validate() is False

    def test_invalid_weight_too_large(self):
        """测试权重过大"""
        signal = OBISignal(levels=5, weight=1.5, use_weighted=True)

        assert signal.validate() is False

    def test_invalid_levels_zero(self):
        """测试 levels 为零"""
        signal = OBISignal(levels=0, weight=0.4, use_weighted=True)

        assert signal.validate() is False

    def test_invalid_levels_negative(self):
        """测试 levels 为负"""
        signal = OBISignal(levels=-5, weight=0.4, use_weighted=True)

        assert signal.validate() is False

    def test_valid_edge_weight(self):
        """测试边界权重（0 和 1）"""
        signal_zero = OBISignal(levels=5, weight=0.0, use_weighted=True)
        signal_one = OBISignal(levels=5, weight=1.0, use_weighted=True)

        assert signal_zero.validate() is True
        assert signal_one.validate() is True


# ==================== 性能监控测试 ====================


class TestOBIPerformance:
    """测试性能监控"""

    def test_normal_performance(self, obi_signal, sample_market_data):
        """测试正常性能"""
        # 正常计算不应该触发性能警告
        result = obi_signal.calculate(sample_market_data)

        assert isinstance(result, float)
        assert obi_signal.last_value == result

    @patch("src.signals.obi.logger")
    def test_slow_calculation_warning(self, mock_logger, obi_signal, sample_market_data):
        """测试慢计算警告"""
        # Mock time.time 模拟慢计算
        with patch("time.time") as mock_time:
            mock_time.side_effect = [0.0, 0.002]  # 2ms 计算时间

            result = obi_signal.calculate(sample_market_data)

            # 应该触发性能警告（> 1ms）
            assert mock_logger.warning.called


# ==================== 属性测试 ====================


class TestOBIProperties:
    """测试 OBI 属性"""

    def test_get_weight(self, obi_signal):
        """测试获取权重"""
        assert obi_signal.get_weight() == 0.4

    def test_last_value_property(self, obi_signal, sample_market_data):
        """测试 last_value 属性"""
        # 初始为 None
        assert obi_signal.last_value is None

        # 计算后应该有值
        result = obi_signal.calculate(sample_market_data)
        assert obi_signal.last_value == result
        assert isinstance(obi_signal.last_value, float)

    def test_repr(self, obi_signal):
        """测试字符串表示"""
        repr_str = repr(obi_signal)

        assert "OBISignal" in repr_str
        assert "levels=5" in repr_str
        assert "weight=0.4" in repr_str
        assert "weighted=True" in repr_str  # __repr__ 使用 weighted 而不是 use_weighted

    def test_normalize_function(self, obi_signal):
        """测试归一化函数"""
        # 测试归一化到 [-1, 1]
        assert obi_signal._normalize(0.5) == 0.5
        assert obi_signal._normalize(2.0) == 1.0  # 超过最大值
        assert obi_signal._normalize(-2.0) == -1.0  # 低于最小值
        assert obi_signal._normalize(0.0) == 0.0
