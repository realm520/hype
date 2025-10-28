"""订单路由器

Week 2 智能订单路由系统：根据置信度选择最优执行策略。
"""

import time
from decimal import Decimal

import structlog

from src.core.logging import get_audit_logger
from src.core.types import ConfidenceLevel, MarketData, Order, SignalScore
from src.execution.ioc_executor import IOCExecutor
from src.execution.limit_executor import LimitExecutor
from src.hyperliquid.api_client import HyperliquidAPIClient

logger = structlog.get_logger()
audit_logger = get_audit_logger()


class OrderRouter:
    """订单路由器

    Week 2 核心组件：根据信号置信度智能选择执行策略。

    路由规则：
        - HIGH (|signal| > theta_1) → IOC Executor（确定性成交）
        - MEDIUM (theta_2 < |signal| ≤ theta_1) → Limit Executor（降低成本）
        - LOW (|signal| ≤ theta_2) → 跳过（避免噪音交易）

    回退机制：
        - 限价单超时未成交 → 自动降级为 IOC 重试
        - 提高整体成交率，避免错失机会

    成本优化目标：
        - Week 1: 100% Taker (费率 4.5 bps)
        - Week 2: 30% Taker + 70% Maker (预期费率 2.4 bps)
        - 计算：0.30 × 4.5 + 0.70 × 1.5 = 1.35 + 1.05 = 2.4 bps
        - 成本降低：2.1 bps (47% 降低)

    费率说明：
        - Taker (IOC)：+0.045% (4.5 bps)
        - Maker (限价单)：+0.015% (1.5 bps，不是 rebate)
        - 节省：3 bps/单
    """

    def __init__(
        self,
        api_client: HyperliquidAPIClient,
        ioc_executor: IOCExecutor,
        limit_executor: LimitExecutor,
        enable_fallback: bool = True,
    ):
        """
        初始化订单路由器

        Args:
            api_client: Hyperliquid API 客户端
            ioc_executor: IOC 订单执行器
            limit_executor: 限价单执行器
            enable_fallback: 是否启用限价单超时后的 IOC 回退
        """
        self.api_client = api_client
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
            "order_router_initialized",
            enable_fallback=enable_fallback,
            ioc_executor=str(ioc_executor),
            limit_executor=str(limit_executor),
        )

    async def route_and_execute(
        self,
        signal_score: SignalScore,
        market_data: MarketData,
        size: Decimal | None = None,
    ) -> Order | None:
        """
        路由并执行订单

        根据信号置信度选择执行策略，并跟踪执行结果。

        Args:
            signal_score: 信号评分
            market_data: 市场数据
            size: 订单大小（如果为 None，使用执行器默认大小）

        Returns:
            Optional[Order]: 执行的订单，如果跳过则返回 None
        """
        start_time = time.time()
        self._stats["total_signals"] += 1

        try:
            # 根据置信度路由
            confidence = signal_score.confidence

            # 记录路由决策
            logger.info(
                "routing_order",
                symbol=market_data.symbol,
                signal_value=signal_score.value,
                confidence=confidence.name,
                abs_signal=abs(signal_score.value),
            )

            # 路由逻辑
            if confidence == ConfidenceLevel.HIGH:
                # 高置信度 → IOC
                self._stats["high_confidence_count"] += 1
                order = await self._execute_ioc(signal_score, market_data, size)

                if order is not None:
                    self._stats["ioc_executions"] += 1

            elif confidence == ConfidenceLevel.MEDIUM:
                # 中置信度 → 限价单（可能回退到 IOC）
                self._stats["medium_confidence_count"] += 1
                order = await self._execute_limit_with_fallback(
                    signal_score, market_data, size
                )

            else:
                # 低置信度 → 跳过
                self._stats["low_confidence_count"] += 1
                self._stats["skipped_signals"] += 1

                logger.info(
                    "signal_skipped_low_confidence",
                    symbol=market_data.symbol,
                    signal_value=signal_score.value,
                    confidence=confidence.name,
                )
                return None

            # 计算路由延迟
            routing_latency_ms = (time.time() - start_time) * 1000

            if order is not None:
                # 记录路由成功
                logger.info(
                    "order_routed_successfully",
                    symbol=market_data.symbol,
                    order_id=order.id,
                    confidence=confidence.name,
                    order_type=order.order_type.name,
                    routing_latency_ms=routing_latency_ms,
                )

                # 记录审计日志
                audit_logger.info(
                    "order_routed",
                    order_id=order.id,
                    symbol=market_data.symbol,
                    signal_value=signal_score.value,
                    confidence=confidence.name,
                    selected_executor=order.order_type.name,
                    routing_latency_ms=routing_latency_ms,
                )
            else:
                # 记录路由失败（超时或跳过）
                logger.info(
                    "order_routing_no_execution",
                    symbol=market_data.symbol,
                    confidence=confidence.name,
                    routing_latency_ms=routing_latency_ms,
                )

            return order

        except Exception as e:
            logger.error(
                "order_routing_error",
                symbol=market_data.symbol,
                signal_value=signal_score.value,
                confidence=signal_score.confidence.name,
                error=str(e),
                exc_info=True,
            )
            return None

    async def _execute_ioc(
        self,
        signal_score: SignalScore,
        market_data: MarketData,
        size: Decimal | None,
    ) -> Order | None:
        """
        执行 IOC 订单

        Args:
            signal_score: 信号评分
            market_data: 市场数据
            size: 订单大小

        Returns:
            Optional[Order]: 执行的订单
        """
        logger.info(
            "routing_to_ioc_executor",
            symbol=market_data.symbol,
            signal_value=signal_score.value,
        )

        return await self.ioc_executor.execute(signal_score, market_data, size)

    async def _execute_limit_with_fallback(
        self,
        signal_score: SignalScore,
        market_data: MarketData,
        size: Decimal | None,
    ) -> Order | None:
        """
        执行限价单（带 IOC 回退）

        策略：
            1. 先尝试限价单（Post-only）
            2. 如果超时未成交，回退到 IOC

        Args:
            signal_score: 信号评分
            market_data: 市场数据
            size: 订单大小

        Returns:
            Optional[Order]: 执行的订单
        """
        logger.info(
            "routing_to_limit_executor",
            symbol=market_data.symbol,
            signal_value=signal_score.value,
            enable_fallback=self.enable_fallback,
        )

        # 先尝试限价单
        order = await self.limit_executor.execute(signal_score, market_data, size)

        if order is not None:
            # 限价单成交成功
            self._stats["limit_executions"] += 1
            logger.info(
                "limit_order_filled_successfully",
                symbol=market_data.symbol,
                order_id=order.id,
            )
            return order

        # 限价单超时未成交
        logger.warning(
            "limit_order_timeout",
            symbol=market_data.symbol,
            signal_value=signal_score.value,
            fallback_enabled=self.enable_fallback,
        )

        # 如果启用回退，尝试 IOC
        if self.enable_fallback:
            logger.info(
                "falling_back_to_ioc",
                symbol=market_data.symbol,
                signal_value=signal_score.value,
            )

            # 暂时提升置信度为 HIGH，让 IOC 执行器接受
            fallback_signal = SignalScore(
                value=signal_score.value,
                confidence=ConfidenceLevel.HIGH,
                individual_scores=signal_score.individual_scores,
                timestamp=signal_score.timestamp,
            )

            fallback_order = await self.ioc_executor.execute(
                fallback_signal, market_data, size
            )

            if fallback_order is not None:
                self._stats["fallback_executions"] += 1
                logger.info(
                    "fallback_to_ioc_successful",
                    symbol=market_data.symbol,
                    order_id=fallback_order.id,
                )

                # 记录审计日志（回退执行）
                audit_logger.warning(
                    "limit_order_fallback_to_ioc",
                    order_id=fallback_order.id,
                    symbol=market_data.symbol,
                    original_confidence="MEDIUM",
                    fallback_confidence="HIGH",
                    signal_value=signal_score.value,
                )

            return fallback_order

        return None

    def get_statistics(self) -> dict:
        """
        获取路由统计数据

        Returns:
            dict: 路由统计指标
        """
        total = self._stats["total_signals"]

        if total == 0:
            return self._stats.copy()

        return {
            **self._stats,
            "high_confidence_pct": (
                self._stats["high_confidence_count"] / total * 100
            ),
            "medium_confidence_pct": (
                self._stats["medium_confidence_count"] / total * 100
            ),
            "low_confidence_pct": self._stats["low_confidence_count"] / total * 100,
            "ioc_execution_rate": (
                self._stats["ioc_executions"] / total * 100 if total > 0 else 0
            ),
            "limit_execution_rate": (
                self._stats["limit_executions"] / total * 100 if total > 0 else 0
            ),
            "fallback_rate": (
                self._stats["fallback_executions"] / total * 100 if total > 0 else 0
            ),
            "skip_rate": self._stats["skipped_signals"] / total * 100,
        }

    def reset_statistics(self) -> None:
        """重置统计数据"""
        for key in self._stats:
            self._stats[key] = 0

        logger.info("order_router_statistics_reset")

    def __repr__(self) -> str:
        stats = self.get_statistics()
        return (
            f"OrderRouter("
            f"total_signals={stats.get('total_signals', 0)}, "
            f"ioc_rate={stats.get('ioc_execution_rate', 0):.1f}%, "
            f"limit_rate={stats.get('limit_execution_rate', 0):.1f}%, "
            f"fallback_rate={stats.get('fallback_rate', 0):.1f}%)"
        )
