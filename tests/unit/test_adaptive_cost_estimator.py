"""AdaptiveCostEstimator 单元测试

测试覆盖：
    1. 市场状态调整逻辑
    2. 执行建议生成
    3. 向后兼容性（可替换 DynamicCostEstimator）
    4. 边界条件和异常处理
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from src.analytics.adaptive_cost_estimator import (
    AdaptiveCostEstimate,
    AdaptiveCostEstimator,
)
from src.analytics.market_state_detector import MarketMetrics, MarketState
from src.core.types import Level, MarketData, OrderSide, OrderType


@pytest.fixture
def market_data():
    """创建测试市场数据"""
    return MarketData(
        symbol="BTC",
        timestamp=1609459200000,
        bids=[
            Level(Decimal("50000.0"), Decimal("1.0")),
            Level(Decimal("49990.0"), Decimal("2.0")),
            Level(Decimal("49980.0"), Decimal("3.0")),
            Level(Decimal("49970.0"), Decimal("4.0")),
            Level(Decimal("49960.0"), Decimal("5.0")),
        ],
        asks=[
            Level(Decimal("50010.0"), Decimal("1.0")),
            Level(Decimal("50020.0"), Decimal("2.0")),
            Level(Decimal("50030.0"), Decimal("3.0")),
            Level(Decimal("50040.0"), Decimal("4.0")),
            Level(Decimal("50050.0"), Decimal("5.0")),
        ],
        mid_price=Decimal("50005.0"),
    )


@pytest.fixture
def estimator():
    """创建测试估算器"""
    return AdaptiveCostEstimator()


class TestAdaptiveAdjustment:
    """测试市场状态调整逻辑"""

    def test_normal_market_no_adjustment(self, estimator, market_data):
        """NORMAL 市场状态不调整成本"""
        # Mock MarketStateDetector 返回 NORMAL
        with patch.object(
            estimator.market_state_detector,
            "detect_state",
            return_value=MarketMetrics(
                volatility=0.01,
                liquidity_score=0.8,
                spread_bps=3.0,
                price_reversals=2,
                detected_state=MarketState.NORMAL,
            ),
        ):
            result = estimator.estimate_cost(
                order_type=OrderType.LIMIT,
                side=OrderSide.BUY,
                size=Decimal("0.1"),
                market_data=market_data,
            )

            # 验证市场状态
            assert result.market_state == MarketState.NORMAL
            assert result.adjustment_factor == 1.0

            # 验证无执行建议
            assert result.recommend_ioc is False
            assert result.recommend_reduce_size is False

    def test_high_vol_adjustment(self, estimator, market_data):
        """HIGH_VOL 市场状态调整成本（1.5x）"""
        with patch.object(
            estimator.market_state_detector,
            "detect_state",
            return_value=MarketMetrics(
                volatility=0.03,  # 高于阈值 0.02
                liquidity_score=0.7,
                spread_bps=5.0,
                price_reversals=3,
                detected_state=MarketState.HIGH_VOL,
            ),
        ):
            result = estimator.estimate_cost(
                order_type=OrderType.LIMIT,
                side=OrderSide.BUY,
                size=Decimal("0.1"),
                market_data=market_data,
            )

            assert result.market_state == MarketState.HIGH_VOL
            assert result.adjustment_factor == 1.5

            # 验证 Slippage 和 Impact 被调整
            # 由于是 mock，我们主要验证调整因子被应用
            assert result.total_cost_bps > 0  # 成本已计算

            # 验证执行建议：HIGH_VOL → 建议改用 IOC（对 LIMIT 订单）
            assert result.recommend_ioc is True

    def test_low_liq_adjustment(self, estimator, market_data):
        """LOW_LIQ 市场状态调整成本（2x）并建议 IOC"""
        with patch.object(
            estimator.market_state_detector,
            "detect_state",
            return_value=MarketMetrics(
                volatility=0.01,
                liquidity_score=0.2,  # 低于阈值 0.3
                spread_bps=20.0,  # 高于阈值 15.0
                price_reversals=2,
                detected_state=MarketState.LOW_LIQ,
            ),
        ):
            result = estimator.estimate_cost(
                order_type=OrderType.LIMIT,
                side=OrderSide.BUY,
                size=Decimal("0.1"),
                market_data=market_data,
            )

            assert result.market_state == MarketState.LOW_LIQ
            assert result.adjustment_factor == 2.0

            # 验证执行建议：LOW_LIQ → 强烈建议 IOC + 减小尺寸
            assert result.recommend_ioc is True
            assert result.recommend_reduce_size is True

    def test_choppy_adjustment(self, estimator, market_data):
        """CHOPPY 市场状态调整 Slippage（1.3x），Impact 不变"""
        with patch.object(
            estimator.market_state_detector,
            "detect_state",
            return_value=MarketMetrics(
                volatility=0.015,
                liquidity_score=0.6,
                spread_bps=4.0,
                price_reversals=7,  # 高于阈值 5
                detected_state=MarketState.CHOPPY,
            ),
        ):
            result = estimator.estimate_cost(
                order_type=OrderType.LIMIT,
                side=OrderSide.BUY,
                size=Decimal("0.1"),
                market_data=market_data,
            )

            assert result.market_state == MarketState.CHOPPY
            assert result.adjustment_factor == 1.3

            # CHOPPY 不建议改用 IOC（震荡不影响 Maker 成交）
            assert result.recommend_ioc is False
            assert result.recommend_reduce_size is False


class TestRecommendations:
    """测试执行建议生成"""

    def test_ioc_recommendation_for_limit_in_high_vol(self, estimator, market_data):
        """HIGH_VOL 时建议 LIMIT 订单改用 IOC"""
        with patch.object(
            estimator.market_state_detector,
            "detect_state",
            return_value=MarketMetrics(
                volatility=0.03,
                liquidity_score=0.7,
                spread_bps=5.0,
                price_reversals=3,
                detected_state=MarketState.HIGH_VOL,
            ),
        ):
            # LIMIT 订单
            result_limit = estimator.estimate_cost(
                order_type=OrderType.LIMIT,
                side=OrderSide.BUY,
                size=Decimal("0.1"),
                market_data=market_data,
            )
            assert result_limit.recommend_ioc is True

            # IOC 订单不需要建议改用 IOC
            result_ioc = estimator.estimate_cost(
                order_type=OrderType.IOC,
                side=OrderSide.BUY,
                size=Decimal("0.1"),
                market_data=market_data,
            )
            assert result_ioc.recommend_ioc is False

    def test_reduce_size_recommendation_for_large_orders(self, estimator, market_data):
        """HIGH_VOL 时建议大订单减小尺寸"""
        with patch.object(
            estimator.market_state_detector,
            "detect_state",
            return_value=MarketMetrics(
                volatility=0.03,
                liquidity_score=0.7,
                spread_bps=5.0,
                price_reversals=3,
                detected_state=MarketState.HIGH_VOL,
            ),
        ):
            # 小订单（< 50% 平均流动性）
            small_result = estimator.estimate_cost(
                order_type=OrderType.LIMIT,
                side=OrderSide.BUY,
                size=Decimal("0.1"),  # 远小于流动性 (6.0)
                market_data=market_data,
            )
            assert small_result.recommend_reduce_size is False

            # 大订单（> 50% 平均流动性）
            large_result = estimator.estimate_cost(
                order_type=OrderType.LIMIT,
                side=OrderSide.BUY,
                size=Decimal("5.0"),  # 接近平均流动性 (6.0) 的 50%
                market_data=market_data,
            )
            assert large_result.recommend_reduce_size is True

    def test_low_liq_always_recommends_both(self, estimator, market_data):
        """LOW_LIQ 总是建议 IOC + 减小尺寸"""
        with patch.object(
            estimator.market_state_detector,
            "detect_state",
            return_value=MarketMetrics(
                volatility=0.01,
                liquidity_score=0.2,
                spread_bps=20.0,
                price_reversals=2,
                detected_state=MarketState.LOW_LIQ,
            ),
        ):
            result = estimator.estimate_cost(
                order_type=OrderType.LIMIT,
                side=OrderSide.BUY,
                size=Decimal("0.01"),  # 极小订单
                market_data=market_data,
            )

            # 即使订单很小，也建议改用 IOC + 减小尺寸
            assert result.recommend_ioc is True
            assert result.recommend_reduce_size is True


class TestBackwardCompatibility:
    """测试向后兼容性"""

    def test_can_replace_dynamic_cost_estimator(self, market_data):
        """AdaptiveCostEstimator 可以无缝替换 DynamicCostEstimator"""
        from src.analytics.dynamic_cost_estimator import DynamicCostEstimator

        # 创建两个估算器
        dynamic_estimator = DynamicCostEstimator()
        adaptive_estimator = AdaptiveCostEstimator()

        # Mock 市场状态为 NORMAL（无调整）
        with patch.object(
            adaptive_estimator.market_state_detector,
            "detect_state",
            return_value=MarketMetrics(
                volatility=0.01,
                liquidity_score=0.8,
                spread_bps=3.0,
                price_reversals=2,
                detected_state=MarketState.NORMAL,
            ),
        ):
            # 相同参数调用
            dynamic_result = dynamic_estimator.estimate_cost(
                order_type=OrderType.LIMIT,
                side=OrderSide.BUY,
                size=Decimal("0.1"),
                market_data=market_data,
            )

            adaptive_result = adaptive_estimator.estimate_cost(
                order_type=OrderType.LIMIT,
                side=OrderSide.BUY,
                size=Decimal("0.1"),
                market_data=market_data,
            )

            # 在 NORMAL 状态下，成本应该一致
            assert abs(adaptive_result.total_cost_bps - dynamic_result.total_cost_bps) < 0.1

    def test_inherits_all_dynamic_methods(self, estimator):
        """验证继承了所有 DynamicCostEstimator 的方法"""
        # 检查关键方法是否可用
        assert hasattr(estimator, "record_actual_cost")
        assert hasattr(estimator, "get_cost_stats")
        assert hasattr(estimator, "get_estimation_accuracy")
        assert hasattr(estimator, "cache_estimate")
        assert hasattr(estimator, "get_cached_estimate")


class TestEdgeCases:
    """测试边界条件"""

    def test_empty_order_book(self, estimator):
        """空订单簿边界条件"""
        empty_market_data = MarketData(
            symbol="BTC",
            timestamp=1609459200000,
            bids=[],
            asks=[],
            mid_price=Decimal("50000.0"),
        )

        with patch.object(
            estimator.market_state_detector,
            "detect_state",
            return_value=MarketMetrics(
                volatility=0.0,
                liquidity_score=0.0,
                spread_bps=9999.0,
                price_reversals=0,
                detected_state=MarketState.LOW_LIQ,
            ),
        ):
            result = estimator.estimate_cost(
                order_type=OrderType.LIMIT,
                side=OrderSide.BUY,
                size=Decimal("0.1"),
                market_data=empty_market_data,
            )

            # 应该检测为 LOW_LIQ 并给出建议
            assert result.market_state == MarketState.LOW_LIQ
            assert result.recommend_ioc is True
            assert result.recommend_reduce_size is True

    def test_zero_size_order(self, estimator, market_data):
        """零尺寸订单边界条件"""
        with patch.object(
            estimator.market_state_detector,
            "detect_state",
            return_value=MarketMetrics(
                volatility=0.01,
                liquidity_score=0.8,
                spread_bps=3.0,
                price_reversals=2,
                detected_state=MarketState.NORMAL,
            ),
        ):
            result = estimator.estimate_cost(
                order_type=OrderType.LIMIT,
                side=OrderSide.BUY,
                size=Decimal("0.0"),
                market_data=market_data,
            )

            # 零尺寸订单是边界条件，SlippageEstimator 可能返回极端值
            # 主要验证不会抛出异常，能正常返回结果
            assert isinstance(result, AdaptiveCostEstimate)
            assert result.market_state == MarketState.NORMAL
            assert result.size == Decimal("0.0")

    def test_custom_adjustment_factors(self, market_data):
        """自定义调整系数"""
        custom_estimator = AdaptiveCostEstimator(
            high_vol_factor=2.0,
            low_liq_factor=3.0,
            choppy_factor=1.5,
        )

        with patch.object(
            custom_estimator.market_state_detector,
            "detect_state",
            return_value=MarketMetrics(
                volatility=0.03,
                liquidity_score=0.7,
                spread_bps=5.0,
                price_reversals=3,
                detected_state=MarketState.HIGH_VOL,
            ),
        ):
            result = custom_estimator.estimate_cost(
                order_type=OrderType.LIMIT,
                side=OrderSide.BUY,
                size=Decimal("0.1"),
                market_data=market_data,
            )

            # 验证使用了自定义调整系数
            assert result.adjustment_factor == 2.0  # 自定义 high_vol_factor


class TestIntegration:
    """集成测试"""

    def test_full_workflow_with_state_detection(self, estimator, market_data):
        """完整工作流：从市场数据 → 状态检测 → 成本估算 → 建议生成"""
        # 不使用 mock，使用真实的 MarketStateDetector
        result = estimator.estimate_cost(
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            size=Decimal("0.1"),
            market_data=market_data,
        )

        # 验证返回了完整的估算结果
        assert isinstance(result, AdaptiveCostEstimate)
        assert result.market_state in [
            MarketState.NORMAL,
            MarketState.HIGH_VOL,
            MarketState.LOW_LIQ,
            MarketState.CHOPPY,
        ]
        assert result.adjustment_factor >= 1.0
        assert result.total_cost_bps >= 0
        assert isinstance(result.recommend_ioc, bool)
        assert isinstance(result.recommend_reduce_size, bool)

    def test_repr_output(self, estimator):
        """验证 __repr__ 输出"""
        repr_str = repr(estimator)
        assert "AdaptiveCostEstimator" in repr_str
        assert "high_vol" in repr_str
        assert "low_liq" in repr_str
        assert "choppy" in repr_str
