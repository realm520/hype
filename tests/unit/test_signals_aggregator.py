"""SignalAggregator 测试

测试信号聚合器的核心功能、边缘情况和配置验证。
"""

import itertools
from decimal import Decimal
from unittest.mock import patch

import pytest

from src.core.types import ConfidenceLevel, Level, MarketData, SignalScore
from src.signals.aggregator import SignalAggregator, create_aggregator_from_config
from src.signals.base import BaseSignal
from src.signals.impact import ImpactSignal
from src.signals.microprice import MicropriceSignal
from src.signals.obi import OBISignal

# ==================== Mock Signal ====================


class MockSignal(BaseSignal):
    """Mock 信号用于测试"""

    def __init__(self, weight: float = 1.0, return_value: float = 0.5):
        super().__init__(weight)
        self.return_value = return_value

    def calculate(self, market_data: MarketData) -> float:
        return self.return_value


class InvalidSignal(BaseSignal):
    """总是验证失败的信号"""

    def __init__(self, weight: float = 1.0):
        super().__init__(weight)

    def calculate(self, market_data: MarketData) -> float:
        return 0.0

    def validate(self) -> bool:
        return False


class ErrorSignal(BaseSignal):
    """总是抛出异常的信号"""

    def __init__(self, weight: float = 1.0):
        super().__init__(weight)

    def calculate(self, market_data: MarketData) -> float:
        raise RuntimeError("Signal calculation error")


# ==================== Fixtures ====================


@pytest.fixture
def sample_market_data():
    """示例市场数据"""
    return MarketData(
        symbol="ETH",
        timestamp=1700000000000,
        bids=[
            Level(price=Decimal("3000.0"), size=Decimal("10.0")),
        ],
        asks=[
            Level(price=Decimal("3000.5"), size=Decimal("10.0")),
        ],
        trades=[],
        mid_price=Decimal("3000.25"),
    )


@pytest.fixture
def single_signal_aggregator():
    """单信号聚合器"""
    signals = [MockSignal(weight=1.0, return_value=0.6)]
    return SignalAggregator(signals=signals, theta_1=0.5, theta_2=0.2)


@pytest.fixture
def multi_signal_aggregator():
    """多信号聚合器"""
    signals = [
        MockSignal(weight=0.4, return_value=0.8),  # 高信号
        MockSignal(weight=0.3, return_value=0.3),  # 中信号
        MockSignal(weight=0.3, return_value=0.1),  # 低信号
    ]
    return SignalAggregator(signals=signals, theta_1=0.5, theta_2=0.2)


# ==================== 基础功能测试 ====================


class TestAggregatorBasics:
    """测试聚合器基础功能"""

    def test_initialization(self):
        """测试初始化"""
        signals = [MockSignal(weight=0.5)]
        aggregator = SignalAggregator(
            signals=signals,
            theta_1=0.5,
            theta_2=0.2,
        )

        assert aggregator.signals == signals
        assert aggregator.theta_1 == 0.5
        assert aggregator.theta_2 == 0.2
        assert len(aggregator.signals) == 1

    def test_initialization_with_invalid_signal(self):
        """测试初始化时信号验证失败"""
        signals = [InvalidSignal(weight=0.5)]

        with pytest.raises(ValueError, match="Invalid signal configuration"):
            SignalAggregator(signals=signals, theta_1=0.5, theta_2=0.2)

    def test_single_signal_aggregation(self, single_signal_aggregator, sample_market_data):
        """测试单信号聚合

        Signal = 0.6
        Confidence = HIGH (> 0.5)
        """
        result = single_signal_aggregator.calculate(sample_market_data)

        assert isinstance(result, SignalScore)
        assert result.value == 0.6
        assert result.confidence == ConfidenceLevel.HIGH
        assert len(result.individual_scores) == 1
        assert result.individual_scores[0] == 0.6
        assert result.timestamp == 1700000000000

    def test_multi_signal_aggregation(self, multi_signal_aggregator, sample_market_data):
        """测试多信号聚合

        Weighted Average = (0.8*0.4 + 0.3*0.3 + 0.1*0.3) / (0.4+0.3+0.3)
                        = (0.32 + 0.09 + 0.03) / 1.0
                        = 0.44
        Confidence = MEDIUM (0.2 < 0.44 < 0.5)
        """
        result = multi_signal_aggregator.calculate(sample_market_data)

        assert isinstance(result, SignalScore)
        assert 0.43 < result.value < 0.45  # 允许浮点误差
        assert result.confidence == ConfidenceLevel.MEDIUM
        assert len(result.individual_scores) == 3
        assert result.individual_scores == [0.8, 0.3, 0.1]

    def test_confidence_level_high(self, sample_market_data):
        """测试高置信度分级"""
        signals = [MockSignal(weight=1.0, return_value=0.8)]
        aggregator = SignalAggregator(signals=signals, theta_1=0.5, theta_2=0.2)

        result = aggregator.calculate(sample_market_data)

        assert result.confidence == ConfidenceLevel.HIGH
        assert result.value > 0.5

    def test_confidence_level_medium(self, sample_market_data):
        """测试中等置信度分级"""
        signals = [MockSignal(weight=1.0, return_value=0.35)]
        aggregator = SignalAggregator(signals=signals, theta_1=0.5, theta_2=0.2)

        result = aggregator.calculate(sample_market_data)

        assert result.confidence == ConfidenceLevel.MEDIUM
        assert 0.2 < result.value <= 0.5

    def test_confidence_level_low(self, sample_market_data):
        """测试低置信度分级"""
        signals = [MockSignal(weight=1.0, return_value=0.1)]
        aggregator = SignalAggregator(signals=signals, theta_1=0.5, theta_2=0.2)

        result = aggregator.calculate(sample_market_data)

        assert result.confidence == ConfidenceLevel.LOW
        assert result.value <= 0.2

    def test_negative_signal_high(self, sample_market_data):
        """测试负信号高置信度"""
        signals = [MockSignal(weight=1.0, return_value=-0.8)]
        aggregator = SignalAggregator(signals=signals, theta_1=0.5, theta_2=0.2)

        result = aggregator.calculate(sample_market_data)

        assert result.confidence == ConfidenceLevel.HIGH
        assert result.value < -0.5


# ==================== 边缘情况测试 ====================


class TestAggregatorEdgeCases:
    """测试边缘情况"""

    def test_single_signal_error(self, sample_market_data):
        """测试单个信号出错"""
        signals = [
            MockSignal(weight=0.5, return_value=0.6),
            ErrorSignal(weight=0.5),  # 这个会出错
        ]
        aggregator = SignalAggregator(signals=signals, theta_1=0.5, theta_2=0.2)

        result = aggregator.calculate(sample_market_data)

        # 出错的信号完全被忽略，不参与加权计算
        # 只使用正常信号：Weighted = 0.6*0.5 / 0.5 = 0.6
        assert isinstance(result, SignalScore)
        assert result.value == 0.6
        assert result.confidence == ConfidenceLevel.HIGH
        assert result.individual_scores == [0.6, 0.0]

    def test_all_signals_error(self, sample_market_data):
        """测试所有信号都出错"""
        signals = [
            ErrorSignal(weight=0.5),
            ErrorSignal(weight=0.5),
        ]
        aggregator = SignalAggregator(signals=signals, theta_1=0.5, theta_2=0.2)

        result = aggregator.calculate(sample_market_data)

        # 所有信号都出错，聚合值应该为 0
        assert result.value == 0.0
        assert result.confidence == ConfidenceLevel.LOW
        assert result.individual_scores == [0.0, 0.0]

    def test_zero_weight_sum(self, sample_market_data):
        """测试权重和为零"""
        # 创建权重为 0 的信号
        signals = [MockSignal(weight=0.0, return_value=0.8)]
        aggregator = SignalAggregator(signals=signals, theta_1=0.5, theta_2=0.2)

        result = aggregator.calculate(sample_market_data)

        # weight_sum = 0，应该返回 0.0
        assert result.value == 0.0
        assert result.confidence == ConfidenceLevel.LOW

    def test_aggregator_exception_handling(self, sample_market_data):
        """测试聚合器整体异常处理"""
        signals = [MockSignal(weight=1.0, return_value=0.6)]
        aggregator = SignalAggregator(signals=signals, theta_1=0.5, theta_2=0.2)

        # Mock calculate 内部抛出异常
        with patch.object(
            aggregator.signals[0], "calculate", side_effect=Exception("Unexpected error")
        ):
            result = aggregator.calculate(sample_market_data)

            # 异常时应该返回零信号
            assert result.value == 0.0
            assert result.confidence == ConfidenceLevel.LOW

    def test_empty_individual_scores(self, sample_market_data):
        """测试空信号列表（虽然初始化时会验证）"""
        # 直接构造一个空信号列表的场景
        signals = [MockSignal(weight=1.0, return_value=0.0)]
        aggregator = SignalAggregator(signals=signals, theta_1=0.5, theta_2=0.2)

        result = aggregator.calculate(sample_market_data)

        assert len(result.individual_scores) == 1


# ==================== 配置验证测试 ====================


class TestAggregatorValidation:
    """测试配置验证"""

    def test_valid_thresholds(self):
        """测试有效阈值"""
        signals = [MockSignal(weight=1.0)]
        aggregator = SignalAggregator(signals=signals, theta_1=0.5, theta_2=0.2)

        assert aggregator.validate_thresholds() is True

    def test_invalid_theta_1_less_than_theta_2(self):
        """测试 theta_1 <= theta_2"""
        signals = [MockSignal(weight=1.0)]
        aggregator = SignalAggregator(signals=signals, theta_1=0.2, theta_2=0.5)

        assert aggregator.validate_thresholds() is False

    def test_invalid_theta_1_equal_theta_2(self):
        """测试 theta_1 == theta_2"""
        signals = [MockSignal(weight=1.0)]
        aggregator = SignalAggregator(signals=signals, theta_1=0.3, theta_2=0.3)

        assert aggregator.validate_thresholds() is False

    def test_invalid_theta_1_out_of_range_high(self):
        """测试 theta_1 > 1.0"""
        signals = [MockSignal(weight=1.0)]
        aggregator = SignalAggregator(signals=signals, theta_1=1.5, theta_2=0.2)

        assert aggregator.validate_thresholds() is False

    def test_invalid_theta_1_out_of_range_low(self):
        """测试 theta_1 < 0"""
        signals = [MockSignal(weight=1.0)]
        aggregator = SignalAggregator(signals=signals, theta_1=-0.1, theta_2=0.2)

        assert aggregator.validate_thresholds() is False

    def test_invalid_theta_2_out_of_range_high(self):
        """测试 theta_2 > 1.0"""
        signals = [MockSignal(weight=1.0)]
        aggregator = SignalAggregator(signals=signals, theta_1=0.5, theta_2=1.5)

        assert aggregator.validate_thresholds() is False

    def test_invalid_theta_2_out_of_range_low(self):
        """测试 theta_2 < 0"""
        signals = [MockSignal(weight=1.0)]
        aggregator = SignalAggregator(signals=signals, theta_1=0.5, theta_2=-0.1)

        assert aggregator.validate_thresholds() is False

    def test_valid_edge_thresholds(self):
        """测试边界阈值"""
        signals = [MockSignal(weight=1.0)]

        # theta_1 = 1.0, theta_2 = 0.0 是有效的
        aggregator1 = SignalAggregator(signals=signals, theta_1=1.0, theta_2=0.0)
        assert aggregator1.validate_thresholds() is True

        # theta_1 = 0.5, theta_2 = 0.0 是有效的
        aggregator2 = SignalAggregator(signals=signals, theta_1=0.5, theta_2=0.0)
        assert aggregator2.validate_thresholds() is True


# ==================== Factory 函数测试 ====================


class TestAggregatorFactory:
    """测试 factory 函数"""

    def test_create_from_config_all_signals(self):
        """测试从配置创建（包含所有信号）"""
        config = {
            "signals": {
                "obi": {"levels": 5, "weight": 0.4},
                "microprice": {"weight": 0.3},
                "impact": {"window_ms": 100, "weight": 0.3},
            },
            "thresholds": {
                "theta_1": 0.5,
                "theta_2": 0.2,
            },
        }

        aggregator = create_aggregator_from_config(config)

        assert len(aggregator.signals) == 3
        assert aggregator.theta_1 == 0.5
        assert aggregator.theta_2 == 0.2
        assert isinstance(aggregator.signals[0], OBISignal)
        assert isinstance(aggregator.signals[1], MicropriceSignal)
        assert isinstance(aggregator.signals[2], ImpactSignal)

    def test_create_from_config_partial_signals(self):
        """测试从配置创建（部分信号）"""
        config = {
            "signals": {
                "obi": {"levels": 3, "weight": 0.6},
                "microprice": {"weight": 0.4},
            },
            "thresholds": {
                "theta_1": 0.6,
                "theta_2": 0.3,
            },
        }

        aggregator = create_aggregator_from_config(config)

        assert len(aggregator.signals) == 2
        assert aggregator.theta_1 == 0.6
        assert aggregator.theta_2 == 0.3

    def test_create_from_config_default_values(self):
        """测试使用默认值"""
        config = {
            "signals": {
                "obi": {},  # 使用默认值
                "microprice": {},
            },
            "thresholds": {},  # 使用默认阈值
        }

        aggregator = create_aggregator_from_config(config)

        assert len(aggregator.signals) == 2
        assert aggregator.theta_1 == 0.5  # 默认值
        assert aggregator.theta_2 == 0.2  # 默认值

    def test_create_from_config_invalid_thresholds(self):
        """测试无效阈值配置"""
        config = {
            "signals": {
                "obi": {"levels": 5, "weight": 0.4},
            },
            "thresholds": {
                "theta_1": 0.2,  # 无效：< theta_2
                "theta_2": 0.5,
            },
        }

        with pytest.raises(ValueError, match="Invalid aggregator thresholds"):
            create_aggregator_from_config(config)

    def test_create_from_config_empty_signals(self):
        """测试空信号配置"""
        config = {
            "signals": {},  # 没有任何信号
            "thresholds": {
                "theta_1": 0.5,
                "theta_2": 0.2,
            },
        }

        aggregator = create_aggregator_from_config(config)

        assert len(aggregator.signals) == 0


# ==================== 性能测试 ====================


class TestAggregatorPerformance:
    """测试性能监控"""

    def test_normal_performance(self, single_signal_aggregator, sample_market_data):
        """测试正常性能"""
        result = single_signal_aggregator.calculate(sample_market_data)

        assert isinstance(result, SignalScore)

    @patch("src.signals.aggregator.logger")
    def test_slow_calculation_warning(self, mock_logger, single_signal_aggregator, sample_market_data):
        """测试慢计算警告"""
        # Mock time.time 模拟慢计算
        with patch("time.time") as mock_time:
            # 使用 itertools.count 创建无限迭代器，每次递增 6ms
            mock_time.side_effect = itertools.count(0.0, 0.006)

            result = single_signal_aggregator.calculate(sample_market_data)

            # 应该触发性能警告（> 5ms）
            assert mock_logger.warning.called


# ==================== 属性测试 ====================


class TestAggregatorProperties:
    """测试聚合器属性"""

    def test_get_signal_weights(self, multi_signal_aggregator):
        """测试获取信号权重"""
        weights = multi_signal_aggregator.get_signal_weights()

        assert isinstance(weights, dict)
        assert "MockSignal" in weights
        assert len(weights) == 1  # MockSignal 的权重会被覆盖（所有 MockSignal 同名）

    def test_repr(self, multi_signal_aggregator):
        """测试字符串表示"""
        repr_str = repr(multi_signal_aggregator)

        assert "SignalAggregator" in repr_str
        assert "signals=3" in repr_str
        assert "theta_1=0.5" in repr_str
        assert "theta_2=0.2" in repr_str

    def test_determine_confidence_private_method(self, single_signal_aggregator):
        """测试 _determine_confidence 私有方法"""
        # 测试各个置信度等级
        assert single_signal_aggregator._determine_confidence(0.8) == ConfidenceLevel.HIGH
        assert single_signal_aggregator._determine_confidence(-0.8) == ConfidenceLevel.HIGH
        assert single_signal_aggregator._determine_confidence(0.3) == ConfidenceLevel.MEDIUM
        assert single_signal_aggregator._determine_confidence(-0.3) == ConfidenceLevel.MEDIUM
        assert single_signal_aggregator._determine_confidence(0.1) == ConfidenceLevel.LOW
        assert single_signal_aggregator._determine_confidence(-0.1) == ConfidenceLevel.LOW
        assert single_signal_aggregator._determine_confidence(0.0) == ConfidenceLevel.LOW
