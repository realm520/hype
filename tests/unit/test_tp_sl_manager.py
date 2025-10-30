"""TPSLManager 单元测试

测试覆盖：
    - 多头止盈/止损触发
    - 空头止盈/止损触发
    - 未触发场景
    - 边界条件
    - 价格计算准确性
"""

from decimal import Decimal

import pytest

from src.core.types import OrderSide, Position
from src.risk.tp_sl_manager import TPSLManager


class TestTPSLManager:
    """TPSLManager 基础测试"""

    def test_initialization(self):
        """测试初始化"""
        manager = TPSLManager(take_profit_pct=0.02, stop_loss_pct=0.01)

        assert manager.take_profit_pct == Decimal("0.02")
        assert manager.stop_loss_pct == Decimal("0.01")

    def test_default_parameters(self):
        """测试默认参数"""
        manager = TPSLManager()

        assert manager.take_profit_pct == Decimal("0.02")  # 2%
        assert manager.stop_loss_pct == Decimal("0.01")  # 1%


class TestLongPositionTPSL:
    """多头持仓 TP/SL 测试"""

    @pytest.fixture
    def manager(self):
        """创建 TP/SL 管理器"""
        return TPSLManager(take_profit_pct=0.02, stop_loss_pct=0.01)

    @pytest.fixture
    def long_position(self):
        """创建多头持仓

        开仓价格：100.0
        止盈价格：102.0（+2%）
        止损价格：99.0（-1%）
        """
        return Position(
            symbol="BTC",
            size=Decimal("1.0"),  # 正数 = 多头
            entry_price=Decimal("100.0"),
        )

    def test_take_profit_triggered(self, manager, long_position):
        """测试多头止盈触发"""
        # 价格上涨到 102.0（触发止盈）
        current_price = Decimal("102.0")

        should_close, reason = manager.check_position_risk(long_position, current_price)

        assert should_close is True
        assert reason == "take_profit"

    def test_take_profit_above_threshold(self, manager, long_position):
        """测试多头止盈（价格超过阈值）"""
        # 价格上涨到 105.0（远超止盈）
        current_price = Decimal("105.0")

        should_close, reason = manager.check_position_risk(long_position, current_price)

        assert should_close is True
        assert reason == "take_profit"

    def test_stop_loss_triggered(self, manager, long_position):
        """测试多头止损触发"""
        # 价格下跌到 99.0（触发止损）
        current_price = Decimal("99.0")

        should_close, reason = manager.check_position_risk(long_position, current_price)

        assert should_close is True
        assert reason == "stop_loss"

    def test_stop_loss_below_threshold(self, manager, long_position):
        """测试多头止损（价格低于阈值）"""
        # 价格下跌到 95.0（远超止损）
        current_price = Decimal("95.0")

        should_close, reason = manager.check_position_risk(long_position, current_price)

        assert should_close is True
        assert reason == "stop_loss"

    def test_no_trigger_price_in_range(self, manager, long_position):
        """测试未触发（价格在安全区间）"""
        # 价格在 99.0 ~ 102.0 之间
        current_price = Decimal("100.5")

        should_close, reason = manager.check_position_risk(long_position, current_price)

        assert should_close is False
        assert reason == ""

    def test_no_trigger_at_boundary(self, manager, long_position):
        """测试边界条件（价格刚好在阈值内）"""
        # 价格 99.01（刚好不触发 SL）
        should_close, reason = manager.check_position_risk(
            long_position, Decimal("99.01")
        )
        assert should_close is False

        # 价格 101.99（刚好不触发 TP）
        should_close, reason = manager.check_position_risk(
            long_position, Decimal("101.99")
        )
        assert should_close is False


class TestShortPositionTPSL:
    """空头持仓 TP/SL 测试"""

    @pytest.fixture
    def manager(self):
        """创建 TP/SL 管理器"""
        return TPSLManager(take_profit_pct=0.02, stop_loss_pct=0.01)

    @pytest.fixture
    def short_position(self):
        """创建空头持仓

        开仓价格：100.0
        止盈价格：98.0（-2%）
        止损价格：101.0（+1%）
        """
        return Position(
            symbol="ETH",
            size=Decimal("-1.0"),  # 负数 = 空头
            entry_price=Decimal("100.0"),
        )

    def test_take_profit_triggered(self, manager, short_position):
        """测试空头止盈触发"""
        # 价格下跌到 98.0（触发止盈）
        current_price = Decimal("98.0")

        should_close, reason = manager.check_position_risk(short_position, current_price)

        assert should_close is True
        assert reason == "take_profit"

    def test_take_profit_below_threshold(self, manager, short_position):
        """测试空头止盈（价格低于阈值）"""
        # 价格下跌到 95.0（远超止盈）
        current_price = Decimal("95.0")

        should_close, reason = manager.check_position_risk(short_position, current_price)

        assert should_close is True
        assert reason == "take_profit"

    def test_stop_loss_triggered(self, manager, short_position):
        """测试空头止损触发"""
        # 价格上涨到 101.0（触发止损）
        current_price = Decimal("101.0")

        should_close, reason = manager.check_position_risk(short_position, current_price)

        assert should_close is True
        assert reason == "stop_loss"

    def test_stop_loss_above_threshold(self, manager, short_position):
        """测试空头止损（价格高于阈值）"""
        # 价格上涨到 105.0（远超止损）
        current_price = Decimal("105.0")

        should_close, reason = manager.check_position_risk(short_position, current_price)

        assert should_close is True
        assert reason == "stop_loss"

    def test_no_trigger_price_in_range(self, manager, short_position):
        """测试未触发（价格在安全区间）"""
        # 价格在 98.0 ~ 101.0 之间
        current_price = Decimal("99.5")

        should_close, reason = manager.check_position_risk(short_position, current_price)

        assert should_close is False
        assert reason == ""

    def test_no_trigger_at_boundary(self, manager, short_position):
        """测试边界条件（价格刚好在阈值内）"""
        # 价格 100.99（刚好不触发 SL）
        should_close, reason = manager.check_position_risk(
            short_position, Decimal("100.99")
        )
        assert should_close is False

        # 价格 98.01（刚好不触发 TP）
        should_close, reason = manager.check_position_risk(
            short_position, Decimal("98.01")
        )
        assert should_close is False


class TestEdgeCases:
    """边界条件和异常场景测试"""

    @pytest.fixture
    def manager(self):
        """创建 TP/SL 管理器"""
        return TPSLManager(take_profit_pct=0.02, stop_loss_pct=0.01)

    def test_zero_position(self, manager):
        """测试零持仓"""
        position = Position(
            symbol="BTC",
            size=Decimal("0"),
            entry_price=Decimal("100.0"),
        )

        should_close, reason = manager.check_position_risk(position, Decimal("105.0"))

        assert should_close is False
        assert reason == ""

    def test_no_entry_price(self, manager):
        """测试无开仓价格"""
        position = Position(
            symbol="BTC",
            size=Decimal("1.0"),
            entry_price=None,
        )

        should_close, reason = manager.check_position_risk(position, Decimal("105.0"))

        assert should_close is False
        assert reason == ""

    def test_zero_entry_price(self, manager):
        """测试开仓价格为零"""
        position = Position(
            symbol="BTC",
            size=Decimal("1.0"),
            entry_price=Decimal("0"),
        )

        should_close, reason = manager.check_position_risk(position, Decimal("105.0"))

        assert should_close is False
        assert reason == ""


class TestTPSLPriceCalculation:
    """TP/SL 价格计算测试"""

    @pytest.fixture
    def manager(self):
        """创建 TP/SL 管理器"""
        return TPSLManager(take_profit_pct=0.02, stop_loss_pct=0.01)

    def test_long_tp_sl_prices(self, manager):
        """测试多头 TP/SL 价格计算"""
        entry_price = Decimal("100.0")

        tp_price, sl_price = manager.get_tp_sl_prices(entry_price, OrderSide.BUY)

        assert tp_price == Decimal("102.0")  # +2%
        assert sl_price == Decimal("99.0")  # -1%

    def test_short_tp_sl_prices(self, manager):
        """测试空头 TP/SL 价格计算"""
        entry_price = Decimal("100.0")

        tp_price, sl_price = manager.get_tp_sl_prices(entry_price, OrderSide.SELL)

        assert tp_price == Decimal("98.0")  # -2%
        assert sl_price == Decimal("101.0")  # +1%

    def test_custom_tp_sl_percentages(self):
        """测试自定义 TP/SL 百分比"""
        manager = TPSLManager(take_profit_pct=0.05, stop_loss_pct=0.02)
        entry_price = Decimal("1000.0")

        # 多头
        tp_price, sl_price = manager.get_tp_sl_prices(entry_price, OrderSide.BUY)
        assert tp_price == Decimal("1050.0")  # +5%
        assert sl_price == Decimal("980.0")  # -2%

        # 空头
        tp_price, sl_price = manager.get_tp_sl_prices(entry_price, OrderSide.SELL)
        assert tp_price == Decimal("950.0")  # -5%
        assert sl_price == Decimal("1020.0")  # +2%


class TestPrecisionAndRounding:
    """精度和舍入测试"""

    def test_decimal_precision(self):
        """测试 Decimal 精度处理"""
        manager = TPSLManager(take_profit_pct=0.025, stop_loss_pct=0.015)

        # 验证初始化时正确转换为 Decimal
        assert manager.take_profit_pct == Decimal("0.025")
        assert manager.stop_loss_pct == Decimal("0.015")

    def test_price_calculation_precision(self):
        """测试价格计算精度"""
        manager = TPSLManager()
        entry_price = Decimal("123.456789")

        tp_price, sl_price = manager.get_tp_sl_prices(entry_price, OrderSide.BUY)

        # TP: 123.456789 * 1.02 = 125.92592478
        assert tp_price == Decimal("123.456789") * Decimal("1.02")

        # SL: 123.456789 * 0.99 = 122.22222111
        assert sl_price == Decimal("123.456789") * Decimal("0.99")
