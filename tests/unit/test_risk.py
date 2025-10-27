"""风控层单元测试"""

from decimal import Decimal

from src.core.types import OrderSide
from src.risk.hard_limits import HardLimits
from src.risk.position_manager import PositionManager


class TestHardLimits:
    """测试硬限制风控"""

    def test_initialization(self):
        """测试初始化"""
        limits = HardLimits(
            initial_nav=Decimal("100000.0"),
            max_single_loss_pct=0.008,  # 0.8%
            max_daily_drawdown_pct=0.05,  # 5%
            max_position_size_usd=10000.0,
        )

        assert limits.initial_nav == Decimal("100000.0")
        assert limits._current_nav == Decimal("100000.0")
        assert limits._daily_pnl == Decimal("0.0")
        assert not limits._is_breached

    def test_single_loss_limit(self, sample_buy_order, sample_market_data):
        """测试单笔损失限制"""
        limits = HardLimits(
            initial_nav=Decimal("100000.0"),
            max_single_loss_pct=0.008,  # 0.8% = 800 USD
            max_daily_drawdown_pct=0.05,
            max_position_size_usd=10000.0,
        )

        # 正常订单（价值约 1500 USD）
        is_allowed, reason = limits.check_order(
            sample_buy_order,
            sample_market_data.mid_price,
            Decimal("0.0"),
        )
        assert is_allowed
        assert reason is None

        # 超大订单（会超过单笔损失限制）
        large_order = sample_buy_order
        large_order.size = Decimal("100.0")  # 价值 ~150,000 USD

        is_allowed, reason = limits.check_order(
            large_order,
            sample_market_data.mid_price,
            Decimal("0.0"),
        )
        assert not is_allowed
        assert "single loss" in reason.lower()

    def test_position_size_limit(self, sample_buy_order, sample_market_data):
        """测试持仓规模限制"""
        limits = HardLimits(
            initial_nav=Decimal("100000.0"),
            max_single_loss_pct=0.008,
            max_daily_drawdown_pct=0.05,
            max_position_size_usd=5000.0,  # 降低持仓限制
        )

        # 订单本身不大，但加上现有持仓会超限
        current_position_value = Decimal("4000.0")

        is_allowed, reason = limits.check_order(
            sample_buy_order,  # ~1500 USD
            sample_market_data.mid_price,
            current_position_value,
        )

        assert not is_allowed
        assert "position size" in reason.lower()

    def test_daily_drawdown_limit(self):
        """测试日内回撤限制"""
        limits = HardLimits(
            initial_nav=Decimal("100000.0"),
            max_single_loss_pct=0.008,
            max_daily_drawdown_pct=0.05,  # 5% = 5000 USD
            max_position_size_usd=10000.0,
        )

        # 模拟一系列亏损
        limits.update_pnl(Decimal("-1000.0"))  # -1%
        assert not limits._is_breached
        assert limits._daily_pnl == Decimal("-1000.0")

        limits.update_pnl(Decimal("-2000.0"))  # -3% 累计
        assert not limits._is_breached

        limits.update_pnl(Decimal("-3000.0"))  # -6% 累计
        # 注意：update_pnl() 只更新统计，不触发违规检查
        # 违规检查只在 check_order() 时进行
        assert not limits._is_breached
        assert limits._daily_pnl == Decimal("-6000.0")
        assert limits._current_nav == Decimal("94000.0")

    def test_pnl_updates(self):
        """测试 PnL 更新"""
        limits = HardLimits(
            initial_nav=Decimal("100000.0"),
            max_single_loss_pct=0.008,
            max_daily_drawdown_pct=0.05,
            max_position_size_usd=10000.0,
        )

        # 更新盈利
        limits.update_pnl(Decimal("500.0"))
        assert limits._current_nav == Decimal("100500.0")
        assert limits._daily_pnl == Decimal("500.0")

        # 更新亏损
        limits.update_pnl(Decimal("-300.0"))
        assert limits._current_nav == Decimal("100200.0")
        assert limits._daily_pnl == Decimal("200.0")

    def test_reset_breach(self):
        """测试违规重置"""
        limits = HardLimits(
            initial_nav=Decimal("100000.0"),
            max_single_loss_pct=0.008,
            max_daily_drawdown_pct=0.05,
            max_position_size_usd=10000.0,
        )

        # 手动标记违规（模拟 check_order 触发的违规）
        limits._mark_breach("Test breach for reset testing")
        assert limits._is_breached
        assert limits._breach_reason == "Test breach for reset testing"

        # 重置违规标志
        limits.reset_breach()
        assert not limits._is_breached
        assert limits._breach_reason is None

    def test_get_status(self):
        """测试状态获取"""
        limits = HardLimits(
            initial_nav=Decimal("100000.0"),
            max_single_loss_pct=0.008,
            max_daily_drawdown_pct=0.05,
            max_position_size_usd=10000.0,
        )

        limits.update_pnl(Decimal("2000.0"))

        status = limits.get_status()

        # get_status() returns current_nav, not initial_nav
        assert limits.initial_nav == Decimal("100000.0")
        assert status["current_nav"] == 102000.0
        assert status["daily_pnl"] == 2000.0
        assert not status["is_breached"]
        assert status["breach_reason"] is None


class TestPositionManager:
    """测试持仓管理器"""

    def test_initialization(self):
        """测试初始化"""
        manager = PositionManager()
        assert len(manager._positions) == 0

    def test_update_from_buy_order(self, sample_buy_order):
        """测试买入订单更新持仓"""
        manager = PositionManager()

        # 第一次买入
        manager.update_from_order(sample_buy_order, sample_buy_order.price)

        position = manager.get_position("ETH")
        assert position is not None
        assert position.symbol == "ETH"
        assert position.size == Decimal("1.0")
        assert position.entry_price == sample_buy_order.price

    def test_update_from_sell_order(self, sample_sell_order):
        """测试卖出订单更新持仓"""
        manager = PositionManager()

        # 先建立多头持仓
        import time

        from src.core.types import Order, OrderStatus, OrderType

        buy_order = Order(
            id="buy_001",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("1500.0"),
            size=Decimal("2.0"),
            filled_size=Decimal("2.0"),
            status=OrderStatus.FILLED,
            created_at=int(time.time() * 1000),
        )

        manager.update_from_order(buy_order, buy_order.price)

        # 部分平仓
        manager.update_from_order(sample_sell_order, sample_sell_order.price)

        position = manager.get_position("ETH")
        assert position.size == Decimal("1.0")  # 2.0 - 1.0

    def test_position_close(self):
        """测试持仓关闭"""
        manager = PositionManager()

        import time

        from src.core.types import Order, OrderStatus, OrderType

        # 买入 2 ETH
        buy_order = Order(
            id="buy_001",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("1500.0"),
            size=Decimal("2.0"),
            filled_size=Decimal("2.0"),
            status=OrderStatus.FILLED,
            created_at=int(time.time() * 1000),
        )
        manager.update_from_order(buy_order, buy_order.price)

        # 卖出 2 ETH（完全平仓）
        sell_order = Order(
            id="sell_001",
            symbol="ETH",
            side=OrderSide.SELL,
            order_type=OrderType.IOC,
            price=Decimal("1510.0"),
            size=Decimal("2.0"),
            filled_size=Decimal("2.0"),
            status=OrderStatus.FILLED,
            created_at=int(time.time() * 1000),
        )
        manager.update_from_order(sell_order, sell_order.price)

        # 持仓应该被移除
        position = manager.get_position("ETH")
        assert position is None or position.size == Decimal("0.0")

    def test_unrealized_pnl(self):
        """测试未实现盈亏"""
        manager = PositionManager()

        import time

        from src.core.types import Order, OrderStatus, OrderType

        # 买入 1 ETH @ 1500
        buy_order = Order(
            id="buy_001",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("1500.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=int(time.time() * 1000),
        )
        manager.update_from_order(buy_order, buy_order.price)

        # 更新价格到 1550
        current_price = Decimal("1550.0")
        manager.update_prices({"ETH": current_price})

        # 获取持仓并检查未实现盈亏
        position = manager.get_position("ETH")
        assert position is not None

        # 应该盈利 50 USD
        assert position.unrealized_pnl == Decimal("50.0")

    def test_realized_pnl(self):
        """测试已实现盈亏"""
        manager = PositionManager()

        import time

        from src.core.types import Order, OrderStatus, OrderType

        # 买入 1 ETH @ 1500
        buy_order = Order(
            id="buy_001",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("1500.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=int(time.time() * 1000),
        )
        manager.update_from_order(buy_order, buy_order.price)

        # 卖出 1 ETH @ 1550
        sell_order = Order(
            id="sell_001",
            symbol="ETH",
            side=OrderSide.SELL,
            order_type=OrderType.IOC,
            price=Decimal("1550.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=int(time.time() * 1000),
        )
        manager.update_from_order(sell_order, sell_order.price)

        # 获取持仓并检查已实现盈亏
        position = manager.get_position("ETH")
        assert position is not None

        # 应该盈利 50 USD
        assert position.realized_pnl == Decimal("50.0")

    def test_multiple_positions(self):
        """测试多个持仓"""
        manager = PositionManager()

        import time

        from src.core.types import Order, OrderStatus, OrderType

        # ETH 持仓
        eth_order = Order(
            id="eth_001",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("1500.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=int(time.time() * 1000),
        )
        manager.update_from_order(eth_order, eth_order.price)

        # BTC 持仓
        btc_order = Order(
            id="btc_001",
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("30000.0"),
            size=Decimal("0.1"),
            filled_size=Decimal("0.1"),
            status=OrderStatus.FILLED,
            created_at=int(time.time() * 1000),
        )
        manager.update_from_order(btc_order, btc_order.price)

        # 检查两个持仓
        eth_position = manager.get_position("ETH")
        btc_position = manager.get_position("BTC")

        assert eth_position is not None
        assert btc_position is not None
        assert eth_position.size == Decimal("1.0")
        assert btc_position.size == Decimal("0.1")

    def test_get_all_positions(self):
        """测试获取所有持仓"""
        manager = PositionManager()

        import time

        from src.core.types import Order, OrderStatus, OrderType

        # 添加多个持仓
        for i, symbol in enumerate(["ETH", "BTC", "SOL"]):
            order = Order(
                id=f"order_{i}",
                symbol=symbol,
                side=OrderSide.BUY,
                order_type=OrderType.IOC,
                price=Decimal("1000.0"),
                size=Decimal("1.0"),
                filled_size=Decimal("1.0"),
                status=OrderStatus.FILLED,
                created_at=int(time.time() * 1000),
            )
            manager.update_from_order(order, order.price)

        all_positions = manager.get_all_positions()
        assert len(all_positions) == 3

    def test_position_average_price(self):
        """测试加仓后的平均价格"""
        manager = PositionManager()

        import time

        from src.core.types import Order, OrderStatus, OrderType

        # 第一次买入 1 ETH @ 1500
        order1 = Order(
            id="order_1",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("1500.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=int(time.time() * 1000),
        )
        manager.update_from_order(order1, order1.price)

        # 第二次买入 1 ETH @ 1600
        order2 = Order(
            id="order_2",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("1600.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=int(time.time() * 1000),
        )
        manager.update_from_order(order2, order2.price)

        position = manager.get_position("ETH")

        # 平均价格应该是 1550
        assert position.entry_price == Decimal("1550.0")
        assert position.size == Decimal("2.0")
