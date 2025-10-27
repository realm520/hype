"""Hyperliquid IOC 交易引擎

Week 1 核心策略：高置信度信号 + IOC 执行 + 硬限制风控
"""

import asyncio
import signal
from decimal import Decimal
from typing import Any

import structlog

from src.analytics.metrics import MetricsCollector
from src.analytics.pnl_attribution import PnLAttribution
from src.core.config import Config, load_config
from src.core.data_feed import MarketDataManager
from src.core.logging import setup_logging
from src.core.types import OrderSide
from src.execution.ioc_executor import IOCExecutor
from src.execution.order_manager import OrderManager
from src.execution.slippage_estimator import SlippageEstimator
from src.hyperliquid.api_client import HyperliquidAPIClient
from src.hyperliquid.websocket_client import HyperliquidWebSocket
from src.risk.hard_limits import HardLimits
from src.risk.position_manager import PositionManager
from src.signals.aggregator import create_aggregator_from_config

logger = structlog.get_logger()


class TradingEngine:
    """Week 1 IOC 交易引擎

    架构：
        数据层 → 信号层 → 执行层 → 风控层 → 分析层

    主循环：
        1. 获取市场数据
        2. 计算聚合信号
        3. 风控预检查
        4. 执行订单（IOC）
        5. 更新持仓
        6. PnL 归因
        7. 指标记录
        8. 健康检查
    """

    def __init__(self, config: Config):
        """
        初始化交易引擎

        Args:
            config: 配置对象
        """
        self.config = config
        self.symbols = config.hyperliquid.symbols
        self._running = False
        self._health_check_interval = 60  # 健康检查间隔（秒）
        self._last_health_check = 0.0

        logger.info(
            "trading_engine_initializing",
            symbols=self.symbols,
            use_mainnet=config.hyperliquid.use_mainnet,
        )

        # 1. 数据层
        self.ws_client = HyperliquidWebSocket(config.hyperliquid.use_mainnet)
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

        # 3. 执行层
        self.api_client = HyperliquidAPIClient(
            wallet_address=config.hyperliquid.wallet_address,
            private_key=config.hyperliquid.private_key,
            use_mainnet=config.hyperliquid.use_mainnet,
        )
        self.executor = IOCExecutor(self.api_client)
        self.slippage_estimator = SlippageEstimator(
            max_slippage_bps=config.execution.max_slippage_bps
        )
        self.order_manager = OrderManager(self.executor, self.slippage_estimator)

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

        logger.info("trading_engine_initialized")

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
                # 遍历所有交易对
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

            # 记录信号
            self.metrics_collector.record_signal(signal_score, symbol)

            # 3. 判断是否执行
            if not self.executor.should_execute(signal_score):
                return

            # 4. 风控预检查
            current_position = self.position_manager.get_position(symbol)
            current_position_value = (
                current_position.position_value_usd if current_position else Decimal("0")
            )

            # 创建模拟订单进行风控检查
            from src.core.types import Order, OrderStatus, OrderType

            side = (
                self._determine_side(signal_score.value)
                if signal_score.value != 0
                else None
            )
            if not side:
                return

            test_order = Order(
                id="test",
                symbol=symbol,
                side=side,
                order_type=OrderType.IOC,
                price=market_data.mid_price,
                size=self.executor.default_size,
                filled_size=Decimal("0"),
                status=OrderStatus.PENDING,
                created_at=market_data.timestamp,
            )

            is_allowed, reject_reason = self.hard_limits.check_order(
                test_order, market_data.mid_price, current_position_value
            )

            if not is_allowed:
                logger.warning(
                    "order_rejected_by_risk_control",
                    symbol=symbol,
                    reason=reject_reason,
                )
                return

            # 5. 执行订单
            order = await self.order_manager.execute_signal(
                signal_score, market_data, size=self.executor.default_size
            )

            if not order:
                return

            # 6. 更新持仓
            self.position_manager.update_from_order(order, order.price)

            # 7. PnL 归因
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

            # 8. 记录执行指标
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

        # 3. 生成报告
        pnl_report = self.pnl_attribution.get_attribution_report()
        metrics_summary = self.metrics_collector.get_metrics_summary(risk_status)

        logger.info(
            "health_check_completed",
            alpha_healthy=is_healthy,
            alpha_pct=pnl_report["percentages"]["alpha"],
            ic=metrics_summary["signal_quality"]["ic"],
            nav=risk_status["current_nav"],
            daily_pnl=risk_status["daily_pnl"],
        )


async def main() -> None:
    """主函数"""
    # 加载配置
    config = load_config("config/week1_ioc.yaml")

    # 配置日志系统
    setup_logging()

    logger = structlog.get_logger(__name__)
    logger.info("hyperliquid_ioc_trading_system_starting")

    # 创建引擎
    engine = TradingEngine(config)

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
