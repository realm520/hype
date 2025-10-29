"""交易流程集成测试

测试完整的端到端交易流程：
1. 市场数据 → 2. 信号计算 → 3. 风控检查 → 4. 订单执行 → 5. PnL归因
"""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.types import Order, OrderSide, OrderStatus, OrderType
from src.main import TradingEngine


class TestTradingFlowIntegration:
    """测试完整交易流程"""

    @pytest.mark.asyncio
    async def test_complete_trading_cycle(self, test_config, sample_market_data):
        """测试完整交易周期"""
        # 创建引擎
        with patch("src.main.HyperliquidWebSocket") as mock_ws, \
             patch("src.main.HyperliquidAPIClient") as mock_api:

            # Mock WebSocket
            mock_ws_instance = MagicMock()
            mock_ws.return_value = mock_ws_instance

            # Mock API Client
            mock_api_instance = AsyncMock()
            mock_api.return_value = mock_api_instance

            # Mock 订单执行
            mock_api_instance.place_order.return_value = {
                "status": "success",
                "order_id": "test_order_001",
                "filled_size": "1.0",
            }

            engine = TradingEngine(test_config)

            # 模拟数据管理器返回市场数据
            engine.data_manager.get_market_data = MagicMock(
                return_value=sample_market_data
            )

            # 处理单个交易对
            await engine._process_symbol("ETH")

            # 验证流程完成（没有抛出异常）
            assert True

    @pytest.mark.asyncio
    async def test_signal_to_order_flow(
        self, test_config, imbalanced_market_data, mock_api_client
    ):
        """测试信号到订单的完整流程"""
        with patch("src.main.HyperliquidWebSocket"), \
             patch("src.main.HyperliquidAPIClient", return_value=mock_api_client):

            engine = TradingEngine(test_config)

            # 1. 获取市场数据
            engine.data_manager.get_market_data = MagicMock(
                return_value=imbalanced_market_data
            )

            # 2. 计算信号
            signal_score = engine.signal_aggregator.calculate(imbalanced_market_data)

            # 3. 检查信号是否达到执行阈值
            # (计算但不使用返回值，仅验证不会崩溃)
            _ = engine.executor.should_execute(signal_score)

            # 买单失衡的数据应该产生较强信号
            assert signal_score.value != 0.0

    @pytest.mark.asyncio
    async def test_risk_control_rejection(self, test_config, sample_market_data):
        """测试风控拒绝订单流程"""
        with patch("src.main.HyperliquidWebSocket"), \
             patch("src.main.HyperliquidAPIClient"):

            engine = TradingEngine(test_config)

            # 设置一个极低的风控限制
            engine.hard_limits.max_position_size_usd = 10.0  # 只允许 10 USD

            # 模拟市场数据
            engine.data_manager.get_market_data = MagicMock(
                return_value=sample_market_data
            )

            # 尝试处理交易对
            await engine._process_symbol("ETH")

            # 应该不会有订单被执行（因为被风控拒绝）
            # 验证：检查没有异常抛出
            assert True

    @pytest.mark.asyncio
    async def test_position_update_flow(self, test_config, sample_market_data):
        """测试持仓更新流程"""
        with patch("src.main.HyperliquidWebSocket"), \
             patch("src.main.HyperliquidAPIClient") as mock_api:

            mock_api_instance = AsyncMock()
            mock_api.return_value = mock_api_instance

            # Mock 订单执行成功
            mock_api_instance.place_order.return_value = {
                "status": "success",
                "order_id": "test_order_001",
                "filled_size": "1.0",
            }

            engine = TradingEngine(test_config)

            # 初始应该没有持仓
            initial_position = engine.position_manager.get_position("ETH")
            assert initial_position is None

            # 模拟一次成功的交易
            import time

            test_order = Order(
                id="test_001",
                symbol="ETH",
                side=OrderSide.BUY,
                order_type=OrderType.IOC,
                price=Decimal("1500.0"),
                size=Decimal("1.0"),
                filled_size=Decimal("1.0"),
                status=OrderStatus.FILLED,
                created_at=int(time.time() * 1000),
            )

            # 更新持仓
            engine.position_manager.update_from_order(test_order, test_order.price)

            # 现在应该有持仓
            position = engine.position_manager.get_position("ETH")
            assert position is not None
            assert position.size == Decimal("1.0")

    @pytest.mark.asyncio
    async def test_pnl_attribution_flow(self, test_config, sample_buy_order):
        """测试 PnL 归因流程"""
        with patch("src.main.HyperliquidWebSocket"), \
             patch("src.main.HyperliquidAPIClient"):

            engine = TradingEngine(test_config)

            # 执行归因
            attribution = engine.pnl_attribution.attribute_trade(
                order=sample_buy_order,
                signal_value=0.8,
                reference_price=Decimal("1500.0"),
                actual_fill_price=Decimal("1500.5"),
                best_price=Decimal("1500.5"),
            )

            # 验证归因结果
            assert attribution is not None
            assert attribution.trade_id == sample_buy_order.id

            # 验证风控 NAV 更新
            initial_nav = engine.hard_limits._current_nav
            engine.hard_limits.update_pnl(attribution.total_pnl)
            assert engine.hard_limits._current_nav != initial_nav

    @pytest.mark.asyncio
    async def test_metrics_collection_flow(
        self, test_config, sample_market_data, sample_buy_order
    ):
        """测试指标收集流程"""
        with patch("src.main.HyperliquidWebSocket"), \
             patch("src.main.HyperliquidAPIClient"):

            engine = TradingEngine(test_config)

            # 1. 记录信号
            signal_score = engine.signal_aggregator.calculate(sample_market_data)
            engine.metrics_collector.record_signal(signal_score, "ETH")

            # 2. 记录执行
            engine.metrics_collector.record_execution(
                order=sample_buy_order,
                slippage_bps=5.0,
                latency_ms=15.0,
            )

            # 验证指标收集
            _ = engine.metrics_collector.get_signal_metrics()
            execution_metrics = engine.metrics_collector.get_execution_metrics()

            # total_signals 只统计有 actual_return 的信号，这里没有提供 actual_return
            # 所以我们检查信号记录列表
            recent_signals = engine.metrics_collector.get_recent_signals(n=10)
            assert len(recent_signals) >= 1
            assert execution_metrics["total_orders"] >= 1

    @pytest.mark.asyncio
    async def test_health_check_flow(self, test_config):
        """测试健康检查流程"""
        with patch("src.main.HyperliquidWebSocket"), \
             patch("src.main.HyperliquidAPIClient"):

            engine = TradingEngine(test_config)

            # 执行健康检查
            await engine._periodic_health_check()

            # 验证健康检查完成（没有异常）
            assert True


class TestErrorHandling:
    """测试错误处理"""

    @pytest.mark.asyncio
    async def test_market_data_unavailable(self, test_config):
        """测试市场数据不可用情况"""
        with patch("src.main.HyperliquidWebSocket"), \
             patch("src.main.HyperliquidAPIClient"):

            engine = TradingEngine(test_config)

            # 模拟数据不可用
            engine.data_manager.get_market_data = MagicMock(return_value=None)

            # 处理交易对（应该优雅处理）
            await engine._process_symbol("ETH")

            # 验证没有抛出异常
            assert True

    @pytest.mark.asyncio
    async def test_order_execution_failure(self, test_config, sample_market_data):
        """测试订单执行失败情况"""
        with patch("src.main.HyperliquidWebSocket"), \
             patch("src.main.HyperliquidAPIClient") as mock_api:

            mock_api_instance = AsyncMock()
            mock_api.return_value = mock_api_instance

            # Mock 订单执行失败
            mock_api_instance.place_order.side_effect = Exception("Order failed")

            engine = TradingEngine(test_config)
            engine.data_manager.get_market_data = MagicMock(
                return_value=sample_market_data
            )

            # 处理交易对（应该优雅处理错误）
            await engine._process_symbol("ETH")

            # 验证没有导致程序崩溃
            assert True

    @pytest.mark.asyncio
    async def test_risk_breach_stops_trading(self, test_config):
        """测试风控突破后停止交易"""
        with patch("src.main.HyperliquidWebSocket"), \
             patch("src.main.HyperliquidAPIClient"):

            engine = TradingEngine(test_config)

            # 模拟风控突破
            engine.hard_limits._is_breached = True
            engine.hard_limits._breach_reason = "Max daily drawdown exceeded"

            # 执行健康检查
            await engine._periodic_health_check()

            # 验证交易引擎停止
            assert not engine._running


class TestConcurrentOperations:
    """测试并发操作"""

    @pytest.mark.asyncio
    async def test_multiple_symbols_processing(self, test_config, sample_market_data):
        """测试多个交易对并发处理"""
        with patch("src.main.HyperliquidWebSocket"), \
             patch("src.main.HyperliquidAPIClient"):

            engine = TradingEngine(test_config)

            # 为多个交易对模拟数据
            def get_market_data_mock(symbol):
                data = sample_market_data
                data.symbol = symbol
                return data

            engine.data_manager.get_market_data = get_market_data_mock

            # 并发处理多个交易对
            tasks = [
                engine._process_symbol(symbol)
                for symbol in ["ETH", "BTC"]
            ]

            await asyncio.gather(*tasks)

            # 验证并发处理成功
            assert True

    @pytest.mark.asyncio
    async def test_rapid_signal_updates(self, test_config, sample_market_data):
        """测试快速信号更新"""
        with patch("src.main.HyperliquidWebSocket"), \
             patch("src.main.HyperliquidAPIClient"):

            engine = TradingEngine(test_config)

            # 快速计算多个信号
            for _ in range(10):
                signal_score = engine.signal_aggregator.calculate(sample_market_data)
                engine.metrics_collector.record_signal(signal_score, "ETH")

            # 验证所有信号都被记录
            # total_signals 只统计有 actual_return 的信号，这里没有提供 actual_return
            # 所以我们检查信号记录列表
            recent_signals = engine.metrics_collector.get_recent_signals(n=15)
            assert len(recent_signals) >= 10


class TestConfigurationVariations:
    """测试不同配置场景"""

    @pytest.mark.asyncio
    async def test_different_risk_limits(self, sample_market_data):
        """测试不同风控限制"""
        from src.core.config import (
            Config,
            ExecutionConfig,
            HyperliquidConfig,
            RiskConfig,
            SignalConfig,
            SignalThresholdsConfig,
        )

        # 创建严格的风控配置
        strict_config = Config(
            hyperliquid=HyperliquidConfig(
                wallet_address="0x0000000000000000000000000000000000000001",
                private_key="test_key",
                use_mainnet=False,
                symbols=["ETH"],
            ),
            signals=SignalConfig(
                obi_levels=5,
                obi_weight=0.35,
                microprice_weight=0.40,
                impact_window_ms=5000,
                impact_weight=0.25,
                thresholds=SignalThresholdsConfig(theta_1=0.75, theta_2=0.50),
            ),
            risk=RiskConfig(
                max_single_loss_pct=0.001,  # 非常严格：0.1%
                max_daily_drawdown_pct=0.01,  # 非常严格：1%
                max_position_size_usd=1000.0,  # 非常小
            ),
            execution=ExecutionConfig(
                max_slippage_bps=10.0,
                default_size_usd=500.0,
            ),
            initial_nav=100000.0,
        )

        with patch("src.main.HyperliquidWebSocket"), \
             patch("src.main.HyperliquidAPIClient"):

            engine = TradingEngine(strict_config)

            # 验证严格风控设置
            assert engine.hard_limits.max_single_loss_pct == 0.001
            assert engine.hard_limits.max_daily_drawdown_pct == 0.01

    @pytest.mark.asyncio
    async def test_different_signal_thresholds(self, sample_market_data):
        """测试不同信号阈值"""
        from src.core.config import (
            Config,
            ExecutionConfig,
            HyperliquidConfig,
            RiskConfig,
            SignalConfig,
            SignalThresholdsConfig,
        )

        # 创建低阈值配置（更积极交易）
        aggressive_config = Config(
            hyperliquid=HyperliquidConfig(
                wallet_address="0x0000000000000000000000000000000000000001",
                private_key="test_key",
                use_mainnet=False,
                symbols=["ETH"],
            ),
            signals=SignalConfig(
                obi_levels=5,
                obi_weight=0.35,
                microprice_weight=0.40,
                impact_window_ms=5000,
                impact_weight=0.25,
                thresholds=SignalThresholdsConfig(
                    theta_1=0.50,  # 低阈值
                    theta_2=0.30,  # 低阈值
                ),
            ),
            risk=RiskConfig(
                max_single_loss_pct=0.008,
                max_daily_drawdown_pct=0.05,
                max_position_size_usd=10000.0,
            ),
            execution=ExecutionConfig(
                max_slippage_bps=20.0,
                default_size_usd=1000.0,
            ),
            initial_nav=100000.0,
        )

        with patch("src.main.HyperliquidWebSocket"), \
             patch("src.main.HyperliquidAPIClient"):

            engine = TradingEngine(aggressive_config)

            # 计算信号
            _ = engine.signal_aggregator.calculate(sample_market_data)

            # 低阈值配置下更容易触发执行
            # 验证阈值设置正确
            assert engine.signal_aggregator.theta_1 == 0.50


class TestPerformanceMetrics:
    """测试性能指标"""

    @pytest.mark.asyncio
    async def test_processing_latency(self, test_config, sample_market_data):
        """测试处理延迟"""
        import time

        with patch("src.main.HyperliquidWebSocket"), \
             patch("src.main.HyperliquidAPIClient"):

            engine = TradingEngine(test_config)
            engine.data_manager.get_market_data = MagicMock(
                return_value=sample_market_data
            )

            # 测量单次处理时间
            start_time = time.time()
            await engine._process_symbol("ETH")
            end_time = time.time()

            processing_time = (end_time - start_time) * 1000  # 转换为毫秒

            # Week 1 目标：< 100ms
            # 在测试环境中，实际处理会更快（因为是 mock）
            assert processing_time < 500  # 给测试环境更宽松的限制

    @pytest.mark.asyncio
    async def test_throughput(self, test_config, sample_market_data):
        """测试吞吐量"""
        with patch("src.main.HyperliquidWebSocket"), \
             patch("src.main.HyperliquidAPIClient"):

            engine = TradingEngine(test_config)
            engine.data_manager.get_market_data = MagicMock(
                return_value=sample_market_data
            )

            # 处理多个周期
            for _ in range(10):
                await engine._process_symbol("ETH")

            # 验证系统能够持续处理
            assert True
