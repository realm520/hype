"""DynamicCostEstimator 单元测试

测试动态成本估算器的核心功能。
"""

import time
from decimal import Decimal

import pytest

from src.analytics.dynamic_cost_estimator import (
    DynamicCostEstimator,
)
from src.core.constants import HYPERLIQUID_MAKER_FEE_RATE, HYPERLIQUID_TAKER_FEE_RATE
from src.core.types import MarketData, Order, OrderSide, OrderStatus, OrderType

# ==================== Fixtures ====================


@pytest.fixture
def cost_estimator():
    """标准成本估算器"""
    return DynamicCostEstimator()


@pytest.fixture
def custom_cost_estimator():
    """自定义参数的成本估算器"""
    return DynamicCostEstimator(
        maker_fee_rate=Decimal("0.0001"),  # 1 bps
        taker_fee_rate=Decimal("0.0004"),  # 4 bps
        impact_alpha=0.02,
    )


# ==================== 测试：初始化 ====================


class TestInitialization:
    """测试初始化"""

    def test_default_initialization(self, cost_estimator):
        """测试默认初始化"""
        assert cost_estimator.maker_fee_rate == HYPERLIQUID_MAKER_FEE_RATE
        assert cost_estimator.taker_fee_rate == HYPERLIQUID_TAKER_FEE_RATE
        assert cost_estimator.impact_model == "linear"
        assert cost_estimator.impact_alpha == 0.01
        assert cost_estimator.max_history == 10000

    def test_custom_initialization(self, custom_cost_estimator):
        """测试自定义初始化"""
        assert custom_cost_estimator.maker_fee_rate == Decimal("0.0001")
        assert custom_cost_estimator.taker_fee_rate == Decimal("0.0004")
        assert custom_cost_estimator.impact_alpha == 0.02


# ==================== 测试：费率计算 ====================


class TestFeeCalculation:
    """测试费率计算"""

    def test_maker_fee_rate(self, cost_estimator, sample_market_data):
        """测试 Maker 费率 = 1.5 bps"""
        estimate = cost_estimator.estimate_cost(
            OrderType.LIMIT,
            OrderSide.BUY,
            Decimal("1.0"),
            sample_market_data,
        )
        assert estimate.fee_bps == 1.5

    def test_taker_fee_rate(self, cost_estimator, sample_market_data):
        """测试 Taker 费率 = 4.5 bps"""
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("1.0"),
            sample_market_data,
        )
        assert estimate.fee_bps == 4.5

    def test_custom_maker_fee_rate(self, custom_cost_estimator, sample_market_data):
        """测试自定义 Maker 费率"""
        estimate = custom_cost_estimator.estimate_cost(
            OrderType.LIMIT,
            OrderSide.BUY,
            Decimal("1.0"),
            sample_market_data,
        )
        assert estimate.fee_bps == 1.0  # 1 bps

    def test_custom_taker_fee_rate(self, custom_cost_estimator, sample_market_data):
        """测试自定义 Taker 费率"""
        estimate = custom_cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("1.0"),
            sample_market_data,
        )
        assert estimate.fee_bps == 4.0  # 4 bps


# ==================== 测试：滑点估算 ====================


class TestSlippageEstimation:
    """测试滑点估算"""

    def test_slippage_estimation_uses_slippage_estimator(
        self, cost_estimator, sample_market_data
    ):
        """测试滑点估算调用 SlippageEstimator"""
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("1.0"),
            sample_market_data,
        )
        # 滑点应该 > 0（因为有订单簿深度）
        assert estimate.slippage_bps >= 0

    def test_slippage_small_order(self, cost_estimator, sample_market_data):
        """测试小单滑点（流动性充足）"""
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("1.0"),  # 小单
            sample_market_data,
        )
        # 小单滑点应该较小
        assert 0 <= estimate.slippage_bps < 10

    def test_slippage_large_order(self, cost_estimator, sample_market_data):
        """测试大单滑点（流动性不足）"""
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("50.0"),  # 大单（超过第一档流动性）
            sample_market_data,
        )
        # 大单滑点应该较大
        assert estimate.slippage_bps > 0


# ==================== 测试：冲击估算 ====================


class TestImpactEstimation:
    """测试市场冲击估算"""

    def test_impact_small_order(self, cost_estimator, sample_market_data):
        """测试小单冲击（流动性充足）"""
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("1.0"),  # 小单
            sample_market_data,
        )
        # 小单冲击应该较小（< 1 bps）
        assert 0.5 <= estimate.impact_bps < 2.0

    def test_impact_large_order(self, cost_estimator, sample_market_data):
        """测试大单冲击（流动性不足）"""
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("50.0"),  # 大单
            sample_market_data,
        )
        # 大单冲击应该较大（> 2 bps）
        assert estimate.impact_bps > 1.0

    def test_impact_range_bounded(self, cost_estimator, sample_market_data):
        """测试冲击范围限制（0.5 - 10 bps）"""
        # 测试极小单
        estimate_small = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("0.01"),
            sample_market_data,
        )
        assert 0.5 <= estimate_small.impact_bps <= 10.0

        # 测试极大单
        estimate_large = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("1000.0"),
            sample_market_data,
        )
        assert 0.5 <= estimate_large.impact_bps <= 10.0


# ==================== 测试：市场状态计算 ====================


class TestMarketStateCalculation:
    """测试市场状态计算"""

    def test_spread_calculation(self, cost_estimator, sample_market_data):
        """测试价差计算"""
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("1.0"),
            sample_market_data,
        )
        # 价差应该 > 0
        assert estimate.spread_bps > 0

    def test_liquidity_score_high(self, cost_estimator, sample_market_data):
        """测试高流动性评分"""
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("1.0"),
            sample_market_data,
        )
        # 标准市场数据流动性较好
        assert 0 <= estimate.liquidity_score <= 1.0
        assert estimate.liquidity_score > 0.3

    def test_liquidity_score_low(self, cost_estimator, wide_spread_market_data):
        """测试低流动性评分"""
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("1.0"),
            wide_spread_market_data,
        )
        # 宽价差市场流动性较差
        assert 0 <= estimate.liquidity_score <= 1.0
        assert estimate.liquidity_score < 0.5

    def test_volatility_score(self, cost_estimator, sample_market_data):
        """测试波动率评分"""
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("1.0"),
            sample_market_data,
        )
        # 波动率评分在 0-1 之间
        assert 0 <= estimate.volatility_score <= 1.0


# ==================== 测试：总成本估算 ====================


class TestTotalCostEstimation:
    """测试总成本估算"""

    def test_maker_total_cost(self, cost_estimator, sample_market_data):
        """测试 Maker 总成本"""
        estimate = cost_estimator.estimate_cost(
            OrderType.LIMIT,
            OrderSide.BUY,
            Decimal("1.0"),
            sample_market_data,
        )
        # Maker 总成本 = Fee(1.5) + Slip(~0) + Impact(~1-2)
        assert 2.0 <= estimate.total_cost_bps <= 5.0
        # 验证成本分解
        assert estimate.total_cost_bps == (
            estimate.fee_bps + estimate.slippage_bps + estimate.impact_bps
        )

    def test_taker_total_cost(self, cost_estimator, sample_market_data):
        """测试 Taker 总成本"""
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("1.0"),
            sample_market_data,
        )
        # Taker 总成本 = Fee(4.5) + Slip(~2-3) + Impact(~1-2)
        assert 6.0 <= estimate.total_cost_bps <= 12.0
        # 验证成本分解
        assert estimate.total_cost_bps == (
            estimate.fee_bps + estimate.slippage_bps + estimate.impact_bps
        )

    def test_maker_cheaper_than_taker(self, cost_estimator, sample_market_data):
        """测试 Maker 成本 < Taker 成本"""
        maker_estimate = cost_estimator.estimate_cost(
            OrderType.LIMIT,
            OrderSide.BUY,
            Decimal("1.0"),
            sample_market_data,
        )
        taker_estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("1.0"),
            sample_market_data,
        )
        # Maker 费率低 3 bps，成本应该更低
        assert maker_estimate.total_cost_bps < taker_estimate.total_cost_bps


# ==================== 测试：实际成本记录 ====================


class TestActualCostRecording:
    """测试实际成本记录"""

    def test_record_actual_cost_maker(
        self, cost_estimator, sample_market_data, sample_buy_order
    ):
        """测试记录 Maker 实际成本"""
        # 1. 事前估算
        estimate = cost_estimator.estimate_cost(
            OrderType.LIMIT,
            OrderSide.BUY,
            sample_buy_order.size,
            sample_market_data,
        )

        # 2. 修改订单类型为 LIMIT
        sample_buy_order.order_type = OrderType.LIMIT

        # 3. 事后记录
        actual = cost_estimator.record_actual_cost(
            order=sample_buy_order,
            estimated_cost=estimate,
            actual_fill_price=Decimal("1500.5"),
            reference_price=Decimal("1500.25"),
            best_price=Decimal("1500.5"),
        )

        # 验证 Maker 费率
        assert actual.fee_bps == 1.5
        assert actual.order_type == OrderType.LIMIT

    def test_record_actual_cost_taker(
        self, cost_estimator, sample_market_data, sample_buy_order
    ):
        """测试记录 Taker 实际成本"""
        # 1. 事前估算
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            sample_buy_order.size,
            sample_market_data,
        )

        # 2. 事后记录
        actual = cost_estimator.record_actual_cost(
            order=sample_buy_order,
            estimated_cost=estimate,
            actual_fill_price=Decimal("1500.5"),
            reference_price=Decimal("1500.25"),
            best_price=Decimal("1500.5"),
        )

        # 验证 Taker 费率
        assert actual.fee_bps == 4.5
        assert actual.order_type == OrderType.IOC

    def test_estimation_error_calculation(
        self, cost_estimator, sample_market_data, sample_buy_order
    ):
        """测试估算误差计算"""
        # 1. 事前估算
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            sample_buy_order.size,
            sample_market_data,
        )

        # 2. 事后记录
        actual = cost_estimator.record_actual_cost(
            order=sample_buy_order,
            estimated_cost=estimate,
            actual_fill_price=Decimal("1500.5"),
            reference_price=Decimal("1500.25"),
            best_price=Decimal("1500.5"),
        )

        # 验证误差计算
        expected_error_pct = (
            (actual.total_cost_bps - estimate.total_cost_bps)
            / estimate.total_cost_bps
            * 100
        )
        assert abs(actual.estimation_error_pct - expected_error_pct) < 0.01

    def test_actual_cost_history_updated(
        self, cost_estimator, sample_market_data, sample_buy_order
    ):
        """测试实际成本历史更新"""
        initial_count = cost_estimator.get_history_size()["actuals"]

        # 记录实际成本
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            sample_buy_order.size,
            sample_market_data,
        )
        cost_estimator.record_actual_cost(
            order=sample_buy_order,
            estimated_cost=estimate,
            actual_fill_price=Decimal("1500.5"),
            reference_price=Decimal("1500.25"),
            best_price=Decimal("1500.5"),
        )

        # 验证历史记录增加
        assert cost_estimator.get_history_size()["actuals"] == initial_count + 1

    def test_zero_trade_value_handling(
        self, cost_estimator, sample_market_data, sample_buy_order
    ):
        """测试零成交额处理"""
        # 创建零成交订单
        sample_buy_order.filled_size = Decimal("0")

        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("1.0"),
            sample_market_data,
        )

        actual = cost_estimator.record_actual_cost(
            order=sample_buy_order,
            estimated_cost=estimate,
            actual_fill_price=Decimal("1500.5"),
            reference_price=Decimal("1500.25"),
            best_price=Decimal("1500.5"),
        )

        # 验证零成本记录
        assert actual.fee_bps == 0.0
        assert actual.total_cost_bps == 0.0


# ==================== 测试：成本统计 ====================


class TestCostStatistics:
    """测试成本统计"""

    def test_get_cost_stats_no_data(self, cost_estimator):
        """测试无数据时的统计"""
        stats = cost_estimator.get_cost_stats()
        assert stats is None

    def test_get_cost_stats_with_data(
        self, cost_estimator, sample_market_data, create_market_data
    ):
        """测试有数据时的统计"""
        # 创建多笔交易记录
        for i in range(5):
            order = Order(
                id=f"order_{i}",
                symbol="ETH",
                side=OrderSide.BUY,
                order_type=OrderType.IOC if i % 2 == 0 else OrderType.LIMIT,
                price=Decimal("1500"),
                size=Decimal("1.0"),
                filled_size=Decimal("1.0"),
                status=OrderStatus.FILLED,
                created_at=int(time.time() * 1000),
            )
            estimate = cost_estimator.estimate_cost(
                order.order_type,
                order.side,
                order.size,
                sample_market_data,
            )
            cost_estimator.record_actual_cost(
                order=order,
                estimated_cost=estimate,
                actual_fill_price=Decimal("1500.5"),
                reference_price=Decimal("1500.25"),
                best_price=Decimal("1500.5"),
            )

        stats = cost_estimator.get_cost_stats()
        assert stats is not None
        assert stats.num_trades == 5
        assert stats.maker_ratio + stats.taker_ratio == 1.0

    def test_get_cost_stats_maker_taker_ratio(
        self, cost_estimator, sample_market_data
    ):
        """测试 Maker/Taker 比例统计"""
        # 创建 3 个 Maker 和 2 个 Taker 订单
        for i in range(5):
            order = Order(
                id=f"order_{i}",
                symbol="ETH",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT if i < 3 else OrderType.IOC,
                price=Decimal("1500"),
                size=Decimal("1.0"),
                filled_size=Decimal("1.0"),
                status=OrderStatus.FILLED,
                created_at=int(time.time() * 1000),
            )
            estimate = cost_estimator.estimate_cost(
                order.order_type,
                order.side,
                order.size,
                sample_market_data,
            )
            cost_estimator.record_actual_cost(
                order=order,
                estimated_cost=estimate,
                actual_fill_price=Decimal("1500.5"),
                reference_price=Decimal("1500.25"),
                best_price=Decimal("1500.5"),
            )

        stats = cost_estimator.get_cost_stats()
        assert stats.maker_ratio == 0.6  # 3/5
        assert stats.taker_ratio == 0.4  # 2/5

    def test_get_cost_stats_by_symbol(self, cost_estimator, sample_market_data):
        """测试按交易对统计"""
        # 创建 BTC 和 ETH 订单
        for symbol in ["BTC", "ETH"]:
            market_data = MarketData(
                symbol=symbol,
                timestamp=int(time.time() * 1000),
                bids=sample_market_data.bids,
                asks=sample_market_data.asks,
                mid_price=sample_market_data.mid_price,
            )
            order = Order(
                id=f"order_{symbol}",
                symbol=symbol,
                side=OrderSide.BUY,
                order_type=OrderType.IOC,
                price=Decimal("1500"),
                size=Decimal("1.0"),
                filled_size=Decimal("1.0"),
                status=OrderStatus.FILLED,
                created_at=int(time.time() * 1000),
            )
            estimate = cost_estimator.estimate_cost(
                order.order_type,
                order.side,
                order.size,
                market_data,
            )
            cost_estimator.record_actual_cost(
                order=order,
                estimated_cost=estimate,
                actual_fill_price=Decimal("1500.5"),
                reference_price=Decimal("1500.25"),
                best_price=Decimal("1500.5"),
            )

        # 按交易对统计
        stats_btc = cost_estimator.get_cost_stats(symbol="BTC")
        stats_eth = cost_estimator.get_cost_stats(symbol="ETH")
        stats_all = cost_estimator.get_cost_stats()

        assert stats_btc.num_trades == 1
        assert stats_eth.num_trades == 1
        assert stats_all.num_trades == 2


# ==================== 测试：估算准确性 ====================


class TestEstimationAccuracy:
    """测试估算准确性"""

    def test_get_estimation_accuracy_no_data(self, cost_estimator):
        """测试无数据时的准确性报告"""
        accuracy = cost_estimator.get_estimation_accuracy()
        assert accuracy["num_samples"] == 0
        assert accuracy["avg_error_pct"] == 0.0

    def test_get_estimation_accuracy_with_data(
        self, cost_estimator, sample_market_data
    ):
        """测试有数据时的准确性报告"""
        # 创建多笔交易
        for i in range(10):
            order = Order(
                id=f"order_{i}",
                symbol="ETH",
                side=OrderSide.BUY,
                order_type=OrderType.IOC,
                price=Decimal("1500"),
                size=Decimal("1.0"),
                filled_size=Decimal("1.0"),
                status=OrderStatus.FILLED,
                created_at=int(time.time() * 1000),
            )
            estimate = cost_estimator.estimate_cost(
                order.order_type,
                order.side,
                order.size,
                sample_market_data,
            )
            cost_estimator.record_actual_cost(
                order=order,
                estimated_cost=estimate,
                actual_fill_price=Decimal("1500.5"),
                reference_price=Decimal("1500.25"),
                best_price=Decimal("1500.5"),
            )

        accuracy = cost_estimator.get_estimation_accuracy()
        assert accuracy["num_samples"] == 10
        assert "avg_error_pct" in accuracy
        assert "mae" in accuracy
        assert "rmse" in accuracy
        assert "within_10pct" in accuracy
        assert "within_20pct" in accuracy

    def test_estimation_within_20pct_target(
        self, cost_estimator, sample_market_data
    ):
        """测试估算误差 < 20% 目标"""
        # 创建多笔交易
        for i in range(20):
            order = Order(
                id=f"order_{i}",
                symbol="ETH",
                side=OrderSide.BUY,
                order_type=OrderType.IOC,
                price=Decimal("1500"),
                size=Decimal("1.0"),
                filled_size=Decimal("1.0"),
                status=OrderStatus.FILLED,
                created_at=int(time.time() * 1000),
            )
            estimate = cost_estimator.estimate_cost(
                order.order_type,
                order.side,
                order.size,
                sample_market_data,
            )
            cost_estimator.record_actual_cost(
                order=order,
                estimated_cost=estimate,
                actual_fill_price=Decimal("1500.5"),
                reference_price=Decimal("1500.25"),
                best_price=Decimal("1500.5"),
            )

        accuracy = cost_estimator.get_estimation_accuracy()
        # 验证大部分估算在 20% 误差范围内
        assert accuracy["within_20pct"] > 0.5  # 至少 50% 的交易误差 < 20%


# ==================== 测试：缓存功能 ====================


class TestCacheFunctionality:
    """测试缓存功能"""

    def test_cache_estimate(self, cost_estimator, sample_market_data):
        """测试缓存估算"""
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("1.0"),
            sample_market_data,
        )

        order_id = "test_order"
        cost_estimator.cache_estimate(order_id, estimate)

        cached = cost_estimator.get_cached_estimate(order_id)
        assert cached == estimate

    def test_get_cached_estimate_not_found(self, cost_estimator):
        """测试获取不存在的缓存"""
        cached = cost_estimator.get_cached_estimate("nonexistent")
        assert cached is None

    def test_cache_cleared_after_recording(
        self, cost_estimator, sample_market_data, sample_buy_order
    ):
        """测试记录实际成本后清除缓存"""
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            sample_buy_order.size,
            sample_market_data,
        )

        order_id = sample_buy_order.id
        cost_estimator.cache_estimate(order_id, estimate)

        # 记录实际成本
        cost_estimator.record_actual_cost(
            order=sample_buy_order,
            estimated_cost=estimate,
            actual_fill_price=Decimal("1500.5"),
            reference_price=Decimal("1500.25"),
            best_price=Decimal("1500.5"),
        )

        # 验证缓存已清除
        cached = cost_estimator.get_cached_estimate(order_id)
        assert cached is None


# ==================== 测试：历史管理 ====================


class TestHistoryManagement:
    """测试历史管理"""

    def test_history_size_limits(self, sample_market_data):
        """测试历史记录大小限制"""
        cost_estimator = DynamicCostEstimator(max_history=10)

        # 创建 20 笔交易（超过限制）
        for i in range(20):
            order = Order(
                id=f"order_{i}",
                symbol="ETH",
                side=OrderSide.BUY,
                order_type=OrderType.IOC,
                price=Decimal("1500"),
                size=Decimal("1.0"),
                filled_size=Decimal("1.0"),
                status=OrderStatus.FILLED,
                created_at=int(time.time() * 1000),
            )
            estimate = cost_estimator.estimate_cost(
                order.order_type,
                order.side,
                order.size,
                sample_market_data,
            )
            cost_estimator.record_actual_cost(
                order=order,
                estimated_cost=estimate,
                actual_fill_price=Decimal("1500.5"),
                reference_price=Decimal("1500.25"),
                best_price=Decimal("1500.5"),
            )

        # 验证历史记录大小限制
        history_size = cost_estimator.get_history_size()
        assert history_size["estimates"] == 10
        assert history_size["actuals"] == 10


# ==================== 测试：数据类表示 ====================


class TestDataClassRepresentation:
    """测试数据类表示"""

    def test_cost_estimate_repr(self, cost_estimator, sample_market_data):
        """测试 CostEstimate __repr__"""
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            Decimal("1.0"),
            sample_market_data,
        )
        repr_str = repr(estimate)
        assert "IOC" in repr_str
        assert "BUY" in repr_str
        assert "bps" in repr_str

    def test_cost_actual_repr(self, cost_estimator, sample_market_data, sample_buy_order):
        """测试 CostActual __repr__"""
        estimate = cost_estimator.estimate_cost(
            OrderType.IOC,
            OrderSide.BUY,
            sample_buy_order.size,
            sample_market_data,
        )
        actual = cost_estimator.record_actual_cost(
            order=sample_buy_order,
            estimated_cost=estimate,
            actual_fill_price=Decimal("1500.5"),
            reference_price=Decimal("1500.25"),
            best_price=Decimal("1500.5"),
        )
        repr_str = repr(actual)
        assert "IOC" in repr_str
        assert "bps" in repr_str
        assert "error" in repr_str

    def test_cost_stats_repr(self, cost_estimator, sample_market_data):
        """测试 CostStats __repr__"""
        # 创建测试数据
        for i in range(5):
            order = Order(
                id=f"order_{i}",
                symbol="ETH",
                side=OrderSide.BUY,
                order_type=OrderType.IOC,
                price=Decimal("1500"),
                size=Decimal("1.0"),
                filled_size=Decimal("1.0"),
                status=OrderStatus.FILLED,
                created_at=int(time.time() * 1000),
            )
            estimate = cost_estimator.estimate_cost(
                order.order_type,
                order.side,
                order.size,
                sample_market_data,
            )
            cost_estimator.record_actual_cost(
                order=order,
                estimated_cost=estimate,
                actual_fill_price=Decimal("1500.5"),
                reference_price=Decimal("1500.25"),
                best_price=Decimal("1500.5"),
            )

        stats = cost_estimator.get_cost_stats()
        repr_str = repr(stats)
        assert "24h" in repr_str
        assert "n=" in repr_str

    def test_estimator_repr(self, cost_estimator):
        """测试 DynamicCostEstimator __repr__"""
        repr_str = repr(cost_estimator)
        assert "DynamicCostEstimator" in repr_str
        assert "maker" in repr_str
        assert "taker" in repr_str
