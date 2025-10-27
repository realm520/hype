"""PositionManager 测试

测试持仓管理器的核心功能：
- 持仓创建和更新
- 开仓/平仓/反向开仓逻辑
- PnL 计算
- 价格更新
- 统计信息
"""

from decimal import Decimal

import pytest

from src.core.types import Order, OrderSide, OrderStatus, OrderType
from src.risk.position_manager import Position, PositionManager

# ==================== Fixtures ====================


@pytest.fixture
def manager():
    """持仓管理器实例"""
    return PositionManager()


@pytest.fixture
def buy_order():
    """买入订单"""
    return Order(
        id="order_1",
        symbol="ETH",
        side=OrderSide.BUY,
        order_type=OrderType.IOC,
        price=Decimal("3000.0"),
        size=Decimal("1.0"),
        filled_size=Decimal("1.0"),
        status=OrderStatus.FILLED,
        created_at=1000,
    )


@pytest.fixture
def sell_order():
    """卖出订单"""
    return Order(
        id="order_2",
        symbol="ETH",
        side=OrderSide.SELL,
        order_type=OrderType.IOC,
        price=Decimal("3100.0"),
        size=Decimal("0.5"),
        filled_size=Decimal("0.5"),
        status=OrderStatus.FILLED,
        created_at=2000,
    )


# ==================== Position 属性测试 ====================


class TestPositionProperties:
    """测试 Position 属性"""

    def test_position_value_usd(self):
        """测试持仓价值计算"""
        position = Position(
            symbol="ETH",
            size=Decimal("2.0"),
            entry_price=Decimal("3000.0"),
            current_price=Decimal("3100.0"),
            unrealized_pnl=Decimal("200.0"),
            realized_pnl=Decimal("0"),
        )

        # 持仓价值 = |size| * current_price
        assert position.position_value_usd == Decimal("6200.0")

    def test_is_long_property(self):
        """测试多头判断"""
        position = Position(
            symbol="ETH",
            size=Decimal("1.0"),  # 正数为多头
            entry_price=Decimal("3000.0"),
            current_price=Decimal("3100.0"),
            unrealized_pnl=Decimal("100.0"),
            realized_pnl=Decimal("0"),
        )

        assert position.is_long is True
        assert position.is_short is False
        assert position.is_flat is False

    def test_is_short_property(self):
        """测试空头判断"""
        position = Position(
            symbol="ETH",
            size=Decimal("-1.0"),  # 负数为空头
            entry_price=Decimal("3000.0"),
            current_price=Decimal("2900.0"),
            unrealized_pnl=Decimal("100.0"),
            realized_pnl=Decimal("0"),
        )

        assert position.is_short is True
        assert position.is_long is False
        assert position.is_flat is False

    def test_is_flat_property(self):
        """测试平仓判断"""
        position = Position(
            symbol="ETH",
            size=Decimal("0"),  # 零为平仓
            entry_price=Decimal("0"),
            current_price=Decimal("3000.0"),
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("100.0"),
        )

        assert position.is_flat is True
        assert position.is_long is False
        assert position.is_short is False


# ==================== 开仓逻辑测试 ====================


class TestOpenPosition:
    """测试开仓逻辑"""

    def test_open_long_position(self, manager, buy_order):
        """测试开多仓"""
        manager.update_from_order(buy_order)

        position = manager.get_position("ETH")

        assert position is not None
        assert position.size == Decimal("1.0")
        assert position.entry_price == Decimal("3000.0")
        assert position.current_price == Decimal("3000.0")
        assert position.is_long is True

    def test_open_short_position(self, manager, sell_order):
        """测试开空仓"""
        manager.update_from_order(sell_order)

        position = manager.get_position("ETH")

        assert position is not None
        assert position.size == Decimal("-0.5")
        assert position.entry_price == Decimal("3100.0")
        assert position.current_price == Decimal("3100.0")
        assert position.is_short is True

    def test_add_to_long_position(self, manager):
        """测试加多仓"""
        # 第一次开仓
        order1 = Order(
            id="order_1",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("3000.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=1000,
        )
        manager.update_from_order(order1)

        # 第二次加仓
        order2 = Order(
            id="order_2",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("3100.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=2000,
        )
        manager.update_from_order(order2)

        position = manager.get_position("ETH")

        # 持仓应该是 2.0
        assert position.size == Decimal("2.0")
        # 平均开仓价 = (1*3000 + 1*3100) / 2 = 3050
        assert position.entry_price == Decimal("3050.0")

    def test_add_to_short_position(self, manager):
        """测试加空仓"""
        # 第一次开空仓
        order1 = Order(
            id="order_1",
            symbol="ETH",
            side=OrderSide.SELL,
            order_type=OrderType.IOC,
            price=Decimal("3100.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=1000,
        )
        manager.update_from_order(order1)

        # 第二次加仓
        order2 = Order(
            id="order_2",
            symbol="ETH",
            side=OrderSide.SELL,
            order_type=OrderType.IOC,
            price=Decimal("3000.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=2000,
        )
        manager.update_from_order(order2)

        position = manager.get_position("ETH")

        # 持仓应该是 -2.0
        assert position.size == Decimal("-2.0")
        # 平均开仓价 = (1*3100 + 1*3000) / 2 = 3050
        assert position.entry_price == Decimal("3050.0")


# ==================== 平仓逻辑测试 ====================


class TestClosePosition:
    """测试平仓逻辑"""

    def test_close_long_position(self, manager):
        """测试平多仓"""
        # 开多仓
        buy_order = Order(
            id="order_1",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("3000.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=1000,
        )
        manager.update_from_order(buy_order)

        # 平仓
        sell_order = Order(
            id="order_2",
            symbol="ETH",
            side=OrderSide.SELL,
            order_type=OrderType.IOC,
            price=Decimal("3100.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=2000,
        )
        manager.update_from_order(sell_order)

        position = manager.get_position("ETH")

        # 完全平仓
        assert position.size == Decimal("0")
        assert position.entry_price == Decimal("0")
        # 已实现盈亏 = 1.0 * (3100 - 3000) = 100
        assert position.realized_pnl == Decimal("100.0")

    def test_close_short_position(self, manager):
        """测试平空仓"""
        # 开空仓
        sell_order = Order(
            id="order_1",
            symbol="ETH",
            side=OrderSide.SELL,
            order_type=OrderType.IOC,
            price=Decimal("3100.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=1000,
        )
        manager.update_from_order(sell_order)

        # 平空仓
        buy_order = Order(
            id="order_2",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("3000.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=2000,
        )
        manager.update_from_order(buy_order)

        position = manager.get_position("ETH")

        # 完全平仓
        assert position.size == Decimal("0")
        assert position.entry_price == Decimal("0")
        # 已实现盈亏 = 1.0 * (3100 - 3000) = 100
        assert position.realized_pnl == Decimal("100.0")

    def test_partial_close_long(self, manager):
        """测试部分平多仓"""
        # 开多仓 2.0
        buy_order = Order(
            id="order_1",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("3000.0"),
            size=Decimal("2.0"),
            filled_size=Decimal("2.0"),
            status=OrderStatus.FILLED,
            created_at=1000,
        )
        manager.update_from_order(buy_order)

        # 部分平仓 1.0
        sell_order = Order(
            id="order_2",
            symbol="ETH",
            side=OrderSide.SELL,
            order_type=OrderType.IOC,
            price=Decimal("3100.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=2000,
        )
        manager.update_from_order(sell_order)

        position = manager.get_position("ETH")

        # 剩余 1.0
        assert position.size == Decimal("1.0")
        # 开仓价不变
        assert position.entry_price == Decimal("3000.0")
        # 已实现盈亏 = 1.0 * (3100 - 3000) = 100
        assert position.realized_pnl == Decimal("100.0")

    def test_reverse_long_to_short(self, manager):
        """测试多转空"""
        # 开多仓 1.0
        buy_order = Order(
            id="order_1",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("3000.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=1000,
        )
        manager.update_from_order(buy_order)

        # 卖出 2.0（平多开空）
        sell_order = Order(
            id="order_2",
            symbol="ETH",
            side=OrderSide.SELL,
            order_type=OrderType.IOC,
            price=Decimal("3100.0"),
            size=Decimal("2.0"),
            filled_size=Decimal("2.0"),
            status=OrderStatus.FILLED,
            created_at=2000,
        )
        manager.update_from_order(sell_order)

        position = manager.get_position("ETH")

        # 反向开仓，持仓 -1.0
        assert position.size == Decimal("-1.0")
        # 新开仓价为反向价
        assert position.entry_price == Decimal("3100.0")
        # 已实现盈亏 = 1.0 * (3100 - 3000) = 100
        assert position.realized_pnl == Decimal("100.0")

    def test_reverse_short_to_long(self, manager):
        """测试空转多"""
        # 开空仓 1.0
        sell_order = Order(
            id="order_1",
            symbol="ETH",
            side=OrderSide.SELL,
            order_type=OrderType.IOC,
            price=Decimal("3100.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=1000,
        )
        manager.update_from_order(sell_order)

        # 买入 2.0（平空开多）
        buy_order = Order(
            id="order_2",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("3000.0"),
            size=Decimal("2.0"),
            filled_size=Decimal("2.0"),
            status=OrderStatus.FILLED,
            created_at=2000,
        )
        manager.update_from_order(buy_order)

        position = manager.get_position("ETH")

        # 反向开仓，持仓 1.0
        assert position.size == Decimal("1.0")
        # 新开仓价为反向价
        assert position.entry_price == Decimal("3000.0")
        # 已实现盈亏 = 1.0 * (3100 - 3000) = 100
        assert position.realized_pnl == Decimal("100.0")


# ==================== 价格更新测试 ====================


class TestPriceUpdate:
    """测试价格更新"""

    def test_update_prices_long(self, manager):
        """测试多仓价格更新"""
        # 开多仓
        buy_order = Order(
            id="order_1",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("3000.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=1000,
        )
        manager.update_from_order(buy_order)

        # 更新价格
        manager.update_prices({"ETH": Decimal("3100.0")})

        position = manager.get_position("ETH")

        # 价格应更新
        assert position.current_price == Decimal("3100.0")
        # 未实现盈亏 = 1.0 * (3100 - 3000) = 100
        assert position.unrealized_pnl == Decimal("100.0")

    def test_update_prices_short(self, manager):
        """测试空仓价格更新"""
        # 开空仓
        sell_order = Order(
            id="order_1",
            symbol="ETH",
            side=OrderSide.SELL,
            order_type=OrderType.IOC,
            price=Decimal("3100.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=1000,
        )
        manager.update_from_order(sell_order)

        # 更新价格（价格下跌）
        manager.update_prices({"ETH": Decimal("3000.0")})

        position = manager.get_position("ETH")

        # 价格应更新
        assert position.current_price == Decimal("3000.0")
        # 空仓未实现盈亏 = 1.0 * (3100 - 3000) = 100
        assert position.unrealized_pnl == Decimal("100.0")

    def test_update_prices_multiple_symbols(self, manager):
        """测试多交易对价格更新"""
        # 开多仓 ETH
        buy_eth = Order(
            id="order_1",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("3000.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=1000,
        )
        manager.update_from_order(buy_eth)

        # 开多仓 BTC
        buy_btc = Order(
            id="order_2",
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("50000.0"),
            size=Decimal("0.1"),
            filled_size=Decimal("0.1"),
            status=OrderStatus.FILLED,
            created_at=2000,
        )
        manager.update_from_order(buy_btc)

        # 批量更新价格
        manager.update_prices({
            "ETH": Decimal("3100.0"),
            "BTC": Decimal("51000.0"),
        })

        eth_pos = manager.get_position("ETH")
        btc_pos = manager.get_position("BTC")

        assert eth_pos.current_price == Decimal("3100.0")
        assert btc_pos.current_price == Decimal("51000.0")
        assert eth_pos.unrealized_pnl == Decimal("100.0")
        assert btc_pos.unrealized_pnl == Decimal("100.0")


# ==================== 统计方法测试 ====================


class TestStatistics:
    """测试统计方法"""

    def test_get_total_position_value(self, manager):
        """测试总持仓价值计算"""
        # 开多仓 ETH
        buy_eth = Order(
            id="order_1",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("3000.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=1000,
        )
        manager.update_from_order(buy_eth)

        # 开多仓 BTC
        buy_btc = Order(
            id="order_2",
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("50000.0"),
            size=Decimal("0.1"),
            filled_size=Decimal("0.1"),
            status=OrderStatus.FILLED,
            created_at=2000,
        )
        manager.update_from_order(buy_btc)

        total_value = manager.get_total_position_value()

        # ETH: 1.0 * 3000 + BTC: 0.1 * 50000 = 8000
        assert total_value == Decimal("8000.0")

    def test_get_total_unrealized_pnl(self, manager):
        """测试总未实现盈亏"""
        # 开多仓 ETH
        buy_eth = Order(
            id="order_1",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("3000.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=1000,
        )
        manager.update_from_order(buy_eth)

        # 更新价格
        manager.update_prices({"ETH": Decimal("3100.0")})

        total_unrealized = manager.get_total_unrealized_pnl()

        # ETH 未实现盈亏: 1.0 * (3100 - 3000) = 100
        assert total_unrealized == Decimal("100.0")

    def test_get_total_realized_pnl(self, manager):
        """测试总已实现盈亏"""
        # 开仓并平仓
        buy_order = Order(
            id="order_1",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("3000.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=1000,
        )
        manager.update_from_order(buy_order)

        sell_order = Order(
            id="order_2",
            symbol="ETH",
            side=OrderSide.SELL,
            order_type=OrderType.IOC,
            price=Decimal("3100.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=2000,
        )
        manager.update_from_order(sell_order)

        total_realized = manager.get_total_realized_pnl()

        # 已实现盈亏: 1.0 * (3100 - 3000) = 100
        assert total_realized == Decimal("100.0")

    def test_get_statistics(self, manager):
        """测试统计信息"""
        # 开多仓 ETH
        buy_eth = Order(
            id="order_1",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("3000.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=1000,
        )
        manager.update_from_order(buy_eth)

        # 开空仓 BTC
        sell_btc = Order(
            id="order_2",
            symbol="BTC",
            side=OrderSide.SELL,
            order_type=OrderType.IOC,
            price=Decimal("50000.0"),
            size=Decimal("0.1"),
            filled_size=Decimal("0.1"),
            status=OrderStatus.FILLED,
            created_at=2000,
        )
        manager.update_from_order(sell_btc)

        stats = manager.get_statistics()

        assert stats["total_positions"] == 2
        assert stats["long_positions"] == 1
        assert stats["short_positions"] == 1
        assert stats["flat_positions"] == 0
        assert stats["total_position_value"] == 8000.0


# ==================== 其他测试 ====================


class TestOther:
    """其他测试"""

    def test_initialization(self, manager):
        """测试初始化"""
        assert len(manager.get_all_positions()) == 0

    def test_get_position_not_found(self, manager):
        """测试获取不存在的持仓"""
        position = manager.get_position("NONEXISTENT")

        assert position is None

    def test_get_all_positions(self, manager, buy_order, sell_order):
        """测试获取所有持仓"""
        manager.update_from_order(buy_order)
        manager.update_from_order(sell_order)

        positions = manager.get_all_positions()

        # 只有一个交易对，但有两个订单，最终持仓为 0.5
        assert len(positions) == 1
        assert "ETH" in positions

    def test_update_from_pending_order(self, manager):
        """测试处理未成交订单"""
        pending_order = Order(
            id="order_1",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("3000.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("0"),
            status=OrderStatus.PENDING,  # 未成交
            created_at=1000,
        )

        manager.update_from_order(pending_order)

        # 不应创建持仓
        position = manager.get_position("ETH")
        assert position is None

    def test_repr(self, manager, buy_order):
        """测试字符串表示"""
        manager.update_from_order(buy_order)

        repr_str = repr(manager)

        assert "PositionManager" in repr_str
        assert "positions=1" in repr_str
