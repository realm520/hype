"""Hyperliquid 混合执行交易引擎

Week 1.5 核心策略：Maker/Taker 混合执行 + 信号强度分级 + 成交率监控
"""

import asyncio
import signal
from decimal import Decimal
from typing import Any

import structlog

from src.analytics.maker_fill_rate_monitor import MakerFillRateMonitor
from src.analytics.metrics import MetricsCollector
from src.analytics.pnl_attribution import PnLAttribution
from src.core.config import Config, load_config, load_yaml_config
from src.core.data_feed import MarketDataManager
from src.core.logging import setup_logging
from src.core.types import OrderSide
from src.execution.hybrid_executor import HybridExecutor
from src.execution.ioc_executor import IOCExecutor
from src.execution.position_closer import PositionCloser
from src.execution.shallow_maker_executor import ShallowMakerExecutor
from src.execution.signal_classifier import SignalClassifier
from src.execution.signal_deduplicator import SignalDeduplicator
from src.execution.slippage_estimator import SlippageEstimator
from src.hyperliquid.api_client import HyperliquidAPIClient
from src.hyperliquid.websocket_client import HyperliquidWebSocket
from src.risk.hard_limits import HardLimits
from src.risk.position_manager import PositionManager
from src.risk.tp_sl_manager import TPSLManager
from src.signals.aggregator import create_aggregator_from_config

logger = structlog.get_logger()


class TradingEngine:
    """Week 1.5 混合执行交易引擎

    架构：
        数据层 → 信号层 → 分类层 → 执行层 → 风控层 → 分析层

    主循环：
        1. 获取市场数据
        2. 计算聚合信号
        3. 信号强度分级（HIGH/MEDIUM/LOW）
        4. 风控预检查
        5. 混合执行（Maker 优先 + IOC 回退）
        6. 更新持仓
        7. PnL 归因
        8. 成交率监控
        9. 指标记录
        10. 健康检查
    """

    def __init__(self, config: Config, dry_run: bool = False):
        """
        初始化交易引擎

        Args:
            config: 配置对象
            dry_run: 是否启用 Paper Trading 模拟模式
        """
        self.config = config
        self.dry_run = dry_run
        self.symbols = config.hyperliquid.symbols
        self._running = False
        self._health_check_interval = 60  # 健康检查间隔（秒）
        self._last_health_check = 0.0

        logger.info(
            "trading_engine_initializing",
            symbols=self.symbols,
            network="mainnet",  # 固定使用 mainnet
            strategy="week1.5_hybrid_maker_taker",
        )

        # 1. 数据层
        self.ws_client = HyperliquidWebSocket()
        self.data_manager = MarketDataManager(self.ws_client)

        # 2. 信号层
        signals_config = {
            "signals": {
                "obi": {
                    "levels": config.signals.obi_levels,
                    "weight": config.signals.obi_weight,
                },
                "microprice": {
                    "weight": config.signals.microprice_weight,
                },
                "impact": {
                    "window_ms": config.signals.impact_window_ms,
                    "weight": config.signals.impact_weight,
                },
            },
            "thresholds": {
                "theta_1": config.signals.thresholds.theta_1,
                "theta_2": config.signals.thresholds.theta_2,
            },
        }
        self.signal_aggregator = create_aggregator_from_config(signals_config)

        # 2.5. 信号分类层（Week 1.5 新增）
        self.signal_classifier = SignalClassifier(
            theta_1=config.signals.thresholds.theta_1,
            theta_2=config.signals.thresholds.theta_2,
        )

        # 3. 执行层（Week 1.5 混合执行）
        self.api_client = HyperliquidAPIClient(
            wallet_address=config.hyperliquid.wallet_address,
            private_key=config.hyperliquid.private_key,
            dry_run=dry_run,  # Paper Trading 模式下启用模拟
        )

        # IOC 执行器（用于回退）
        self.ioc_executor = IOCExecutor(self.api_client)

        # 浅被动 Maker 执行器
        # 注意：ExecutionConfig 不包含 default_size，使用固定值 0.001（小资金测试）
        self.shallow_maker = ShallowMakerExecutor(
            api_client=self.api_client,
            default_size=Decimal("0.001"),  # 小资金测试订单尺寸
            timeout_high=5.0,  # HIGH 置信度超时 5 秒
            timeout_medium=3.0,  # MEDIUM 置信度超时 3 秒
            tick_offset=Decimal("0.1"),  # BTC/ETH 标准 tick
            use_post_only=True,  # 确保成为 Maker
        )

        # 混合执行协调器
        self.executor = HybridExecutor(
            shallow_maker_executor=self.shallow_maker,
            ioc_executor=self.ioc_executor,
            enable_fallback=True,  # 启用 IOC 回退
            fallback_on_medium=False,  # MEDIUM 超时不回退
        )

        # 滑点估计器（仍用于分析）
        self.slippage_estimator = SlippageEstimator(
            max_slippage_bps=config.execution.max_slippage_bps
        )

        # 4. 风控层
        self.hard_limits = HardLimits(
            initial_nav=Decimal(str(config.initial_nav)),
            max_single_loss_pct=config.risk.max_single_loss_pct,
            max_daily_drawdown_pct=config.risk.max_daily_drawdown_pct,
            max_position_size_usd=Decimal(str(config.risk.max_position_size_usd)),
        )
        self.position_manager = PositionManager()

        # 5. 分析层
        self.pnl_attribution = PnLAttribution()
        self.metrics_collector = MetricsCollector()

        # 5.5. 成交率监控（Week 1.5 新增）
        self.fill_rate_monitor = MakerFillRateMonitor(
            window_size=100,  # 最近 100 次尝试
            alert_threshold_high=0.80,  # HIGH 置信度目标 80%
            alert_threshold_medium=0.75,  # MEDIUM 置信度目标 75%
            critical_threshold=0.60,  # 严重告警阈值 60%
        )

        # Week 2 Phase 2: TP/SL + 平仓协调器
        self.tp_sl_manager = TPSLManager(
            take_profit_pct=getattr(
                config.risk, "tp_sl", {}
            ).get("take_profit_pct", 0.02),
            stop_loss_pct=getattr(
                config.risk, "tp_sl", {}
            ).get("stop_loss_pct", 0.01),
        )

        self.position_closer = PositionCloser(
            tp_sl_manager=self.tp_sl_manager,
            position_manager=self.position_manager,
            ioc_executor=self.ioc_executor,
            max_position_age_seconds=getattr(
                config.risk, "tp_sl", {}
            ).get("max_position_age_seconds", 1800.0),
        )

        # Week 2 Phase 1: 信号去重器
        self.signal_deduplicator = SignalDeduplicator(
            cooldown_seconds=getattr(
                config.signals, "dedup", {}
            ).get("cooldown_seconds", 5.0),
            change_threshold=getattr(
                config.signals, "dedup", {}
            ).get("change_threshold", 0.15),
            decay_factor=getattr(
                config.signals, "dedup", {}
            ).get("decay_factor", 0.85),
            max_same_direction=getattr(
                config.signals, "dedup", {}
            ).get("max_same_direction", 3),
        )

    async def start(self) -> None:
        """启动交易引擎"""
        logger.info("trading_engine_starting", symbols=self.symbols)

        try:
            # 启动数据订阅
            await self.data_manager.start(self.symbols)

            # 等待数据稳定
            logger.info("waiting_for_initial_data")
            await asyncio.sleep(2)

            # 设置运行标志
            self._running = True

            # 启动主循环
            await self._main_loop()

        except Exception as e:
            logger.error("trading_engine_start_error", error=str(e), exc_info=True)
            raise

    async def stop(self) -> None:
        """停止交易引擎"""
        logger.info("trading_engine_stopping")

        self._running = False

        # 停止数据管理器
        await self.data_manager.stop()

        logger.info("trading_engine_stopped")

    async def _main_loop(self) -> None:
        """主事件循环"""
        logger.info("main_loop_started")

        while self._running:
            try:
                # Week 2 Phase 2: 先检查所有持仓，执行平仓
                market_data_dict = {
                    symbol: md
                    for symbol in self.symbols
                    if (md := self.data_manager.get_market_data(symbol)) is not None
                }
                closed_orders = await self.position_closer.check_and_close_positions(
                    market_data_dict
                )

                # 记录平仓订单
                for order in closed_orders:
                    logger.info(
                        "position_closed",
                        symbol=order.symbol,
                        order_id=order.id,
                        reason="tp_sl_or_timeout",
                    )

                # 遍历所有交易对（开仓逻辑）
                for symbol in self.symbols:
                    await self._process_symbol(symbol)

                # 周期性健康检查
                await self._periodic_health_check()

                # 100ms 循环周期
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error("main_loop_error", error=str(e), exc_info=True)
                # 继续运行，但记录错误
                await asyncio.sleep(1)

    async def _process_symbol(self, symbol: str) -> None:
        """
        处理单个交易对

        Args:
            symbol: 交易对
        """
        try:
            # 1. 获取市场数据
            market_data = self.data_manager.get_market_data(symbol)
            if not market_data:
                return

            # 2. 计算聚合信号
            signal_score = self.signal_aggregator.calculate(market_data)

            # Week 2 Phase 1: 信号去重
            current_position = self.position_manager.get_position(symbol)
            filtered_signal = self.signal_deduplicator.filter(
                signal_score, market_data, current_position
            )

            if filtered_signal is None:
                return  # 信号被去重器拒绝

            signal_score = filtered_signal  # 使用去重后的信号

            # 3. 信号强度分级（Week 1.5 新增）
            confidence_level = self.signal_classifier.classify(signal_score.value)
            # 更新 signal_score 的置信度
            from dataclasses import replace

            signal_score = replace(signal_score, confidence=confidence_level)

            # 记录信号
            self.metrics_collector.record_signal(signal_score, symbol)

            # 4. 判断是否执行（基于置信度）
            if signal_score.value == 0:
                return

            # 5. 风控预检查
            current_position = self.position_manager.get_position(symbol)
            # 修改：传入持仓数量（币本位），而非持仓价值
            current_position_size = (
                current_position.size if current_position else Decimal("0")
            )

            # 创建模拟订单进行风控检查
            from src.core.types import Order, OrderStatus, OrderType

            side = self._determine_side(signal_score.value)
            if not side:
                return

            # 估算订单尺寸（使用默认尺寸）
            order_size = self.shallow_maker.default_size

            test_order = Order(
                id="test",
                symbol=symbol,
                side=side,
                order_type=OrderType.LIMIT,  # Week 1.5 默认使用限价单
                price=market_data.mid_price,
                size=order_size,
                filled_size=Decimal("0"),
                status=OrderStatus.PENDING,
                created_at=market_data.timestamp,
            )

            is_allowed, reject_reason = self.hard_limits.check_order(
                test_order, market_data.mid_price, current_position_size  # 修改：传入币数量
            )

            if not is_allowed:
                logger.warning(
                    "order_rejected_by_risk_control",
                    symbol=symbol,
                    reason=reject_reason,
                    confidence=signal_score.confidence.name,
                )
                return

            # 6. 混合执行（Week 1.5 核心逻辑）
            order = await self.executor.execute(
                signal_score=signal_score,
                market_data=market_data,
                size=order_size,
            )

            # 7. 记录成交率（无论是否成交）
            if signal_score.confidence.name in ["HIGH", "MEDIUM"]:
                from src.core.types import ConfidenceLevel

                confidence_enum = ConfidenceLevel[signal_score.confidence.name]

                # 创建一个订单对象用于记录
                if order is not None:
                    # 成交：使用实际订单
                    self.fill_rate_monitor.record_maker_attempt(
                        order=order,
                        confidence=confidence_enum,
                        filled=True,
                    )
                else:
                    # 未成交：创建临时订单对象
                    dummy_order = Order(
                        id="unfilled",
                        symbol=symbol,
                        side=side,
                        order_type=OrderType.LIMIT,
                        price=market_data.mid_price,
                        size=order_size,
                        filled_size=Decimal("0"),
                        status=OrderStatus.CANCELLED,
                        created_at=market_data.timestamp,
                    )
                    self.fill_rate_monitor.record_maker_attempt(
                        order=dummy_order,
                        confidence=confidence_enum,
                        filled=False,
                    )

            if not order:
                return

            # 8. 更新持仓
            self.position_manager.update_from_order(order, order.price)

            # 9. PnL 归因
            attribution = self.pnl_attribution.attribute_trade(
                order=order,
                signal_value=signal_score.value,
                reference_price=market_data.mid_price,
                actual_fill_price=order.price,
                best_price=market_data.bids[0].price
                if order.side.name == "SELL"
                else market_data.asks[0].price,
            )

            # 更新风控净值
            self.hard_limits.update_pnl(attribution.total_pnl)

            # 10. 记录执行指标
            slippage_bps = self.slippage_estimator.calculate_actual_slippage(
                order.price, market_data.mid_price, order.side
            )
            self.metrics_collector.record_execution(
                order, slippage_bps, latency_ms=10.0  # 简化，实际应测量
            )

            logger.info(
                "trade_completed",
                symbol=symbol,
                order_id=order.id,
                side=order.side.name,
                order_type=order.order_type.name,
                confidence=signal_score.confidence.name,
                size=float(order.size),
                pnl=float(attribution.total_pnl),
                alpha_pct=attribution.alpha_percentage,
            )

        except Exception as e:
            logger.error(
                "symbol_processing_error",
                symbol=symbol,
                error=str(e),
                exc_info=True,
            )

    def _determine_side(self, signal_value: float) -> OrderSide | None:
        """确定订单方向"""
        if signal_value > 0:
            return OrderSide.BUY
        elif signal_value < 0:
            return OrderSide.SELL
        else:
            return None

    async def _periodic_health_check(self) -> None:
        """周期性健康检查"""
        import time

        now = time.time()

        if now - self._last_health_check < self._health_check_interval:
            return

        self._last_health_check = now

        # 1. Alpha 健康检查
        is_healthy, message = self.pnl_attribution.check_alpha_health()
        if not is_healthy:
            logger.warning("alpha_health_warning", message=message)

        # 2. 风控状态
        risk_status = self.hard_limits.get_status()
        if risk_status["is_breached"]:
            logger.error("risk_breach_detected", reason=risk_status["breach_reason"])
            self._running = False  # 停止交易
            return

        # 3. 成交率监控（Week 1.5 新增）
        fill_rate_stats = self.fill_rate_monitor.get_statistics()

        # 检查成交率健康状态
        from src.core.types import ConfidenceLevel

        high_healthy = self.fill_rate_monitor.is_healthy(ConfidenceLevel.HIGH)
        medium_healthy = self.fill_rate_monitor.is_healthy(ConfidenceLevel.MEDIUM)

        # 检查是否触发严重告警
        high_critical = self.fill_rate_monitor.is_critical(ConfidenceLevel.HIGH)
        medium_critical = self.fill_rate_monitor.is_critical(ConfidenceLevel.MEDIUM)

        if high_critical or medium_critical:
            logger.critical(
                "maker_fill_rate_critical",
                high_fill_rate=fill_rate_stats["high"]["window_fill_rate"],
                medium_fill_rate=fill_rate_stats["medium"]["window_fill_rate"],
                action="consider_strategy_adjustment",
            )

        # 4. 执行统计（Week 1.5 新增）
        executor_stats = self.executor.get_statistics()

        # 5. 生成报告
        pnl_report = self.pnl_attribution.get_attribution_report()
        metrics_summary = self.metrics_collector.get_metrics_summary(risk_status)

        logger.info(
            "health_check_completed",
            # Alpha 健康
            alpha_healthy=is_healthy,
            alpha_pct=pnl_report["percentages"]["alpha"],
            # 信号质量
            ic=metrics_summary["signal_quality"]["ic"],
            # 风控状态
            nav=risk_status["current_nav"],
            daily_pnl=risk_status["daily_pnl"],
            # Week 1.5 特有指标
            maker_fill_rate_high=fill_rate_stats["high"]["window_fill_rate"],
            maker_fill_rate_medium=fill_rate_stats["medium"]["window_fill_rate"],
            maker_healthy=high_healthy and medium_healthy,
            execution_stats={
                "total_signals": executor_stats["total_signals"],
                "maker_executions": executor_stats["maker_executions"],
                "ioc_executions": executor_stats["ioc_executions"],
                "fallback_executions": executor_stats["fallback_executions"],
                "maker_fill_rate": f"{executor_stats['maker_fill_rate']:.1f}%",
                "ioc_fill_rate": f"{executor_stats['ioc_fill_rate']:.1f}%",
                # skip_rate 不在 executor_stats 中，使用 skipped_signals 计算
                "skip_rate": f"{(executor_stats['skipped_signals'] / max(executor_stats['total_signals'], 1) * 100):.1f}%",
            },
        )


async def main() -> None:
    """主函数"""
    # 加载配置
    config_path = "config/paper_trading.yaml"
    config = load_config(config_path)

    # 检测 Paper Trading 模式
    yaml_config = load_yaml_config(config_path)
    is_paper_trading = yaml_config.get("paper_trading", {}).get("enabled", False)

    # 配置日志系统
    setup_logging()

    logger = structlog.get_logger(__name__)
    logger.info(
        "hyperliquid_hybrid_trading_system_starting",
        version="week1.5",
        strategy="maker_taker_hybrid",
        paper_trading=is_paper_trading,
    )

    # 创建引擎
    engine = TradingEngine(config, dry_run=is_paper_trading)

    # 设置信号处理
    def shutdown_handler(signum: int, frame: Any) -> None:
        logger.info("shutdown_signal_received", signal=signum)
        asyncio.create_task(engine.stop())

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        # 启动引擎
        await engine.start()

    except KeyboardInterrupt:
        logger.info("keyboard_interrupt_received")

    except Exception as e:
        logger.error("system_error", error=str(e), exc_info=True)

    finally:
        await engine.stop()
        logger.info("system_shutdown_complete")


if __name__ == "__main__":
    asyncio.run(main())
