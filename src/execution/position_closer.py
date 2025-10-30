"""平仓协调器

Week 2 Phase 2 核心模块：集成 TP/SL + 超时平仓触发器。
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
from src.execution.hybrid_executor import HybridExecutor
from src.execution.ioc_executor import IOCExecutor
from src.risk.position_manager import PositionManager
from src.risk.tp_sl_manager import TPSLManager

logger = structlog.get_logger()
audit_logger = get_audit_logger()


class PositionCloser:
    """平仓协调器

    Week 2 Phase 2 核心功能：
        1. TP/SL 触发检测（使用 TPSLManager）
        2. 超时平仓触发（持仓存活 > max_age_seconds）
        3. 平仓信号生成（反向信号 + HIGH 置信度）
        4. 平仓执行（调用 IOC Executor，确保成交）

    设计原则：
        - 平仓信号强制 HIGH 置信度（确保 IOC 立即成交）
        - 平仓信号不经过去重器（直接执行，避免延迟）
        - 记录详细审计日志（便于监控和调试）

    注意：
        - Week 2 统一使用 IOC 平仓（不用 Maker，避免挂单风险）
        - 平仓失败会记录 ERROR 级别日志，但不阻塞主流程
    """

    def __init__(
        self,
        tp_sl_manager: TPSLManager,
        position_manager: PositionManager,
        ioc_executor: IOCExecutor,
        max_position_age_seconds: float = 1800.0,  # 默认 30 分钟
    ):
        """
        初始化平仓协调器

        Args:
            tp_sl_manager: TP/SL 管理器
            position_manager: 持仓管理器
            ioc_executor: IOC 执行器（平仓使用）
            max_position_age_seconds: 持仓最大存活时间（秒），默认 1800 秒（30 分钟）
        """
        self.tp_sl_manager = tp_sl_manager
        self.position_manager = position_manager
        self.ioc_executor = ioc_executor
        self.max_position_age_seconds = max_position_age_seconds

        # 统计指标
        self._stats = {
            "total_checks": 0,
            "tp_triggers": 0,
            "sl_triggers": 0,
            "timeout_triggers": 0,
            "close_success": 0,
            "close_failed": 0,
        }

        logger.info(
            "position_closer_initialized",
            max_position_age_seconds=max_position_age_seconds,
        )

    async def check_and_close_positions(
        self,
        market_data: dict[str, MarketData],
    ) -> list[Order]:
        """
        检查所有持仓，如需平仓则执行

        Args:
            market_data: symbol -> MarketData 映射

        Returns:
            list[Order]: 已执行的平仓订单列表（不包括失败的）
        """
        self._stats["total_checks"] += 1
        closed_orders: list[Order] = []

        for symbol, md in market_data.items():
            position = self.position_manager.get_position(symbol)

            # 跳过空仓或无持仓
            if not position or position.size == 0:
                continue

            # 1. 检查 TP/SL 触发
            should_close, reason = self.tp_sl_manager.check_position_risk(
                position, md.mid_price
            )

            # 2. 如果 TP/SL 未触发，检查超时平仓
            if not should_close:
                is_stale = self.position_manager.is_position_stale(
                    symbol, self.max_position_age_seconds
                )
                if is_stale:
                    should_close = True
                    reason = "max_age_timeout"
                    self._stats["timeout_triggers"] += 1

                    # 获取持仓年龄用于日志
                    age = self.position_manager.get_position_age_seconds(symbol)
                    logger.warning(
                        "position_timeout_triggered",
                        symbol=symbol,
                        position_age_seconds=age,
                        max_age_seconds=self.max_position_age_seconds,
                    )
            else:
                # 统计 TP/SL 触发
                if reason == "take_profit":
                    self._stats["tp_triggers"] += 1
                elif reason == "stop_loss":
                    self._stats["sl_triggers"] += 1

            # 3. 执行平仓（如果触发）
            if should_close:
                order = await self._execute_close(position, md, reason)
                if order:
                    closed_orders.append(order)
                    self._stats["close_success"] += 1
                else:
                    self._stats["close_failed"] += 1

        return closed_orders

    async def _execute_close(
        self,
        position,
        market_data: MarketData,
        reason: str,
    ) -> Order | None:
        """
        执行平仓（生成反向信号 + 调用 IOC 执行器）

        Args:
            position: 当前持仓
            market_data: 市场数据
            reason: 平仓原因（"take_profit" / "stop_loss" / "max_age_timeout"）

        Returns:
            Optional[Order]: 成功则返回平仓订单，失败则返回 None
        """
        symbol = position.symbol

        # 生成反向平仓信号
        close_signal = self._generate_close_signal(position, reason)

        # 计算平仓尺寸（全部平仓）
        close_size = abs(position.size)

        # 调用 IOC 执行器执行平仓（Week 2 统一使用 IOC，确保成交）
        try:
            order = await self.ioc_executor.execute(
                signal_score=close_signal,
                market_data=market_data,
                size=close_size,  # 指定平仓全部尺寸
            )

            if order:
                # 记录审计日志
                audit_logger.info(
                    "position_closed",
                    symbol=symbol,
                    reason=reason,
                    close_type="IOC",
                    order_id=order.id,
                    close_size=float(close_size),
                    entry_price=float(position.entry_price) if position.entry_price else None,
                    close_price=float(order.price) if order.price else float(market_data.mid_price),
                    pnl=float(position.unrealized_pnl),
                )

                logger.info(
                    "position_close_executed",
                    symbol=symbol,
                    reason=reason,
                    order_id=order.id,
                    close_size=float(close_size),
                )
            else:
                logger.error(
                    "position_close_failed",
                    symbol=symbol,
                    reason=reason,
                    close_size=float(close_size),
                    error="IOC executor returned None",
                )

            return order

        except Exception as e:
            logger.error(
                "position_close_exception",
                symbol=symbol,
                reason=reason,
                error=str(e),
                exc_info=True,
            )
            return None

    def _generate_close_signal(
        self,
        position,
        reason: str,
    ) -> SignalScore:
        """
        生成平仓信号（反向信号 + HIGH 置信度）

        Args:
            position: 当前持仓
            reason: 平仓原因

        Returns:
            SignalScore: 平仓信号（反向 + HIGH 置信度确保 IOC 执行）
        """
        # 反向信号：多头 → -1.0（卖出），空头 → +1.0（买入）
        signal_value = -1.0 if position.size > 0 else 1.0

        return SignalScore(
            value=signal_value,
            confidence=ConfidenceLevel.HIGH,  # 强制 HIGH，确保 IOC 立即执行
            individual_scores=[signal_value],
            timestamp=int(time.time() * 1000),
        )

    def get_stats(self) -> dict:
        """
        获取平仓统计信息

        Returns:
            dict: 统计指标
        """
        return self._stats.copy()

    def reset_stats(self) -> None:
        """重置统计指标"""
        for key in self._stats:
            self._stats[key] = 0

        logger.info("position_closer_stats_reset")
