"""混合执行协调器

Week 1.5 Maker/Taker 混合策略核心执行引擎。
"""

import time
from decimal import Decimal

import structlog

from src.core.logging import get_audit_logger
from src.core.types import (
    ConfidenceLevel,
    MarketData,
    Order,
    SignalScore,
)
from src.execution.ioc_executor import IOCExecutor
from src.execution.shallow_maker_executor import ShallowMakerExecutor

logger = structlog.get_logger()
audit_logger = get_audit_logger()


class HybridExecutor:
    """混合执行协调器（Maker/Taker 智能路由）

    Week 1.5 策略：
        - HIGH 置信度：ShallowMaker（5s 超时）→ IOC 回退
        - MEDIUM 置信度：ShallowMaker（3s 超时）→ 不回退（跳过）
        - LOW 置信度：跳过

    核心优势：
        - Maker 费率：+0.015%（1.5 bps）
        - Taker 费率：+0.045%（4.5 bps）
        - 节省：3 bps 往返成本

    执行流程：
        1. 根据 SignalScore.confidence 路由
        2. HIGH/MEDIUM 优先使用 ShallowMaker
        3. HIGH 超时后回退 IOC，MEDIUM 超时则跳过
        4. 记录审计日志（关键决策点）
    """

    def __init__(
        self,
        shallow_maker_executor: ShallowMakerExecutor,
        ioc_executor: IOCExecutor,
        enable_fallback: bool = True,
        fallback_on_medium: bool = False,
    ):
        """
        初始化混合执行协调器

        Args:
            shallow_maker_executor: 浅被动 Maker 执行器
            ioc_executor: IOC 执行器（回退用）
            enable_fallback: 是否启用 IOC 回退（默认 True）
            fallback_on_medium: MEDIUM 置信度超时后是否回退 IOC（默认 False）
        """
        self.shallow_maker = shallow_maker_executor
        self.ioc_executor = ioc_executor
        self.enable_fallback = enable_fallback
        self.fallback_on_medium = fallback_on_medium

        # 统计指标
        self._stats = {
            "total_signals": 0,
            "high_confidence_count": 0,
            "medium_confidence_count": 0,
            "low_confidence_count": 0,
            "maker_executions": 0,
            "ioc_executions": 0,
            "fallback_executions": 0,
            "skipped_signals": 0,
        }

        logger.info(
            "hybrid_executor_initialized",
            enable_fallback=enable_fallback,
            fallback_on_medium=fallback_on_medium,
        )

    async def execute(
        self,
        signal_score: SignalScore,
        market_data: MarketData,
        size: Decimal | None = None,
    ) -> Order | None:
        """
        根据信号置信度智能执行订单

        Args:
            signal_score: 信号评分（包含 confidence 级别）
            market_data: 市场数据
            size: 订单大小（如果为 None，使用执行器默认值）

        Returns:
            Optional[Order]: 执行的订单，跳过则返回 None
        """
        start_time = time.time()
        self._stats["total_signals"] += 1
        confidence = signal_score.confidence

        try:
            # === 路由决策 ===
            if confidence == ConfidenceLevel.HIGH:
                # HIGH 置信度：ShallowMaker（5s 超时）→ IOC 回退
                self._stats["high_confidence_count"] += 1

                logger.info(
                    "routing_high_confidence",
                    symbol=market_data.symbol,
                    signal_value=signal_score.value,
                    execution_plan="shallow_maker_with_ioc_fallback",
                )

                # 尝试 ShallowMaker
                maker_order = await self.shallow_maker.execute(
                    signal_score, market_data, size
                )

                if maker_order is not None:
                    # Maker 成交成功
                    self._stats["maker_executions"] += 1

                    latency_ms = (time.time() - start_time) * 1000
                    logger.info(
                        "high_confidence_maker_filled",
                        symbol=market_data.symbol,
                        order_id=maker_order.id,
                        latency_ms=latency_ms,
                    )

                    return maker_order

                # Maker 超时，检查是否回退 IOC
                if self.enable_fallback:
                    logger.warning(
                        "high_confidence_maker_timeout_fallback_ioc",
                        symbol=market_data.symbol,
                        signal_value=signal_score.value,
                    )

                    # 审计日志：回退决策
                    audit_logger.warning(
                        "fallback_triggered",
                        symbol=market_data.symbol,
                        confidence=confidence.name,
                        reason="maker_timeout",
                        action="execute_ioc",
                    )

                    # 回退 IOC
                    ioc_order = await self.ioc_executor.execute(
                        signal_score, market_data, size
                    )

                    if ioc_order is not None:
                        self._stats["fallback_executions"] += 1
                        self._stats["ioc_executions"] += 1

                        latency_ms = (time.time() - start_time) * 1000
                        logger.info(
                            "high_confidence_ioc_fallback_filled",
                            symbol=market_data.symbol,
                            order_id=ioc_order.id,
                            latency_ms=latency_ms,
                        )

                        return ioc_order
                    else:
                        # IOC 回退也失败
                        self._stats["skipped_signals"] += 1
                        logger.error(
                            "high_confidence_fallback_failed",
                            symbol=market_data.symbol,
                            signal_value=signal_score.value,
                        )
                        return None
                else:
                    # 未启用回退
                    self._stats["skipped_signals"] += 1
                    logger.warning(
                        "high_confidence_maker_timeout_no_fallback",
                        symbol=market_data.symbol,
                    )
                    return None

            elif confidence == ConfidenceLevel.MEDIUM:
                # MEDIUM 置信度：ShallowMaker（3s 超时）→ 不回退（默认）
                self._stats["medium_confidence_count"] += 1

                logger.info(
                    "routing_medium_confidence",
                    symbol=market_data.symbol,
                    signal_value=signal_score.value,
                    execution_plan="shallow_maker_only",
                    fallback_enabled=self.fallback_on_medium,
                )

                # 尝试 ShallowMaker
                maker_order = await self.shallow_maker.execute(
                    signal_score, market_data, size
                )

                if maker_order is not None:
                    # Maker 成交成功
                    self._stats["maker_executions"] += 1

                    latency_ms = (time.time() - start_time) * 1000
                    logger.info(
                        "medium_confidence_maker_filled",
                        symbol=market_data.symbol,
                        order_id=maker_order.id,
                        latency_ms=latency_ms,
                    )

                    return maker_order

                # Maker 超时
                if self.fallback_on_medium:
                    # 配置允许 MEDIUM 回退 IOC（非默认行为）
                    logger.warning(
                        "medium_confidence_maker_timeout_fallback_ioc",
                        symbol=market_data.symbol,
                        signal_value=signal_score.value,
                    )

                    audit_logger.warning(
                        "fallback_triggered",
                        symbol=market_data.symbol,
                        confidence=confidence.name,
                        reason="maker_timeout",
                        action="execute_ioc",
                    )

                    ioc_order = await self.ioc_executor.execute(
                        signal_score, market_data, size
                    )

                    if ioc_order is not None:
                        self._stats["fallback_executions"] += 1
                        self._stats["ioc_executions"] += 1
                        return ioc_order
                    else:
                        self._stats["skipped_signals"] += 1
                        return None
                else:
                    # MEDIUM 超时直接跳过（Week 1.5 默认策略）
                    self._stats["skipped_signals"] += 1
                    logger.info(
                        "medium_confidence_maker_timeout_skipped",
                        symbol=market_data.symbol,
                        signal_value=signal_score.value,
                    )
                    return None

            else:
                # LOW 置信度：直接跳过
                self._stats["low_confidence_count"] += 1
                self._stats["skipped_signals"] += 1

                logger.info(
                    "routing_low_confidence_skipped",
                    symbol=market_data.symbol,
                    signal_value=signal_score.value,
                    confidence=confidence.name,
                )

                return None

        except Exception as e:
            logger.error(
                "hybrid_executor_error",
                symbol=market_data.symbol,
                confidence=confidence.name,
                error=str(e),
                exc_info=True,
            )

            audit_logger.error(
                "execution_error",
                symbol=market_data.symbol,
                confidence=confidence.name,
                error=str(e),
            )

            self._stats["skipped_signals"] += 1
            return None

    def get_statistics(self) -> dict:
        """
        获取执行统计数据

        Returns:
            dict: 统计信息，包含各置信度执行率
        """
        total = self._stats["total_signals"]

        if total == 0:
            return {**self._stats, "maker_fill_rate": 0.0, "ioc_fill_rate": 0.0}

        return {
            **self._stats,
            "maker_fill_rate": (
                self._stats["maker_executions"] / total * 100 if total > 0 else 0
            ),
            "ioc_fill_rate": (
                self._stats["ioc_executions"] / total * 100 if total > 0 else 0
            ),
            "fallback_rate": (
                self._stats["fallback_executions"] / total * 100 if total > 0 else 0
            ),
            "skip_rate": (
                self._stats["skipped_signals"] / total * 100 if total > 0 else 0
            ),
        }

    def reset_statistics(self):
        """重置统计数据"""
        for key in self._stats:
            self._stats[key] = 0

        logger.info("hybrid_executor_statistics_reset")

    def __repr__(self) -> str:
        return (
            f"HybridExecutor(enable_fallback={self.enable_fallback}, "
            f"fallback_on_medium={self.fallback_on_medium})"
        )
