"""集成测试专用 fixtures

为集成测试提供：
1. DynamicCostEstimator + PnLAttribution 集成 fixtures
2. 多场景市场数据生成器
3. Maker/Taker 订单工厂
4. 多交易场景测试辅助函数
"""

import time
from collections.abc import Callable
from decimal import Decimal

import pytest

from src.analytics.dynamic_cost_estimator import DynamicCostEstimator
from src.analytics.pnl_attribution import PnLAttribution
from src.core.constants import HYPERLIQUID_MAKER_FEE_RATE, HYPERLIQUID_TAKER_FEE_RATE
from src.core.types import Level, MarketData, Order, OrderSide, OrderStatus, OrderType
from src.execution.slippage_estimator import SlippageEstimator

# ==================== DynamicCostEstimator Fixtures ====================


@pytest.fixture
def cost_estimator():
    """标准成本估算器（Maker 1.5 bps + Taker 4.5 bps）"""
    slippage_estimator = SlippageEstimator()
    return DynamicCostEstimator(
        maker_fee_rate=HYPERLIQUID_MAKER_FEE_RATE,
        taker_fee_rate=HYPERLIQUID_TAKER_FEE_RATE,
        slippage_estimator=slippage_estimator,
        impact_model="linear",
        impact_alpha=0.01,
        max_history=10000,
    )


@pytest.fixture
def pnl_with_cost_estimator(cost_estimator):
    """集成了 DynamicCostEstimator 的 PnLAttribution"""
    pnl = PnLAttribution(
        fee_rate=float(HYPERLIQUID_TAKER_FEE_RATE),  # 默认 Taker 费率（向后兼容）
        alpha_threshold=0.70,
        max_history=10000,
    )
    # 注意：cost_estimator 通过 attribute_trade() 的参数传入
    return pnl


# ==================== 市场数据生成器 Fixtures ====================


@pytest.fixture
def create_normal_market():
    """创建正常市场数据（窄点差 + 高流动性）"""

    def _create(
        symbol: str = "ETH",
        mid_price: float = 1500.0,
        spread_bps: float = 3.0,  # 3 bps 点差
        bid_liquidity: float = 50.0,  # 买盘 50 ETH
        ask_liquidity: float = 50.0,  # 卖盘 50 ETH
    ) -> MarketData:
        """
        创建正常市场数据

        Args:
            symbol: 交易对
            mid_price: 中间价
            spread_bps: 买卖价差（基点）
            bid_liquidity: 买盘总流动性
            ask_liquidity: 卖盘总流动性

        Returns:
            MarketData: 市场数据对象
        """
        spread = mid_price * spread_bps / 10000
        best_bid = Decimal(str(mid_price - spread / 2))
        best_ask = Decimal(str(mid_price + spread / 2))

        # 5 档订单簿（流动性递减）
        bids = [
            Level(price=best_bid, size=Decimal(str(bid_liquidity * 0.4))),
            Level(price=best_bid - Decimal("0.5"), size=Decimal(str(bid_liquidity * 0.25))),
            Level(price=best_bid - Decimal("1.0"), size=Decimal(str(bid_liquidity * 0.15))),
            Level(price=best_bid - Decimal("1.5"), size=Decimal(str(bid_liquidity * 0.10))),
            Level(price=best_bid - Decimal("2.0"), size=Decimal(str(bid_liquidity * 0.10))),
        ]

        asks = [
            Level(price=best_ask, size=Decimal(str(ask_liquidity * 0.4))),
            Level(price=best_ask + Decimal("0.5"), size=Decimal(str(ask_liquidity * 0.25))),
            Level(price=best_ask + Decimal("1.0"), size=Decimal(str(ask_liquidity * 0.15))),
            Level(price=best_ask + Decimal("1.5"), size=Decimal(str(ask_liquidity * 0.10))),
            Level(price=best_ask + Decimal("2.0"), size=Decimal(str(ask_liquidity * 0.10))),
        ]

        return MarketData(
            symbol=symbol,
            timestamp=int(time.time() * 1000),
            bids=bids,
            asks=asks,
            mid_price=Decimal(str(mid_price)),
        )

    return _create


@pytest.fixture
def create_wide_spread_market():
    """创建宽点差市场数据（低流动性）"""

    def _create(
        symbol: str = "ETH",
        mid_price: float = 1500.0,
        spread_bps: float = 20.0,  # 20 bps 点差（正常的 6-7 倍）
        bid_liquidity: float = 10.0,  # 买盘仅 10 ETH
        ask_liquidity: float = 10.0,  # 卖盘仅 10 ETH
    ) -> MarketData:
        """
        创建宽点差市场数据

        特点：
        - 点差大（20 bps）
        - 流动性低（仅 10 ETH/档）
        - 适合测试高成本场景
        """
        spread = mid_price * spread_bps / 10000
        best_bid = Decimal(str(mid_price - spread / 2))
        best_ask = Decimal(str(mid_price + spread / 2))

        # 3 档订单簿（流动性稀薄）
        bids = [
            Level(price=best_bid, size=Decimal(str(bid_liquidity * 0.5))),
            Level(price=best_bid - Decimal("2.0"), size=Decimal(str(bid_liquidity * 0.3))),
            Level(price=best_bid - Decimal("4.0"), size=Decimal(str(bid_liquidity * 0.2))),
        ]

        asks = [
            Level(price=best_ask, size=Decimal(str(ask_liquidity * 0.5))),
            Level(price=best_ask + Decimal("2.0"), size=Decimal(str(ask_liquidity * 0.3))),
            Level(price=best_ask + Decimal("4.0"), size=Decimal(str(ask_liquidity * 0.2))),
        ]

        return MarketData(
            symbol=symbol,
            timestamp=int(time.time() * 1000),
            bids=bids,
            asks=asks,
            mid_price=Decimal(str(mid_price)),
        )

    return _create


@pytest.fixture
def create_imbalanced_market():
    """创建不平衡市场数据（买卖流动性严重不对称）"""

    def _create(
        symbol: str = "ETH",
        mid_price: float = 1500.0,
        spread_bps: float = 5.0,
        bid_liquidity: float = 100.0,  # 买盘 100 ETH（强买盘）
        ask_liquidity: float = 10.0,  # 卖盘仅 10 ETH（弱卖盘）
    ) -> MarketData:
        """
        创建不平衡市场数据

        特点：
        - 买盘流动性 >> 卖盘流动性（10:1）
        - 适合测试 OBI 信号强度
        - 适合测试市场冲击差异
        """
        spread = mid_price * spread_bps / 10000
        best_bid = Decimal(str(mid_price - spread / 2))
        best_ask = Decimal(str(mid_price + spread / 2))

        bids = [
            Level(price=best_bid, size=Decimal(str(bid_liquidity * 0.4))),
            Level(price=best_bid - Decimal("0.5"), size=Decimal(str(bid_liquidity * 0.25))),
            Level(price=best_bid - Decimal("1.0"), size=Decimal(str(bid_liquidity * 0.15))),
            Level(price=best_bid - Decimal("1.5"), size=Decimal(str(bid_liquidity * 0.10))),
            Level(price=best_bid - Decimal("2.0"), size=Decimal(str(bid_liquidity * 0.10))),
        ]

        asks = [
            Level(price=best_ask, size=Decimal(str(ask_liquidity * 0.5))),
            Level(price=best_ask + Decimal("0.5"), size=Decimal(str(ask_liquidity * 0.3))),
            Level(price=best_ask + Decimal("1.0"), size=Decimal(str(ask_liquidity * 0.2))),
        ]

        return MarketData(
            symbol=symbol,
            timestamp=int(time.time() * 1000),
            bids=bids,
            asks=asks,
            mid_price=Decimal(str(mid_price)),
        )

    return _create


# ==================== 订单工厂 Fixtures ====================


@pytest.fixture
def create_maker_order():
    """创建 Maker 订单（LIMIT 类型）"""

    def _create(
        order_id: str,
        symbol: str = "ETH",
        side: OrderSide = OrderSide.BUY,
        price: Decimal = Decimal("1500.0"),
        size: Decimal = Decimal("1.0"),
        filled_size: Decimal | None = None,
        status: OrderStatus = OrderStatus.FILLED,
    ) -> Order:
        """
        创建 Maker 订单

        Args:
            order_id: 订单 ID
            symbol: 交易对
            side: 买卖方向
            price: 限价
            size: 订单数量
            filled_size: 成交数量（默认全部成交）
            status: 订单状态

        Returns:
            Order: Maker 订单对象
        """
        if filled_size is None:
            filled_size = size

        return Order(
            id=order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,  # Maker 订单
            price=price,
            size=size,
            filled_size=filled_size,
            status=status,
            created_at=int(time.time() * 1000),
        )

    return _create


@pytest.fixture
def create_taker_order():
    """创建 Taker 订单（IOC 类型）"""

    def _create(
        order_id: str,
        symbol: str = "ETH",
        side: OrderSide = OrderSide.BUY,
        price: Decimal = Decimal("1500.5"),
        size: Decimal = Decimal("1.0"),
        filled_size: Decimal | None = None,
        status: OrderStatus = OrderStatus.FILLED,
    ) -> Order:
        """
        创建 Taker 订单

        Args:
            order_id: 订单 ID
            symbol: 交易对
            side: 买卖方向
            price: 成交价
            size: 订单数量
            filled_size: 成交数量（默认全部成交）
            status: 订单状态

        Returns:
            Order: Taker 订单对象
        """
        if filled_size is None:
            filled_size = size

        return Order(
            id=order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.IOC,  # Taker 订单
            price=price,
            size=size,
            filled_size=filled_size,
            status=status,
            created_at=int(time.time() * 1000),
        )

    return _create


# ==================== 多交易场景辅助函数 ====================


@pytest.fixture
def create_trade_sequence():
    """创建交易序列生成器（用于多交易场景测试）"""

    def _create(
        num_trades: int,
        order_factory: Callable,
        base_price: float = 1500.0,
        price_increment: float = 1.0,
        size: Decimal = Decimal("1.0"),
    ) -> list[Order]:
        """
        创建交易序列

        Args:
            num_trades: 交易数量
            order_factory: 订单工厂函数（create_maker_order 或 create_taker_order）
            base_price: 基础价格
            price_increment: 价格递增幅度
            size: 每笔交易数量

        Returns:
            list[Order]: 订单列表
        """
        orders = []
        for i in range(num_trades):
            price = Decimal(str(base_price + i * price_increment))
            order = order_factory(
                order_id=f"order_{i+1:03d}",
                price=price,
                size=size,
            )
            orders.append(order)

        return orders

    return _create


@pytest.fixture
def execute_trade_and_attribute(pnl_with_cost_estimator, cost_estimator):
    """执行交易并进行 PnL 归因的辅助函数"""

    def _execute(
        order: Order,
        signal_value: float,
        reference_price: Decimal,
        actual_fill_price: Decimal,
        best_price: Decimal,
    ):
        """
        执行单笔交易并归因

        Args:
            order: 订单对象
            signal_value: 信号值（-1 到 1）
            reference_price: 参考价格（信号时刻中间价）
            actual_fill_price: 实际成交价
            best_price: 最优价格（下单时盘口价）

        Returns:
            TradeAttribution: 归因结果
        """
        return pnl_with_cost_estimator.attribute_trade(
            order=order,
            signal_value=signal_value,
            reference_price=reference_price,
            actual_fill_price=actual_fill_price,
            best_price=best_price,
            cost_estimator=cost_estimator,  # 使用动态成本估算器
        )

    return _execute


@pytest.fixture
def verify_cost_breakdown():
    """验证成本分解的辅助函数"""

    def _verify(
        attribution,
        expected_fee_bps: float,
        max_slippage_bps: float,
        max_impact_bps: float,
        tolerance_bps: float = 0.2,
        price: Decimal | None = None,
    ):
        """
        验证成本分解是否符合预期

        Args:
            attribution: TradeAttribution 对象
            expected_fee_bps: 预期手续费（bps）
            max_slippage_bps: 最大滑点（bps）
            max_impact_bps: 最大市场冲击（bps）
            tolerance_bps: 允许误差（bps）
            price: 交易价格（用于计算 bps，如果未提供则从 attribution 推算）
        """
        # 从费用反推交易价值（因为 TradeAttribution 没有 trade_value 字段）
        if price is None:
            # 假设 size = 1.0，从 fee 反推价格
            # fee = -trade_value * fee_rate
            # 已知 fee_rate（从 expected_fee_bps 推算），反推 trade_value
            if expected_fee_bps == 1.5:  # Maker
                fee_rate = Decimal("0.00015")
            else:  # Taker (4.5 bps)
                fee_rate = Decimal("0.00045")

            trade_value = abs(attribution.fee) / fee_rate
        else:
            trade_value = price  # size = 1.0

        # 计算实际 bps
        actual_fee_bps = float(abs(attribution.fee) / trade_value * 10000)
        actual_slippage_bps = float(abs(attribution.slippage) / trade_value * 10000)
        actual_impact_bps = float(abs(attribution.impact) / trade_value * 10000)

        # 验证手续费
        assert abs(actual_fee_bps - expected_fee_bps) <= tolerance_bps, (
            f"Fee mismatch: expected {expected_fee_bps:.2f} bps, got {actual_fee_bps:.2f} bps"
        )

        # 验证滑点在范围内
        assert actual_slippage_bps <= max_slippage_bps, (
            f"Slippage too high: {actual_slippage_bps:.2f} bps > {max_slippage_bps:.2f} bps"
        )

        # 验证冲击在范围内
        assert actual_impact_bps <= max_impact_bps, (
            f"Impact too high: {actual_impact_bps:.2f} bps > {max_impact_bps:.2f} bps"
        )

    return _verify
