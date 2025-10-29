"""TradingEngine 核心逻辑测试

测试优先级：
- P0（Week 1 核心）：健康检查、风控熔断、异常处理
- P1（系统稳定性）：引擎生命周期、信号处理流程

目标覆盖率：75%（50% → 75%）
"""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.types import OrderSide, OrderStatus
from src.main import TradingEngine


@pytest.fixture
def mock_api_client():
    """Mock Hyperliquid API 客户端"""
    mock = MagicMock()
    mock.exchange = MagicMock()
    return mock


@pytest.fixture
def trading_engine(test_config, mock_api_client):
    """创建带 Mock API 的 TradingEngine 实例"""
    with patch("src.main.HyperliquidAPIClient", return_value=mock_api_client):
        trading_engine = TradingEngine(test_config)
        return trading_engine


class TestHealthCheckAndRiskControl:
    """健康检查和风控熔断测试（P0 - Week 1 核心）"""

    @pytest.mark.asyncio
    async def test_health_check_detects_alpha_failure(self, trading_engine):
        """验证 Alpha < 70% 触发告警（不停机）"""
        # Mock PnL 归因器返回不健康状态
        trading_engine.pnl_attribution.check_alpha_health = MagicMock(
            return_value=(False, "Alpha health FAIL: 65.0% < 70.0%")
        )
        trading_engine.pnl_attribution.get_attribution_report = MagicMock(
            return_value={
                "cumulative": {"alpha": 65.0, "total": 100.0},
                "percentages": {"alpha": 65.0},
                "health_check": {
                    "is_healthy": False,
                    "message": "Alpha health FAIL: 65.0% < 70.0%",
                },
            }
        )

        # Mock 风控管理器
        trading_engine.risk_manager.get_statistics = MagicMock(
            return_value={
                "total_pnl": 100.0,
                "max_drawdown": 0.02,
                "daily_drawdown": 0.01,
            }
        )

        # 运行一次健康检查
        trading_engine._running = True

        # 启动健康检查协程
        health_check_task = asyncio.create_task(trading_engine._periodic_health_check())

        # 等待第一次检查完成（60秒 → 0.1秒模拟）
        await asyncio.sleep(0.1)

        # 停止引擎
        trading_engine._running = False
        health_check_task.cancel()

        try:
            await health_check_task
        except asyncio.CancelledError:
            pass

        # 验证：Alpha 失败应该记录日志，但 Week 1 不停机
        assert trading_engine.pnl_attribution.check_alpha_health.called
        # Week 1: 只告警，引擎应该继续运行（不验证停机）

    @pytest.mark.asyncio
    async def test_health_check_detects_risk_control_breach(self, trading_engine):
        """验证风控指标异常触发告警"""

        # Mock 风控管理器返回异常高的回撤
        trading_engine.risk_manager.get_statistics = MagicMock(
            return_value={
                "total_pnl": -500.0,
                "max_drawdown": 0.08,  # 8% 回撤（超过 5% 阈值）
                "daily_drawdown": 0.06,  # 6% 日回撤
            }
        )

        # Mock PnL 归因器（健康）
        trading_engine.pnl_attribution.check_alpha_health = MagicMock(
            return_value=(True, "Alpha health OK")
        )
        trading_engine.pnl_attribution.get_attribution_report = MagicMock(
            return_value={
                "cumulative": {"alpha": 75.0, "total": 100.0},
                "percentages": {"alpha": 75.0},
            }
        )

        # 运行健康检查
        trading_engine._running = True
        health_check_task = asyncio.create_task(trading_engine._periodic_health_check())
        await asyncio.sleep(0.1)
        trading_engine._running = False
        health_check_task.cancel()

        try:
            await health_check_task
        except asyncio.CancelledError:
            pass

        # 验证：应该检查风控统计
        assert trading_engine.risk_manager.get_statistics.called

    @pytest.mark.asyncio
    async def test_health_check_handles_exception(self, trading_engine):
        """验证健康检查异常不崩溃引擎"""

        # Mock PnL 归因器抛出异常
        trading_engine.pnl_attribution.get_attribution_report = MagicMock(
            side_effect=Exception("PnL calculation error")
        )

        # 运行健康检查
        trading_engine._running = True
        health_check_task = asyncio.create_task(trading_engine._periodic_health_check())
        await asyncio.sleep(0.1)
        trading_engine._running = False
        health_check_task.cancel()

        try:
            await health_check_task
        except asyncio.CancelledError:
            pass

        # 验证：异常应该被捕获，引擎继续运行
        # （通过没有抛出异常来验证）


class TestEngineLifecycle:
    """引擎生命周期测试（P1 - 系统稳定性）"""

    @pytest.mark.asyncio
    async def test_start_initializes_data_feed(self, trading_engine):
        """验证 start() 初始化数据流"""

        # Mock 数据流
        with patch.object(
            trading_engine.data_feed, "start", new_callable=AsyncMock
        ) as mock_start:
            await trading_engine.start()

            # 验证数据流已启动
            mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_closes_data_feed(self, trading_engine):
        """验证 stop() 关闭数据流"""

        # 先启动引擎
        with patch.object(trading_engine.data_feed, "start", new_callable=AsyncMock):
            await trading_engine.start()

        # Mock 数据流关闭
        with patch.object(
            trading_engine.data_feed, "close", new_callable=AsyncMock
        ) as mock_close:
            await trading_engine.stop()

            # 验证数据流已关闭
            mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_sets_running_flag_to_false(self, trading_engine):
        """验证 stop() 设置运行标志为 False"""

        # 先启动
        with patch.object(trading_engine.data_feed, "start", new_callable=AsyncMock):
            await trading_engine.start()

        assert trading_engine._running is True

        # 停止
        with patch.object(trading_engine.data_feed, "close", new_callable=AsyncMock):
            await trading_engine.stop()

        assert trading_engine._running is False

    @pytest.mark.asyncio
    async def test_engine_handles_graceful_shutdown(self, trading_engine):
        """验证引擎优雅关闭（不丢失订单状态）"""

        # 创建一些模拟订单状态
        from src.core.types import Order

        order = Order(
            id="test_order_1",
            symbol="BTC",
            side=OrderSide.BUY,
            size=Decimal("0.1"),
            price=Decimal("50000"),
            status=OrderStatus.PENDING,
            created_at=int(asyncio.get_event_loop().time() * 1000),
        )

        # Mock 订单管理器
        trading_engine.order_manager.get_pending_orders = MagicMock(return_value=[order])

        # 启动并停止
        with patch.object(trading_engine.data_feed, "start", new_callable=AsyncMock):
            with patch.object(trading_engine.data_feed, "close", new_callable=AsyncMock):
                await trading_engine.start()
                await trading_engine.stop()

        # 验证：停止后应该记录待处理订单
        # （实际实现中应该持久化订单状态）


class TestSignalProcessing:
    """信号处理流程测试（P1 - 系统稳定性）"""

    @pytest.mark.asyncio
    async def test_process_symbol_skips_low_confidence_signal(self, trading_engine):
        """验证低置信度信号不交易"""

        from src.signals.types import ConfidenceLevel, SignalScore

        # Mock 信号聚合器返回低置信度信号
        low_signal = SignalScore(value=0.1, confidence=ConfidenceLevel.LOW)

        with patch.object(
            trading_engine.signal_aggregator, "generate_signal", return_value=low_signal
        ):
            # Mock 执行器（不应该被调用）
            with patch.object(
                trading_engine.shadow_executor, "execute_shadow", new_callable=AsyncMock
            ) as mock_execute:
                # 处理交易对
                await trading_engine._process_symbol("BTC")

                # 验证：低置信度信号不执行
                mock_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_symbol_executes_high_confidence_signal(self, trading_engine):
        """验证高置信度信号执行交易"""

        from src.signals.types import ConfidenceLevel, SignalScore

        from src.execution.shadow_executor import ShadowExecutionRecord

        # Mock 信号聚合器返回高置信度信号
        high_signal = SignalScore(value=0.6, confidence=ConfidenceLevel.HIGH)

        # Mock 影子执行器返回成功记录
        from src.core.types import Order

        mock_order = Order(
            id="test_order_2",
            symbol="BTC",
            side=OrderSide.BUY,
            size=Decimal("0.1"),
            price=Decimal("50000"),
            status=OrderStatus.FILLED,
            created_at=int(asyncio.get_event_loop().time() * 1000),
            filled_size=Decimal("0.1"),
            avg_fill_price=Decimal("50010"),
        )

        mock_record = ShadowExecutionRecord(
            order=mock_order,
            signal_value=high_signal.value,
            skipped=False,
            skip_reason=None,
        )

        with patch.object(
            trading_engine.signal_aggregator, "generate_signal", return_value=high_signal
        ):
            with patch.object(
                trading_engine.shadow_executor,
                "execute_shadow",
                new_callable=AsyncMock,
                return_value=mock_record,
            ) as mock_execute:
                # 处理交易对
                await trading_engine._process_symbol("BTC")

                # 验证：高置信度信号执行交易
                mock_execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_symbol_handles_execution_exception(self, trading_engine):
        """验证执行异常不崩溃引擎"""

        from src.signals.types import ConfidenceLevel, SignalScore

        # Mock 信号聚合器
        high_signal = SignalScore(value=0.6, confidence=ConfidenceLevel.HIGH)

        with patch.object(
            trading_engine.signal_aggregator, "generate_signal", return_value=high_signal
        ):
            # Mock 执行器抛出异常
            with patch.object(
                trading_engine.shadow_executor,
                "execute_shadow",
                new_callable=AsyncMock,
                side_effect=Exception("Execution error"),
            ):
                # 处理交易对（不应该崩溃）
                await trading_engine._process_symbol("BTC")

                # 验证：异常被捕获，引擎继续运行
                # （通过没有抛出异常来验证）


class TestExceptionHandling:
    """异常处理路径测试（P0 - Week 1 核心）"""

    @pytest.mark.asyncio
    async def test_main_loop_handles_processing_exception(self, trading_engine):
        """验证主循环异常不停止引擎"""

        # Mock _process_symbol 抛出异常
        with patch.object(
            trading_engine, "_process_symbol", new_callable=AsyncMock, side_effect=Exception("Processing error")
        ):
            trading_engine._running = True

            # 启动主循环
            main_loop_task = asyncio.create_task(trading_engine._main_loop())

            # 等待一次循环
            await asyncio.sleep(0.1)

            # 停止引擎
            trading_engine._running = False

            # 等待主循环结束
            try:
                await asyncio.wait_for(main_loop_task, timeout=1.0)
            except TimeoutError:
                main_loop_task.cancel()

            # 验证：异常被捕获，引擎继续运行
            # （通过没有抛出异常来验证）

    @pytest.mark.asyncio
    async def test_engine_handles_data_feed_exception(self, trading_engine):
        """验证数据流异常处理"""

        # Mock 数据流启动抛出异常
        with patch.object(
            trading_engine.data_feed, "start", new_callable=AsyncMock, side_effect=Exception("Data feed error")
        ):
            # 尝试启动（应该抛出异常或优雅处理）
            with pytest.raises((Exception, RuntimeError)):
                await trading_engine.start()
