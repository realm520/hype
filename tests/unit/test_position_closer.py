"""PositionCloser 单元测试

Week 2 Phase 2 核心测试：平仓协调器集成测试

测试覆盖：
    - 初始化和配置
    - TP/SL 触发检测（多头/空头）
    - 超时触发检测
    - 平仓信号生成
    - 平仓执行（成功/失败）
    - 多持仓场景
    - 统计和指标
    - 边缘案例（空仓、None、异常）
"""

import pytest

from src.core.types import ConfidenceLevel
from src.execution.position_closer import PositionCloser


class TestPositionCloserInitialization:
    """初始化和配置测试"""

    def test_initialization_with_defaults(
        self,
        mock_tp_sl_manager,
        mock_position_manager,
        mock_ioc_executor,
    ):
        """测试默认参数初始化"""
        closer = PositionCloser(
            tp_sl_manager=mock_tp_sl_manager,
            position_manager=mock_position_manager,
            ioc_executor=mock_ioc_executor,
        )

        assert closer.tp_sl_manager is mock_tp_sl_manager
        assert closer.position_manager is mock_position_manager
        assert closer.ioc_executor is mock_ioc_executor
        assert closer.max_position_age_seconds == 1800.0  # 默认 30 分钟

    def test_initialization_with_custom_timeout(
        self,
        mock_tp_sl_manager,
        mock_position_manager,
        mock_ioc_executor,
    ):
        """测试自定义超时参数"""
        closer = PositionCloser(
            tp_sl_manager=mock_tp_sl_manager,
            position_manager=mock_position_manager,
            ioc_executor=mock_ioc_executor,
            max_position_age_seconds=3600.0,  # 1 小时
        )

        assert closer.max_position_age_seconds == 3600.0

    def test_stats_initialization(
        self,
        mock_tp_sl_manager,
        mock_position_manager,
        mock_ioc_executor,
    ):
        """测试统计指标初始化"""
        closer = PositionCloser(
            tp_sl_manager=mock_tp_sl_manager,
            position_manager=mock_position_manager,
            ioc_executor=mock_ioc_executor,
        )

        stats = closer.get_stats()

        assert stats["total_checks"] == 0
        assert stats["tp_triggers"] == 0
        assert stats["sl_triggers"] == 0
        assert stats["timeout_triggers"] == 0
        assert stats["close_success"] == 0
        assert stats["close_failed"] == 0


class TestLongPositionTPSLTriggers:
    """多头持仓 TP/SL 触发检测测试"""

    @pytest.fixture
    def position_closer(
        self,
        mock_tp_sl_manager,
        mock_position_manager,
        mock_ioc_executor,
    ):
        """创建 PositionCloser 实例"""
        return PositionCloser(
            tp_sl_manager=mock_tp_sl_manager,
            position_manager=mock_position_manager,
            ioc_executor=mock_ioc_executor,
        )

    @pytest.mark.asyncio
    async def test_long_take_profit_triggered(
        self,
        position_closer,
        create_position,
        market_data_dict_factory,
        mock_tp_sl_manager,
        mock_position_manager,
    ):
        """测试多头止盈触发"""
        # 设置持仓：多头 ETH @ 1500.0
        long_position = create_position(symbol="ETH", size=1.0, entry_price=1500.0)
        mock_position_manager.set_position(long_position)

        # 设置止盈触发（价格上涨到 1530.0）
        mock_tp_sl_manager.set_trigger(should_close=True, reason="take_profit")

        # 设置市场数据（价格 1530.0）
        market_data = market_data_dict_factory(symbols=["ETH"], mid_prices={"ETH": 1530.0})

        # 执行检查
        closed_orders = await position_closer.check_and_close_positions(market_data)

        # 验证结果
        assert len(closed_orders) == 1
        assert closed_orders[0].symbol == "ETH"

        # 验证统计
        stats = position_closer.get_stats()
        assert stats["tp_triggers"] == 1
        assert stats["close_success"] == 1
        assert stats["total_checks"] == 1

    @pytest.mark.asyncio
    async def test_long_stop_loss_triggered(
        self,
        position_closer,
        create_position,
        market_data_dict_factory,
        mock_tp_sl_manager,
        mock_position_manager,
    ):
        """测试多头止损触发"""
        # 设置持仓：多头 ETH @ 1500.0
        long_position = create_position(symbol="ETH", size=1.0, entry_price=1500.0)
        mock_position_manager.set_position(long_position)

        # 设置止损触发（价格下跌到 1485.0）
        mock_tp_sl_manager.set_trigger(should_close=True, reason="stop_loss")

        # 设置市场数据（价格 1485.0）
        market_data = market_data_dict_factory(symbols=["ETH"], mid_prices={"ETH": 1485.0})

        # 执行检查
        closed_orders = await position_closer.check_and_close_positions(market_data)

        # 验证结果
        assert len(closed_orders) == 1

        # 验证统计
        stats = position_closer.get_stats()
        assert stats["sl_triggers"] == 1
        assert stats["close_success"] == 1


class TestShortPositionTPSLTriggers:
    """空头持仓 TP/SL 触发检测测试"""

    @pytest.fixture
    def position_closer(
        self,
        mock_tp_sl_manager,
        mock_position_manager,
        mock_ioc_executor,
    ):
        """创建 PositionCloser 实例"""
        return PositionCloser(
            tp_sl_manager=mock_tp_sl_manager,
            position_manager=mock_position_manager,
            ioc_executor=mock_ioc_executor,
        )

    @pytest.mark.asyncio
    async def test_short_take_profit_triggered(
        self,
        position_closer,
        create_position,
        market_data_dict_factory,
        mock_tp_sl_manager,
        mock_position_manager,
    ):
        """测试空头止盈触发"""
        # 设置持仓：空头 ETH @ 1500.0
        short_position = create_position(symbol="ETH", size=-1.0, entry_price=1500.0)
        mock_position_manager.set_position(short_position)

        # 设置止盈触发（价格下跌到 1470.0）
        mock_tp_sl_manager.set_trigger(should_close=True, reason="take_profit")

        # 设置市场数据（价格 1470.0）
        market_data = market_data_dict_factory(symbols=["ETH"], mid_prices={"ETH": 1470.0})

        # 执行检查
        closed_orders = await position_closer.check_and_close_positions(market_data)

        # 验证结果
        assert len(closed_orders) == 1

        # 验证统计
        stats = position_closer.get_stats()
        assert stats["tp_triggers"] == 1
        assert stats["close_success"] == 1

    @pytest.mark.asyncio
    async def test_short_stop_loss_triggered(
        self,
        position_closer,
        create_position,
        market_data_dict_factory,
        mock_tp_sl_manager,
        mock_position_manager,
    ):
        """测试空头止损触发"""
        # 设置持仓：空头 ETH @ 1500.0
        short_position = create_position(symbol="ETH", size=-1.0, entry_price=1500.0)
        mock_position_manager.set_position(short_position)

        # 设置止损触发（价格上涨到 1515.0）
        mock_tp_sl_manager.set_trigger(should_close=True, reason="stop_loss")

        # 设置市场数据（价格 1515.0）
        market_data = market_data_dict_factory(symbols=["ETH"], mid_prices={"ETH": 1515.0})

        # 执行检查
        closed_orders = await position_closer.check_and_close_positions(market_data)

        # 验证结果
        assert len(closed_orders) == 1

        # 验证统计
        stats = position_closer.get_stats()
        assert stats["sl_triggers"] == 1
        assert stats["close_success"] == 1


class TestTimeoutTrigger:
    """超时触发检测测试"""

    @pytest.fixture
    def position_closer(
        self,
        mock_tp_sl_manager,
        mock_position_manager,
        mock_ioc_executor,
    ):
        """创建 PositionCloser 实例（30 分钟超时）"""
        return PositionCloser(
            tp_sl_manager=mock_tp_sl_manager,
            position_manager=mock_position_manager,
            ioc_executor=mock_ioc_executor,
            max_position_age_seconds=1800.0,
        )

    @pytest.mark.asyncio
    async def test_timeout_triggered_when_position_stale(
        self,
        position_closer,
        create_position,
        market_data_dict_factory,
        mock_position_manager,
    ):
        """测试持仓超时触发"""
        # 设置持仓：多头 ETH（已存在 31 分钟）
        stale_position = create_position(symbol="ETH", size=1.0, entry_price=1500.0)
        mock_position_manager.set_position(stale_position)
        mock_position_manager.set_stale(is_stale=True, age_seconds=1860.0)  # 31 分钟

        # 设置市场数据
        market_data = market_data_dict_factory(symbols=["ETH"])

        # 执行检查
        closed_orders = await position_closer.check_and_close_positions(market_data)

        # 验证结果
        assert len(closed_orders) == 1

        # 验证统计
        stats = position_closer.get_stats()
        assert stats["timeout_triggers"] == 1
        assert stats["close_success"] == 1

    @pytest.mark.asyncio
    async def test_no_timeout_when_position_fresh(
        self,
        position_closer,
        create_position,
        market_data_dict_factory,
        mock_position_manager,
    ):
        """测试持仓未超时（不触发）"""
        # 设置持仓：多头 ETH（刚开仓 5 分钟）
        fresh_position = create_position(symbol="ETH", size=1.0, entry_price=1500.0)
        mock_position_manager.set_position(fresh_position)
        mock_position_manager.set_stale(is_stale=False, age_seconds=300.0)  # 5 分钟

        # 设置市场数据
        market_data = market_data_dict_factory(symbols=["ETH"])

        # 执行检查
        closed_orders = await position_closer.check_and_close_positions(market_data)

        # 验证结果（不应触发平仓）
        assert len(closed_orders) == 0

        # 验证统计
        stats = position_closer.get_stats()
        assert stats["timeout_triggers"] == 0


class TestCloseSignalGeneration:
    """平仓信号生成测试"""

    @pytest.fixture
    def position_closer(
        self,
        mock_tp_sl_manager,
        mock_position_manager,
        mock_ioc_executor,
    ):
        """创建 PositionCloser 实例"""
        return PositionCloser(
            tp_sl_manager=mock_tp_sl_manager,
            position_manager=mock_position_manager,
            ioc_executor=mock_ioc_executor,
        )

    def test_long_position_generates_sell_signal(self, position_closer, create_position):
        """测试多头持仓生成卖出信号"""
        # 创建多头持仓
        long_position = create_position(symbol="ETH", size=1.0, entry_price=1500.0)

        # 生成平仓信号
        signal = position_closer._generate_close_signal(long_position, "take_profit")

        # 验证信号方向（多头 → 卖出 = -1.0）
        assert signal.value == -1.0
        assert signal.confidence == ConfidenceLevel.HIGH
        assert signal.individual_scores == [-1.0]

    def test_short_position_generates_buy_signal(self, position_closer, create_position):
        """测试空头持仓生成买入信号"""
        # 创建空头持仓
        short_position = create_position(symbol="ETH", size=-1.0, entry_price=1500.0)

        # 生成平仓信号
        signal = position_closer._generate_close_signal(short_position, "stop_loss")

        # 验证信号方向（空头 → 买入 = +1.0）
        assert signal.value == 1.0
        assert signal.confidence == ConfidenceLevel.HIGH
        assert signal.individual_scores == [1.0]

    def test_close_signal_always_high_confidence(self, position_closer, create_position):
        """测试平仓信号始终是 HIGH 置信度（确保 IOC 执行）"""
        position = create_position(symbol="ETH", size=1.0)

        # 测试不同原因的信号
        tp_signal = position_closer._generate_close_signal(position, "take_profit")
        sl_signal = position_closer._generate_close_signal(position, "stop_loss")
        timeout_signal = position_closer._generate_close_signal(position, "max_age_timeout")

        # 验证都是 HIGH 置信度
        assert tp_signal.confidence == ConfidenceLevel.HIGH
        assert sl_signal.confidence == ConfidenceLevel.HIGH
        assert timeout_signal.confidence == ConfidenceLevel.HIGH


class TestCloseExecution:
    """平仓执行测试（成功/失败）"""

    @pytest.fixture
    def position_closer(
        self,
        mock_tp_sl_manager,
        mock_position_manager,
        mock_ioc_executor,
    ):
        """创建 PositionCloser 实例"""
        return PositionCloser(
            tp_sl_manager=mock_tp_sl_manager,
            position_manager=mock_position_manager,
            ioc_executor=mock_ioc_executor,
        )

    @pytest.mark.asyncio
    async def test_close_execution_success(
        self,
        position_closer,
        create_position,
        market_data_dict_factory,
        mock_tp_sl_manager,
        mock_position_manager,
        mock_ioc_executor,
    ):
        """测试平仓执行成功"""
        # 设置持仓
        position = create_position(symbol="ETH", size=1.0, entry_price=1500.0)
        mock_position_manager.set_position(position)
        mock_tp_sl_manager.set_trigger(should_close=True, reason="take_profit")

        # 设置市场数据
        market_data = market_data_dict_factory(symbols=["ETH"])

        # 执行平仓
        await position_closer.check_and_close_positions(market_data)

        # 验证 IOC 执行器被调用
        assert mock_ioc_executor.execute.call_count == 1

        # 验证成功统计
        stats = position_closer.get_stats()
        assert stats["close_success"] == 1
        assert stats["close_failed"] == 0

    @pytest.mark.asyncio
    async def test_close_execution_failure(
        self,
        position_closer,
        create_position,
        market_data_dict_factory,
        mock_tp_sl_manager,
        mock_position_manager,
        mock_ioc_executor,
    ):
        """测试平仓执行失败（IOC 返回 None）"""
        # 设置持仓
        position = create_position(symbol="ETH", size=1.0, entry_price=1500.0)
        mock_position_manager.set_position(position)
        mock_tp_sl_manager.set_trigger(should_close=True, reason="take_profit")

        # 模拟 IOC 执行失败
        mock_ioc_executor.set_execute_result(None)

        # 设置市场数据
        market_data = market_data_dict_factory(symbols=["ETH"])

        # 执行平仓
        closed_orders = await position_closer.check_and_close_positions(market_data)

        # 验证返回空列表
        assert len(closed_orders) == 0

        # 验证失败统计
        stats = position_closer.get_stats()
        assert stats["close_success"] == 0
        assert stats["close_failed"] == 1

    @pytest.mark.asyncio
    async def test_close_execution_exception_handling(
        self,
        position_closer,
        create_position,
        market_data_dict_factory,
        mock_tp_sl_manager,
        mock_position_manager,
        mock_ioc_executor,
    ):
        """测试平仓执行异常处理"""
        from unittest.mock import AsyncMock

        # 设置持仓
        position = create_position(symbol="ETH", size=1.0, entry_price=1500.0)
        mock_position_manager.set_position(position)
        mock_tp_sl_manager.set_trigger(should_close=True, reason="take_profit")

        # 模拟 IOC 执行异常
        mock_ioc_executor.execute = AsyncMock(side_effect=Exception("API error"))

        # 设置市场数据
        market_data = market_data_dict_factory(symbols=["ETH"])

        # 执行平仓（不应抛出异常）
        closed_orders = await position_closer.check_and_close_positions(market_data)

        # 验证返回空列表
        assert len(closed_orders) == 0

        # 验证失败统计
        stats = position_closer.get_stats()
        assert stats["close_failed"] == 1


class TestMultiPositionScenarios:
    """多持仓场景测试"""

    @pytest.fixture
    def position_closer(
        self,
        mock_tp_sl_manager,
        mock_position_manager,
        mock_ioc_executor,
    ):
        """创建 PositionCloser 实例"""
        return PositionCloser(
            tp_sl_manager=mock_tp_sl_manager,
            position_manager=mock_position_manager,
            ioc_executor=mock_ioc_executor,
        )

    @pytest.mark.asyncio
    async def test_multiple_positions_mixed_triggers(
        self,
        position_closer,
        create_position,
        market_data_dict_factory,
        mock_tp_sl_manager,
        mock_position_manager,
    ):
        """测试多个持仓混合触发（TP + SL + 超时）"""
        # 设置多个持仓
        eth_position = create_position(symbol="ETH", size=1.0, entry_price=1500.0)
        btc_position = create_position(symbol="BTC", size=-1.0, entry_price=30000.0)

        # 设置市场数据
        market_data = market_data_dict_factory(
            symbols=["ETH", "BTC"],
            mid_prices={"ETH": 1530.0, "BTC": 30300.0},
        )

        # 模拟不同触发条件
        def check_position_risk_side_effect(position, price):
            if position.symbol == "ETH":
                return (True, "take_profit")  # ETH 止盈
            elif position.symbol == "BTC":
                return (True, "stop_loss")  # BTC 止损
            return (False, "")

        mock_tp_sl_manager.check_position_risk.side_effect = check_position_risk_side_effect

        # 设置持仓管理器行为
        def get_position_side_effect(symbol):
            if symbol == "ETH":
                return eth_position
            elif symbol == "BTC":
                return btc_position
            return None

        mock_position_manager.get_position.side_effect = get_position_side_effect

        # 执行检查
        closed_orders = await position_closer.check_and_close_positions(market_data)

        # 验证结果（应该平仓两个持仓）
        assert len(closed_orders) == 2

        # 验证统计
        stats = position_closer.get_stats()
        assert stats["tp_triggers"] == 1
        assert stats["sl_triggers"] == 1
        assert stats["close_success"] == 2


class TestStatisticsAndMetrics:
    """统计和指标测试"""

    @pytest.fixture
    def position_closer(
        self,
        mock_tp_sl_manager,
        mock_position_manager,
        mock_ioc_executor,
    ):
        """创建 PositionCloser 实例"""
        return PositionCloser(
            tp_sl_manager=mock_tp_sl_manager,
            position_manager=mock_position_manager,
            ioc_executor=mock_ioc_executor,
        )

    @pytest.mark.asyncio
    async def test_stats_accumulation(
        self,
        position_closer,
        create_position,
        market_data_dict_factory,
        mock_tp_sl_manager,
        mock_position_manager,
    ):
        """测试统计指标累积"""
        # 设置持仓
        position = create_position(symbol="ETH", size=1.0)
        mock_position_manager.set_position(position)

        # 设置市场数据
        market_data = market_data_dict_factory(symbols=["ETH"])

        # 执行多次检查
        for i in range(3):
            if i == 0:
                mock_tp_sl_manager.set_trigger(True, "take_profit")
            elif i == 1:
                mock_tp_sl_manager.set_trigger(True, "stop_loss")
            else:
                mock_tp_sl_manager.set_trigger(False, "")

            await position_closer.check_and_close_positions(market_data)

        # 验证累积统计
        stats = position_closer.get_stats()
        assert stats["total_checks"] == 3
        assert stats["tp_triggers"] == 1
        assert stats["sl_triggers"] == 1
        assert stats["close_success"] == 2

    def test_stats_reset(self, position_closer):
        """测试统计指标重置"""
        # 修改统计指标
        position_closer._stats["total_checks"] = 10
        position_closer._stats["tp_triggers"] = 5

        # 重置统计
        position_closer.reset_stats()

        # 验证重置后全为 0
        stats = position_closer.get_stats()
        assert all(v == 0 for v in stats.values())


class TestEdgeCases:
    """边缘案例测试"""

    @pytest.fixture
    def position_closer(
        self,
        mock_tp_sl_manager,
        mock_position_manager,
        mock_ioc_executor,
    ):
        """创建 PositionCloser 实例"""
        return PositionCloser(
            tp_sl_manager=mock_tp_sl_manager,
            position_manager=mock_position_manager,
            ioc_executor=mock_ioc_executor,
        )

    @pytest.mark.asyncio
    async def test_empty_market_data(self, position_closer):
        """测试空市场数据"""
        closed_orders = await position_closer.check_and_close_positions({})

        # 应该返回空列表（不报错）
        assert closed_orders == []

        # 验证统计
        stats = position_closer.get_stats()
        assert stats["total_checks"] == 1

    @pytest.mark.asyncio
    async def test_no_position_for_symbol(
        self,
        position_closer,
        market_data_dict_factory,
        mock_position_manager,
    ):
        """测试无持仓的交易对"""
        # 设置市场数据（但没有持仓）
        market_data = market_data_dict_factory(symbols=["ETH"])
        mock_position_manager.set_position(None)

        # 执行检查
        closed_orders = await position_closer.check_and_close_positions(market_data)

        # 应该返回空列表
        assert closed_orders == []

    @pytest.mark.asyncio
    async def test_zero_size_position(
        self,
        position_closer,
        create_position,
        market_data_dict_factory,
        mock_position_manager,
    ):
        """测试零持仓"""
        # 设置零持仓
        zero_position = create_position(symbol="ETH", size=0.0, entry_price=1500.0)
        mock_position_manager.set_position(zero_position)

        # 设置市场数据
        market_data = market_data_dict_factory(symbols=["ETH"])

        # 执行检查
        closed_orders = await position_closer.check_and_close_positions(market_data)

        # 应该跳过零持仓
        assert closed_orders == []
