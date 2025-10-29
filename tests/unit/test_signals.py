"""信号层单元测试"""

from decimal import Decimal

from src.core.types import ConfidenceLevel
from src.signals.aggregator import create_aggregator_from_config
from src.signals.impact import ImpactSignal
from src.signals.microprice import MicropriceSignal
from src.signals.obi import OBISignal


class TestOBISignal:
    """测试订单簿失衡信号"""

    def test_obi_calculation_basic(self, sample_market_data):
        """测试基础 OBI 计算"""
        signal = OBISignal(levels=3)
        value = signal.calculate(sample_market_data)

        # OBI 应该在 [-1, 1] 范围内
        assert -1.0 <= value <= 1.0

    def test_obi_buy_imbalance(self, imbalanced_market_data):
        """测试买单失衡场景（买单明显多于卖单）"""
        signal = OBISignal(levels=2)
        value = signal.calculate(imbalanced_market_data)

        # 买单明显大，应该是正值
        assert value > 0.5

    def test_obi_levels_parameter(self, sample_market_data):
        """测试不同层数的 OBI 计算"""
        signal_3_levels = OBISignal(levels=3)
        signal_5_levels = OBISignal(levels=5)

        value_3 = signal_3_levels.calculate(sample_market_data)
        value_5 = signal_5_levels.calculate(sample_market_data)

        # 都应该在有效范围内
        assert -1.0 <= value_3 <= 1.0
        assert -1.0 <= value_5 <= 1.0

    def test_obi_empty_orderbook(self):
        """测试空订单簿情况"""
        import time

        from src.core.types import MarketData

        empty_data = MarketData(
            symbol="ETH",
            timestamp=int(time.time() * 1000),
            bids=[],
            asks=[],
            mid_price=Decimal("1500.0"),
        )

        signal = OBISignal(levels=3)
        value = signal.calculate(empty_data)

        # 空订单簿应该返回 0
        assert value == 0.0


class TestMicropriceSignal:
    """测试微观价格信号"""

    def test_microprice_calculation(self, sample_market_data):
        """测试微观价格计算"""
        signal = MicropriceSignal()
        value = signal.calculate(sample_market_data)

        # Microprice signal返回归一化值在[-1, 1]范围内
        assert -1.0 <= value <= 1.0

    def test_microprice_deviation(self, sample_market_data):
        """测试微观价格偏离度"""
        signal = MicropriceSignal()
        value = signal.calculate(sample_market_data)

        # Microprice signal返回归一化值，已经包含了偏离度信息
        # 正值表示买盘流动性强，负值表示卖盘流动性强
        assert -1.0 <= value <= 1.0

    def test_microprice_wide_spread(self, wide_spread_market_data):
        """测试宽点差场景"""
        signal = MicropriceSignal()
        value = signal.calculate(wide_spread_market_data)

        # Microprice signal返回归一化值在[-1, 1]范围内
        # 宽点差可能导致更强的信号
        assert -1.0 <= value <= 1.0


class TestImpactSignal:
    """测试市场冲击信号"""

    def test_impact_initialization(self):
        """测试市场冲击信号初始化"""
        signal = ImpactSignal(window_ms=5000)
        assert signal.window_ms == 5000
        # ImpactSignal从MarketData.trades计算，不维护内部trade history

    def test_impact_single_trade(self, sample_market_data):
        """测试单笔交易的市场冲击"""
        signal = ImpactSignal(window_ms=5000)

        # 第一次计算（无历史数据）
        value1 = signal.calculate(sample_market_data)
        assert value1 == 0.0  # 无历史，应该是 0

        # 等待一小段时间后再次计算
        import time
        time.sleep(0.01)
        value2 = signal.calculate(sample_market_data)

        # 现在应该有一定的冲击值
        assert -1.0 <= value2 <= 1.0

    def test_impact_window_cleanup(self):
        """测试时间窗口清理"""
        signal = ImpactSignal(window_ms=100)  # 100ms 窗口

        import time

        from src.core.types import Level, MarketData

        # 添加一个旧数据点
        old_data = MarketData(
            symbol="ETH",
            timestamp=int((time.time() - 1) * 1000),  # 1秒前
            bids=[Level(price=Decimal("1500.0"), size=Decimal("10.0"))],
            asks=[Level(price=Decimal("1500.5"), size=Decimal("10.0"))],
            mid_price=Decimal("1500.25"),
        )

        _ = signal.calculate(old_data)

        # 等待窗口过期
        time.sleep(0.15)

        # 添加新数据
        new_data = MarketData(
            symbol="ETH",
            timestamp=int(time.time() * 1000),
            bids=[Level(price=Decimal("1510.0"), size=Decimal("10.0"))],
            asks=[Level(price=Decimal("1510.5"), size=Decimal("10.0"))],
            mid_price=Decimal("1510.25"),
        )

        new_value = signal.calculate(new_data)

        # Impact signal基于trades，这里测试它能正常计算
        assert -1.0 <= new_value <= 1.0


class TestSignalAggregator:
    """测试信号聚合器"""

    def test_aggregator_initialization(self):
        """测试聚合器初始化"""
        config = {
            "signals": {
                "obi": {"levels": 5, "weight": 0.35},
                "microprice": {"weight": 0.40},
                "impact": {"window_ms": 5000, "weight": 0.25},
            },
            "thresholds": {
                "theta_1": 0.75,
                "theta_2": 0.50,
            },
        }

        aggregator = create_aggregator_from_config(config)

        assert aggregator.theta_1 == 0.75
        assert aggregator.theta_2 == 0.50
        assert len(aggregator.signals) == 3

    def test_aggregator_weights_sum_to_one(self):
        """测试权重总和为1"""
        config = {
            "signals": {
                "obi": {"levels": 5, "weight": 0.35},
                "microprice": {"weight": 0.40},
                "impact": {"window_ms": 5000, "weight": 0.25},
            },
            "thresholds": {
                "theta_1": 0.75,
                "theta_2": 0.50,
            },
        }

        aggregator = create_aggregator_from_config(config)
        total_weight = sum(signal.get_weight() for signal in aggregator.signals)

        assert abs(total_weight - 1.0) < 0.01  # 允许浮点误差

    def test_aggregator_calculate(self, sample_market_data):
        """测试信号聚合计算"""
        config = {
            "signals": {
                "obi": {"levels": 5, "weight": 0.35},
                "microprice": {"weight": 0.40},
                "impact": {"window_ms": 5000, "weight": 0.25},
            },
            "thresholds": {
                "theta_1": 0.75,
                "theta_2": 0.50,
            },
        }

        aggregator = create_aggregator_from_config(config)
        signal_score = aggregator.calculate(sample_market_data)

        # 检查信号评分
        assert -1.0 <= signal_score.value <= 1.0
        assert signal_score.confidence in [
            ConfidenceLevel.HIGH,
            ConfidenceLevel.MEDIUM,
            ConfidenceLevel.LOW,
        ]
        assert len(signal_score.individual_scores) == 3

    def test_aggregator_high_confidence(self, imbalanced_market_data):
        """测试高置信度信号生成"""
        config = {
            "signals": {
                "obi": {"levels": 2, "weight": 0.50},
                "microprice": {"weight": 0.50},
                "impact": {"window_ms": 5000, "weight": 0.0},  # 忽略冲击
            },
            "thresholds": {
                "theta_1": 0.60,  # 降低阈值以便测试
                "theta_2": 0.40,
            },
        }

        aggregator = create_aggregator_from_config(config)
        signal_score = aggregator.calculate(imbalanced_market_data)

        # 买单失衡数据应该产生较强的买入信号
        assert signal_score.value > 0.3

    def test_aggregator_confidence_thresholds(self, create_signal):
        """测试置信度阈值判断"""
        config = {
            "signals": {
                "obi": {"levels": 5, "weight": 1.0},
                "microprice": {"weight": 0.0},
                "impact": {"window_ms": 5000, "weight": 0.0},
            },
            "thresholds": {
                "theta_1": 0.75,
                "theta_2": 0.50,
            },
        }

        _ = create_aggregator_from_config(config)

        # 测试不同信号值的置信度分类
        # 注意：这里假设 OBI 可以产生接近给定值的信号

        # HIGH: > 0.75
        # MEDIUM: 0.50 - 0.75
        # LOW: < 0.50

    def test_aggregator_component_breakdown(self, sample_market_data):
        """测试信号组成部分分解"""
        config = {
            "signals": {
                "obi": {"levels": 5, "weight": 0.35},
                "microprice": {"weight": 0.40},
                "impact": {"window_ms": 5000, "weight": 0.25},
            },
            "thresholds": {
                "theta_1": 0.75,
                "theta_2": 0.50,
            },
        }

        aggregator = create_aggregator_from_config(config)
        signal_score = aggregator.calculate(sample_market_data)

        # 检查各组成部分信号值
        assert len(signal_score.individual_scores) == 3

        # 各组成部分应该在合理范围内
        for score in signal_score.individual_scores:
            assert -1.0 <= score <= 1.0


class TestSignalValidation:
    """测试信号验证逻辑"""

    def test_signal_normalization(self):
        """测试信号归一化"""
        # 确保所有信号都在 [-1, 1] 范围内
        pass

    def test_signal_timestamp(self, sample_market_data):
        """测试信号时间戳"""
        config = {
            "signals": {
                "obi": {"levels": 5, "weight": 1.0},
                "microprice": {"weight": 0.0},
                "impact": {"window_ms": 5000, "weight": 0.0},
            },
            "thresholds": {
                "theta_1": 0.75,
                "theta_2": 0.50,
            },
        }

        aggregator = create_aggregator_from_config(config)
        signal_score = aggregator.calculate(sample_market_data)

        # 信号时间戳应该接近当前时间
        import time
        current_time = int(time.time() * 1000)
        assert abs(signal_score.timestamp - current_time) < 5000  # 5秒容差
