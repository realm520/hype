"""硬限制风控

Week 1 核心风控：不可违背的硬性限制。
"""

from datetime import datetime
from decimal import Decimal

import structlog

from src.core.logging import get_audit_logger
from src.core.types import MarketData, Order, OrderSide
from src.execution.slippage_estimator import SlippageEstimator

logger = structlog.get_logger()
audit_logger = get_audit_logger()


class HardLimits:
    """硬限制风控

    Week 1 核心限制：
        1. 单笔最大亏损：0.8% 初始净值
        2. 日最大回撤：5% 初始净值（基准可配置）
        3. 最大持仓：10000 USD
        4. 违规立即停止交易

    回撤计算说明：
        - 默认使用 initial_nav 作为基准（更保守，符合 Week 1 要求）
        - 日内峰值 (daily_peak_nav) 用于追踪回撤幅度
        - 计算公式：drawdown = daily_peak_nav - current_nav
        - 触发条件：drawdown >= initial_nav * max_daily_drawdown_pct
    """

    def __init__(
        self,
        initial_nav: Decimal,
        max_single_loss_pct: float = 0.008,
        max_daily_drawdown_pct: float = 0.05,
        max_position_size_usd: Decimal = Decimal("10000"),
        slippage_estimator: SlippageEstimator | None = None,
    ):
        """
        初始化硬限制风控

        Args:
            initial_nav: 初始净值（USD）
            max_single_loss_pct: 单笔最大亏损比例（默认 0.8%，相对初始净值）
            max_daily_drawdown_pct: 日最大回撤比例（默认 5%，相对初始净值）
            max_position_size_usd: 最大持仓（USD，默认 10000）
            slippage_estimator: 滑点估算器（可选，用于动态估算订单风险）

        注意：
            - 所有百分比参数为小数形式（0.008 表示 0.8%）
            - 回撤基准为初始净值，不随日内盈亏变化
            - 如果提供 slippage_estimator，将使用动态滑点估算提升风控精度
        """
        self.initial_nav = initial_nav
        self.max_single_loss_pct = max_single_loss_pct
        self.max_daily_drawdown_pct = max_daily_drawdown_pct
        self.max_position_size_usd = max_position_size_usd
        self.slippage_estimator = slippage_estimator

        # 当前净值
        self._current_nav = initial_nav

        # 日内统计
        self._daily_pnl = Decimal("0")
        self._daily_peak_nav = initial_nav
        self._trading_date = datetime.now().date()

        # 违规标志
        self._is_breached = False
        self._breach_reason: str | None = None

        logger.info(
            "hard_limits_initialized",
            initial_nav=float(initial_nav),
            max_single_loss_pct=max_single_loss_pct,
            max_daily_drawdown_pct=max_daily_drawdown_pct,
            max_position_size_usd=float(max_position_size_usd),
        )

    def check_order(
        self,
        order: Order,
        current_price: Decimal,
        current_position_size: Decimal = Decimal("0"),  # 修改：币本位数量
        market_data: MarketData | None = None,
    ) -> tuple[bool, str | None]:
        """
        检查订单是否违反硬限制

        Args:
            order: 待检查订单
            current_price: 当前价格
            current_position_size: 当前持仓数量（币本位，带符号）
            market_data: 市场数据（可选，用于动态滑点估算）

        Returns:
            tuple[bool, Optional[str]]: (是否允许, 拒绝原因)
        """
        # 如果已经违规，拒绝所有订单
        if self._is_breached:
            return False, f"System breached: {self._breach_reason}"

        # 检查日期切换
        self._check_new_day()

        # 1. 检查单笔最大亏损
        single_loss_check = self._check_single_loss(order, current_price, market_data)
        if not single_loss_check[0]:
            return single_loss_check

        # 2. 检查日最大回撤
        daily_drawdown_check = self._check_daily_drawdown(order, current_price)
        if not daily_drawdown_check[0]:
            return daily_drawdown_check

        # 3. 检查最大持仓
        position_check = self._check_position_size(
            order, current_price, current_position_size
        )
        if not position_check[0]:
            return position_check

        # 所有检查通过
        return True, None

    def _check_single_loss(
        self, order: Order, current_price: Decimal, market_data: MarketData | None = None
    ) -> tuple[bool, str | None]:
        """
        检查单笔最大亏损限制

        Args:
            order: 订单
            current_price: 当前价格
            market_data: 市场数据（可选，用于动态滑点估算）

        Returns:
            tuple[bool, Optional[str]]: (是否允许, 拒绝原因)

        说明：
            - 最大亏损基准：初始净值（不是当前净值）
            - 潜在亏损估算：订单价值 * 滑点系数
            - 如果提供 slippage_estimator 和 market_data，使用动态估算
            - 否则使用保守固定值（1% 滑点）
        """
        # 计算订单价值
        order_value = order.size * current_price

        # 计算最大允许亏损（基于初始净值）
        max_loss = self.initial_nav * Decimal(str(self.max_single_loss_pct))

        # 估算潜在亏损
        if self.slippage_estimator and market_data:
            # 使用动态滑点估算
            try:
                slippage_result = self.slippage_estimator.estimate(
                    market_data=market_data,
                    side=order.side,
                    size=order.size,
                )
                # 滑点以基点表示，转换为比例（bps / 10000）
                slippage_pct = Decimal(str(slippage_result["slippage_bps"])) / Decimal("10000")
                potential_loss = order_value * slippage_pct

                logger.debug(
                    "dynamic_slippage_estimate",
                    order_id=order.id,
                    slippage_bps=slippage_result["slippage_bps"],
                    slippage_pct=float(slippage_pct),
                    potential_loss=float(potential_loss),
                )
            except Exception as e:
                # 降级到固定滑点
                logger.warning(
                    "slippage_estimator_error",
                    error=str(e),
                    fallback_to_fixed="1%",
                )
                potential_loss = order_value * Decimal("0.01")
        else:
            # 使用固定滑点（保守估计 1%）
            potential_loss = order_value * Decimal("0.01")

        if potential_loss > max_loss:
            reason = (
                f"Single loss limit exceeded: potential_loss={float(potential_loss):.2f} "
                f"> max_loss={float(max_loss):.2f} "
                f"(initial_NAV={float(self.initial_nav):.2f}, "
                f"max_pct={self.max_single_loss_pct*100:.2f}%)"
            )
            logger.warning("single_loss_limit_breach", reason=reason)
            self._mark_breach(reason)
            return False, reason

        return True, None

    def _check_daily_drawdown(
        self, order: Order, current_price: Decimal
    ) -> tuple[bool, str | None]:
        """
        检查日最大回撤限制

        Args:
            order: 订单
            current_price: 当前价格

        Returns:
            tuple[bool, Optional[str]]: (是否允许, 拒绝原因)

        说明：
            - 回撤计算：daily_peak_nav - current_nav
            - 回撤阈值：initial_nav * max_daily_drawdown_pct
            - 基准选择：使用 initial_nav 更保守，确保即使日内盈利也不放松风控
        """
        # 计算当前回撤（从日内峰值开始）
        current_drawdown = self._daily_peak_nav - self._current_nav

        # 计算最大允许回撤（基于初始净值）
        max_drawdown = self.initial_nav * Decimal(str(self.max_daily_drawdown_pct))

        if current_drawdown >= max_drawdown:
            reason = (
                f"Daily drawdown limit exceeded: drawdown={float(current_drawdown):.2f} "
                f">= max_drawdown={float(max_drawdown):.2f} "
                f"(peak_nav={float(self._daily_peak_nav):.2f}, "
                f"current_nav={float(self._current_nav):.2f}, "
                f"initial_nav={float(self.initial_nav):.2f}, "
                f"max_pct={self.max_daily_drawdown_pct*100:.2f}%)"
            )
            logger.warning("daily_drawdown_limit_breach", reason=reason)
            self._mark_breach(reason)
            return False, reason

        return True, None

    def _check_position_size(
        self,
        order: Order,
        current_price: Decimal,
        current_position_size: Decimal,  # 修改：现在是持仓数量（币本位），不是价值
    ) -> tuple[bool, str | None]:
        """
        检查最大持仓限制

        Args:
            order: 订单
            current_price: 当前价格
            current_position_size: 当前持仓数量（币本位，带符号：正数多头，负数空头）

        Returns:
            tuple[bool, Optional[str]]: (是否允许, 拒绝原因)
        """
        # 计算订单后持仓数量
        if order.side == OrderSide.BUY:
            new_position_size = current_position_size + order.size
        else:
            new_position_size = current_position_size - order.size

        # 计算新持仓价值（USD）
        new_position_value_usd = abs(new_position_size) * current_price
        
        # DEBUG: 添加调试日志
        logger.debug(
            "position_check_calculation",
            symbol=order.symbol,
            current_position_size=float(current_position_size),
            order_size=float(order.size),
            order_side=order.side.name,
            new_position_size=float(new_position_size),
            current_price=float(current_price),
            new_position_value_usd=float(new_position_value_usd),
            max_limit=float(self.max_position_size_usd),
        )

        # 检查持仓价值限制
        if new_position_value_usd > self.max_position_size_usd:
            reason = (
                f"Position size limit exceeded: new_position={float(new_position_value_usd):.2f} "
                f"> max_position={float(self.max_position_size_usd):.2f}"
            )
            logger.warning("position_size_limit_breach", reason=reason)
            return False, reason

        return True, None

    def update_pnl(self, pnl: Decimal) -> None:
        """
        更新盈亏，影响净值和回撤统计

        Args:
            pnl: 盈亏金额（USD）
        """
        # 检查日期切换
        self._check_new_day()

        # 更新净值
        self._current_nav += pnl

        # 更新日内统计
        self._daily_pnl += pnl

        # 更新日内峰值
        if self._current_nav > self._daily_peak_nav:
            self._daily_peak_nav = self._current_nav

        logger.debug(
            "pnl_updated",
            pnl=float(pnl),
            current_nav=float(self._current_nav),
            daily_pnl=float(self._daily_pnl),
            daily_peak_nav=float(self._daily_peak_nav),
        )

    def _check_new_day(self) -> None:
        """检查是否需要重置日内统计"""
        today = datetime.now().date()

        if today != self._trading_date:
            logger.info(
                "new_trading_day",
                old_date=str(self._trading_date),
                new_date=str(today),
                daily_pnl=float(self._daily_pnl),
            )

            # 重置日内统计
            self._trading_date = today
            self._daily_pnl = Decimal("0")
            self._daily_peak_nav = self._current_nav

    def _mark_breach(self, reason: str) -> None:
        """
        标记违规

        Args:
            reason: 违规原因
        """
        self._is_breached = True
        self._breach_reason = reason

        logger.error(
            "hard_limit_breached",
            reason=reason,
            current_nav=float(self._current_nav),
            daily_pnl=float(self._daily_pnl),
        )

        # 记录审计日志（关键风控事件）
        audit_logger.critical(
            "hard_limit_breached",
            trigger="risk_control",
            reason=reason,
            current_nav=float(self._current_nav),
            initial_nav=float(self.initial_nav),
            daily_pnl=float(self._daily_pnl),
            daily_peak_nav=float(self._daily_peak_nav),
            max_single_loss_pct=self.max_single_loss_pct,
            max_daily_drawdown_pct=self.max_daily_drawdown_pct,
            action="stop_trading",
        )

    def reset_breach(self) -> None:
        """重置违规标志（谨慎使用）"""
        logger.warning(
            "breach_reset",
            previous_reason=self._breach_reason,
        )
        self._is_breached = False
        self._breach_reason = None

    def get_status(self) -> dict:
        """
        获取风控状态

        Returns:
            dict: 风控状态信息
        """
        current_drawdown = self._daily_peak_nav - self._current_nav
        max_drawdown = self.initial_nav * Decimal(str(self.max_daily_drawdown_pct))

        return {
            "is_breached": self._is_breached,
            "breach_reason": self._breach_reason,
            "current_nav": float(self._current_nav),
            "daily_pnl": float(self._daily_pnl),
            "daily_peak_nav": float(self._daily_peak_nav),
            "current_drawdown": float(current_drawdown),
            "max_drawdown": float(max_drawdown),
            "drawdown_utilization": float(current_drawdown / max_drawdown)
            if max_drawdown > 0
            else 0.0,
        }

    def __repr__(self) -> str:
        return (
            f"HardLimits(nav={float(self._current_nav):.2f}, "
            f"breached={self._is_breached})"
        )
