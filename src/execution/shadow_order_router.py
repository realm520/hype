"""影子订单路由器

Week 2 影子交易系统：模拟混合订单执行策略（IOC + 限价单）。
"""

import asyncio
import time
from decimal import Decimal

import structlog

from src.core.types import (
    ConfidenceLevel,
    MarketData,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    SignalScore,
)
from src.execution.fill_simulator import FillSimulator
from src.execution.shadow_executor import ShadowExecutionRecord, ShadowIOCExecutor

logger = structlog.get_logger()


class ShadowLimitExecutor:
    """影子限价单执行器

    模拟限价单（Post-only）执行：
        1. 贴盘口价格下限价单
        2. 模拟等待成交（基于订单簿流动性）
        3. 超时未成交则撤单
    """

    def __init__(
        self,
        fill_simulator: FillSimulator,
        default_size: Decimal = Decimal("0.01"),
        timeout_seconds: float = 5.0,
        use_post_only: bool = True,
    ):
        """
        初始化影子限价单执行器

        Args:
            fill_simulator: 成交模拟器
            default_size: 默认订单大小
            timeout_seconds: 成交超时时间
            use_post_only: 是否使用 Post-only
        """
        self.fill_simulator = fill_simulator
        self.default_size = default_size
        self.timeout_seconds = timeout_seconds
        self.use_post_only = use_post_only

        logger.info(
            "shadow_limit_executor_initialized",
            default_size=float(default_size),
            timeout_seconds=timeout_seconds,
            use_post_only=use_post_only,
        )

    async def execute(
        self,
        signal_score: SignalScore,
        market_data: MarketData,
        size: Decimal | None = None,
    ) -> ShadowExecutionRecord:
        """
        执行影子限价单

        Args:
            signal_score: 信号评分
            market_data: 市场数据
            size: 订单大小

        Returns:
            ShadowExecutionRecord: 影子执行记录
        """
        signal_timestamp = signal_score.timestamp
        decision_timestamp = int(time.time() * 1000)

        signal_latency_ms = decision_timestamp - signal_timestamp

        try:
            # 检查置信度（仅接受 MEDIUM）
            if signal_score.confidence != ConfidenceLevel.MEDIUM:
                return self._create_skipped_record(
                    signal_score,
                    market_data,
                    signal_timestamp,
                    decision_timestamp,
                    "wrong_confidence",
                )

            # 确定订单方向
            if signal_score.value > 0:
                side = OrderSide.BUY
            elif signal_score.value < 0:
                side = OrderSide.SELL
            else:
                return self._create_skipped_record(
                    signal_score,
                    market_data,
                    signal_timestamp,
                    decision_timestamp,
                    "zero_signal",
                )

            # 计算订单参数
            order_size = size if size is not None else self.default_size
            order_price = self._calculate_limit_price(market_data, side)

            # 创建订单对象
            order = self._create_order(
                market_data.symbol, side, order_size, order_price, decision_timestamp
            )

            # 模拟限价单成交（等待流动性）
            execution_timestamp = int(time.time() * 1000)

            # 简化模拟：假设 70% 的限价单能够在超时前成交
            # 真实情况应该基于订单簿深度和历史成交率
            import random

            fill_probability = 0.7  # 70% 成交率
            await asyncio.sleep(0.001)  # 模拟等待时间

            if random.random() < fill_probability:
                # 限价单成交（Maker 费率 +0.015%）
                fill_result = self.fill_simulator.simulate_limit_fill(
                    market_data=market_data,
                    side=side,
                    size=order_size,
                    price=order_price,
                )

                order.status = OrderStatus.FILLED
                order.filled_size = fill_result.filled_size

                logger.info(
                    "shadow_limit_filled",
                    symbol=market_data.symbol,
                    order_id=order.id,
                    side=side.name,
                    size=float(order_size),
                    filled_size=float(fill_result.filled_size),
                    slippage=float(fill_result.slippage),
                    fee_bps=0.15,  # Maker 费率 1.5 bps（正费率）
                )

                execution_result = fill_result.to_execution_result()

            else:
                # 限价单超时未成交
                fill_result = None
                execution_result = None

                logger.info(
                    "shadow_limit_timeout",
                    symbol=market_data.symbol,
                    order_id=order.id,
                    timeout_seconds=self.timeout_seconds,
                )

            # 计算延迟
            decision_latency_ms = execution_timestamp - decision_timestamp
            total_latency_ms = execution_timestamp - signal_timestamp

            return ShadowExecutionRecord(
                order=order,
                fill_result=fill_result,
                execution_result=execution_result,
                signal_timestamp=signal_timestamp,
                decision_timestamp=decision_timestamp,
                execution_timestamp=execution_timestamp,
                signal_latency_ms=signal_latency_ms,
                decision_latency_ms=decision_latency_ms,
                total_latency_ms=total_latency_ms,
                skipped=(fill_result is None),
                skip_reason="timeout" if fill_result is None else None,
            )

        except Exception as e:
            logger.error(
                "shadow_limit_execution_error",
                symbol=market_data.symbol,
                error=str(e),
                exc_info=True,
            )
            return self._create_skipped_record(
                signal_score,
                market_data,
                signal_timestamp,
                decision_timestamp,
                f"error: {str(e)}",
            )

    def _calculate_limit_price(
        self, market_data: MarketData, side: OrderSide
    ) -> Decimal:
        """计算限价单价格（贴盘口）"""
        if side == OrderSide.BUY:
            best_bid = market_data.bids[0]
            price = best_bid.price
        else:
            best_ask = market_data.asks[0]
            price = best_ask.price

        return price

    def _create_order(
        self,
        symbol: str,
        side: OrderSide,
        size: Decimal,
        price: Decimal,
        timestamp: int,
    ) -> Order:
        """创建订单对象"""
        import uuid

        return Order(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            price=price,
            size=size,
            filled_size=Decimal("0"),
            status=OrderStatus.PENDING,
            created_at=timestamp,
            error_message=None,
        )

    def _create_skipped_record(
        self,
        signal_score: SignalScore,
        market_data: MarketData,
        signal_timestamp: int,
        decision_timestamp: int,
        reason: str,
    ) -> ShadowExecutionRecord:
        """创建跳过记录"""
        execution_timestamp = int(time.time() * 1000)

        order = Order(
            id="skipped",
            symbol=market_data.symbol,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("0"),
            size=Decimal("0"),
            filled_size=Decimal("0"),
            status=OrderStatus.REJECTED,
            created_at=decision_timestamp,
            error_message=reason,
        )

        return ShadowExecutionRecord(
            order=order,
            fill_result=None,
            execution_result=None,
            signal_timestamp=signal_timestamp,
            decision_timestamp=decision_timestamp,
            execution_timestamp=execution_timestamp,
            signal_latency_ms=float(decision_timestamp - signal_timestamp),
            decision_latency_ms=float(execution_timestamp - decision_timestamp),
            total_latency_ms=float(execution_timestamp - signal_timestamp),
            skipped=True,
            skip_reason=reason,
        )


class ShadowOrderRouter:
    """影子订单路由器

    Week 2 影子交易系统核心组件：模拟智能订单路由。

    路由规则：
        - HIGH → Shadow IOC Executor
        - MEDIUM → Shadow Limit Executor（可能超时）
        - LOW → 跳过

    回退机制：
        - 限价单超时 → 降级为 IOC 重试
    """

    def __init__(
        self,
        fill_simulator: FillSimulator,
        ioc_executor: ShadowIOCExecutor,
        limit_executor: ShadowLimitExecutor,
        enable_fallback: bool = True,
    ):
        """
        初始化影子订单路由器

        Args:
            fill_simulator: 成交模拟器
            ioc_executor: 影子 IOC 执行器
            limit_executor: 影子限价单执行器
            enable_fallback: 是否启用回退机制
        """
        self.fill_simulator = fill_simulator
        self.ioc_executor = ioc_executor
        self.limit_executor = limit_executor
        self.enable_fallback = enable_fallback

        # 统计指标
        self._stats = {
            "total_signals": 0,
            "high_confidence_count": 0,
            "medium_confidence_count": 0,
            "low_confidence_count": 0,
            "ioc_executions": 0,
            "limit_executions": 0,
            "fallback_executions": 0,
            "skipped_signals": 0,
        }

        logger.info(
            "shadow_order_router_initialized",
            enable_fallback=enable_fallback,
        )

    async def route_and_execute(
        self,
        signal_score: SignalScore,
        market_data: MarketData,
        size: Decimal | None = None,
    ) -> ShadowExecutionRecord:
        """
        路由并执行影子订单

        Args:
            signal_score: 信号评分
            market_data: 市场数据
            size: 订单大小

        Returns:
            ShadowExecutionRecord: 影子执行记录
        """
        self._stats["total_signals"] += 1
        confidence = signal_score.confidence

        try:
            # 路由逻辑
            if confidence == ConfidenceLevel.HIGH:
                # 高置信度 → IOC
                self._stats["high_confidence_count"] += 1
                record = await self.ioc_executor.execute(signal_score, market_data, size)

                if not record.skipped:
                    self._stats["ioc_executions"] += 1

                return record

            elif confidence == ConfidenceLevel.MEDIUM:
                # 中置信度 → 限价单（可能回退到 IOC）
                self._stats["medium_confidence_count"] += 1
                record = await self.limit_executor.execute(
                    signal_score, market_data, size
                )

                if not record.skipped:
                    self._stats["limit_executions"] += 1
                    return record

                # 限价单超时，尝试回退
                if self.enable_fallback:
                    logger.info(
                        "shadow_fallback_to_ioc",
                        symbol=market_data.symbol,
                        signal_value=signal_score.value,
                    )

                    # 提升置信度为 HIGH
                    fallback_signal = SignalScore(
                        value=signal_score.value,
                        confidence=ConfidenceLevel.HIGH,
                        individual_scores=signal_score.individual_scores,
                        timestamp=signal_score.timestamp,
                    )

                    fallback_record = await self.ioc_executor.execute(
                        fallback_signal, market_data, size
                    )

                    if not fallback_record.skipped:
                        self._stats["fallback_executions"] += 1

                    return fallback_record

                return record

            else:
                # 低置信度 → 跳过
                self._stats["low_confidence_count"] += 1
                self._stats["skipped_signals"] += 1

                # 创建跳过记录
                signal_timestamp = signal_score.timestamp
                decision_timestamp = int(time.time() * 1000)
                execution_timestamp = decision_timestamp

                order = Order(
                    id="skipped_low_confidence",
                    symbol=market_data.symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.IOC,
                    price=Decimal("0"),
                    size=Decimal("0"),
                    filled_size=Decimal("0"),
                    status=OrderStatus.REJECTED,
                    created_at=decision_timestamp,
                    error_message="low_confidence",
                )

                return ShadowExecutionRecord(
                    order=order,
                    fill_result=None,
                    execution_result=None,
                    signal_timestamp=signal_timestamp,
                    decision_timestamp=decision_timestamp,
                    execution_timestamp=execution_timestamp,
                    signal_latency_ms=float(decision_timestamp - signal_timestamp),
                    decision_latency_ms=0.0,
                    total_latency_ms=float(execution_timestamp - signal_timestamp),
                    skipped=True,
                    skip_reason="low_confidence",
                )

        except Exception as e:
            logger.error(
                "shadow_routing_error",
                symbol=market_data.symbol,
                error=str(e),
                exc_info=True,
            )

            # 返回错误记录
            signal_timestamp = signal_score.timestamp
            decision_timestamp = int(time.time() * 1000)

            order = Order(
                id="routing_error",
                symbol=market_data.symbol,
                side=OrderSide.BUY,
                order_type=OrderType.IOC,
                price=Decimal("0"),
                size=Decimal("0"),
                filled_size=Decimal("0"),
                status=OrderStatus.REJECTED,
                created_at=decision_timestamp,
                error_message=str(e),
            )

            return ShadowExecutionRecord(
                order=order,
                fill_result=None,
                execution_result=None,
                signal_timestamp=signal_timestamp,
                decision_timestamp=decision_timestamp,
                execution_timestamp=decision_timestamp,
                signal_latency_ms=float(decision_timestamp - signal_timestamp),
                decision_latency_ms=0.0,
                total_latency_ms=float(decision_timestamp - signal_timestamp),
                skipped=True,
                skip_reason=f"error: {str(e)}",
            )

    def get_statistics(self) -> dict:
        """获取路由统计数据"""
        total = self._stats["total_signals"]

        if total == 0:
            return self._stats.copy()

        return {
            **self._stats,
            "ioc_execution_rate": (
                self._stats["ioc_executions"] / total * 100 if total > 0 else 0
            ),
            "limit_execution_rate": (
                self._stats["limit_executions"] / total * 100 if total > 0 else 0
            ),
            "fallback_rate": (
                self._stats["fallback_executions"] / total * 100 if total > 0 else 0
            ),
        }
