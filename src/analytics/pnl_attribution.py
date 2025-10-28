"""PnL 归因分析器

将交易盈亏分解为：Alpha + Fee + Slippage + Impact + Rebate
"""

from collections import deque
from dataclasses import dataclass
from decimal import Decimal

import structlog

from src.core.constants import HYPERLIQUID_TAKER_FEE_RATE
from src.core.types import Order, OrderSide

logger = structlog.get_logger()


@dataclass
class TradeAttribution:
    """交易归因数据"""

    trade_id: str
    symbol: str
    alpha: Decimal  # 信号预测价值
    fee: Decimal  # 交易手续费（负数）
    slippage: Decimal  # 滑点成本（负数）
    impact: Decimal  # 市场冲击（负数）
    rebate: Decimal  # Maker 返佣（正数，Week 1 为 0）
    total_pnl: Decimal  # 总盈亏
    timestamp: int

    @property
    def alpha_percentage(self) -> float:
        """Alpha占总PnL的百分比"""
        if self.total_pnl == 0:
            return 0.0
        return float(self.alpha / self.total_pnl * 100)


class PnLAttribution:
    """PnL 归因分析器

    职责：
        1. 分解每笔交易的盈亏来源
        2. 聚合归因统计
        3. 健康检查（Alpha ≥ 70%）
        4. 生成归因报告
    """

    def __init__(
        self,
        fee_rate: float = 0.00045,  # 0.045% Taker 手续费（4.5 bps）
        alpha_threshold: float = 0.70,  # Alpha 占比阈值（70%）
        max_history: int = 10000,
    ):
        """
        初始化 PnL 归因分析器

        Args:
            fee_rate: 手续费率（默认 0.045% Taker，4.5 bps）
            alpha_threshold: Alpha 占比健康阈值（默认 70%）
            max_history: 最大历史记录数
        """
        self.fee_rate = Decimal(str(fee_rate)) if fee_rate != 0.00045 else HYPERLIQUID_TAKER_FEE_RATE
        self.alpha_threshold = alpha_threshold
        self.max_history = max_history

        # 归因历史
        self._attribution_history: deque = deque(maxlen=max_history)

        # 累计统计
        self._cumulative_alpha = Decimal("0")
        self._cumulative_fee = Decimal("0")
        self._cumulative_slippage = Decimal("0")
        self._cumulative_impact = Decimal("0")
        self._cumulative_rebate = Decimal("0")
        self._cumulative_total = Decimal("0")

        logger.info(
            "pnl_attribution_initialized",
            fee_rate=float(self.fee_rate),
            alpha_threshold=alpha_threshold,
            max_history=max_history,
        )

    def attribute_trade(
        self,
        order: Order,
        signal_value: float,
        reference_price: Decimal,
        actual_fill_price: Decimal,
        best_price: Decimal,
    ) -> TradeAttribution:
        """
        归因单笔交易

        Args:
            order: 订单对象
            signal_value: 信号值（-1 到 1）
            reference_price: 参考价格（信号时刻的中间价）
            actual_fill_price: 实际成交价
            best_price: 最优价格（下单时的最优价）

        Returns:
            TradeAttribution: 归因结果
        """
        try:
            # 1. 计算 Fee（手续费，负数表示成本）
            trade_value = order.size * actual_fill_price
            fee = -trade_value * self.fee_rate

            # 2. 计算 Slippage（滑点，负数表示成本）
            # Slippage = (ExecutionPrice - ReferencePrice) * Size
            # 买入时价格越高滑点越大（负数），卖出时价格越低滑点越大
            if order.side == OrderSide.BUY:
                slippage = -(actual_fill_price - reference_price) * order.size
            else:
                slippage = -(reference_price - actual_fill_price) * order.size

            # 3. 计算 Impact（市场冲击，负数表示成本）
            # Impact = (AvgFillPrice - BestPrice) * Size
            if order.side == OrderSide.BUY:
                impact = -(actual_fill_price - best_price) * order.size
            else:
                impact = -(best_price - actual_fill_price) * order.size

            # 4. Rebate（返佣，Week 1 为 0）
            rebate = Decimal("0")

            # 5. 计算 Alpha（方向性收益）
            # 基于信号值估算理论收益
            # Alpha 反映信号预测的准确性和盈利能力
            volatility = reference_price * Decimal("0.01")  # 假设 1% 波动率
            alpha = Decimal(str(signal_value)) * volatility * order.size

            # 6. 计算 Total PnL
            # Total PnL = Alpha + Fee + Slippage + Impact + Rebate
            total_pnl = alpha + fee + slippage + impact + rebate

            # 创建归因对象
            attribution = TradeAttribution(
                trade_id=order.id,
                symbol=order.symbol,
                alpha=alpha,
                fee=fee,
                slippage=slippage,
                impact=impact,
                rebate=rebate,
                total_pnl=total_pnl,
                timestamp=order.created_at,
            )

            # 记录归因
            self._record_attribution(attribution)

            logger.info(
                "trade_attributed",
                trade_id=order.id,
                symbol=order.symbol,
                alpha=float(alpha),
                fee=float(fee),
                slippage=float(slippage),
                impact=float(impact),
                total_pnl=float(total_pnl),
                alpha_pct=attribution.alpha_percentage,
            )

            return attribution

        except Exception as e:
            logger.error(
                "attribution_error",
                order_id=order.id,
                error=str(e),
                exc_info=True,
            )
            raise

    def _record_attribution(self, attribution: TradeAttribution) -> None:
        """
        记录归因结果

        Args:
            attribution: 归因对象
        """
        # 添加到历史
        self._attribution_history.append(attribution)

        # 更新累计统计
        self._cumulative_alpha += attribution.alpha
        self._cumulative_fee += attribution.fee
        self._cumulative_slippage += attribution.slippage
        self._cumulative_impact += attribution.impact
        self._cumulative_rebate += attribution.rebate
        self._cumulative_total += attribution.total_pnl

    def get_cumulative_attribution(self) -> dict[str, Decimal]:
        """
        获取累计归因统计

        Returns:
            Dict[str, Decimal]: 累计归因
        """
        return {
            "alpha": self._cumulative_alpha,
            "fee": self._cumulative_fee,
            "slippage": self._cumulative_slippage,
            "impact": self._cumulative_impact,
            "rebate": self._cumulative_rebate,
            "total": self._cumulative_total,
        }

    def get_attribution_percentages(self) -> dict[str, float]:
        """
        获取归因百分比

        Returns:
            Dict[str, float]: 各项占比（%）

        注意：
            - 盈利时：Alpha > 0, 成本 < 0，各项占比符合直觉
            - 亏损时：使用绝对值计算占比，确保语义清晰
            - 持平时：所有占比为 0
        """
        if self._cumulative_total == 0:
            return {
                "alpha": 0.0,
                "fee": 0.0,
                "slippage": 0.0,
                "impact": 0.0,
                "rebate": 0.0,
            }

        # 使用绝对值计算占比，确保语义清晰
        base = abs(self._cumulative_total)

        return {
            "alpha": float(self._cumulative_alpha / base * 100),
            "fee": float(self._cumulative_fee / base * 100),
            "slippage": float(self._cumulative_slippage / base * 100),
            "impact": float(self._cumulative_impact / base * 100),
            "rebate": float(self._cumulative_rebate / base * 100),
        }

    def check_alpha_health(self) -> tuple[bool, str]:
        """
        检查 Alpha 健康度

        Returns:
            tuple[bool, str]: (是否健康, 诊断信息)

        逻辑：
            - Alpha 占比 >= 70% 视为健康
            - 使用绝对值计算占比，避免负数 PnL 的语义混淆
        """
        if self._cumulative_total == 0:
            return True, "No trades yet, health check skipped"

        # 使用绝对值计算 Alpha 占比
        base = abs(self._cumulative_total)
        alpha_pct = float(self._cumulative_alpha / base)

        is_healthy = alpha_pct >= self.alpha_threshold

        if is_healthy:
            message = (
                f"Alpha health PASS: {alpha_pct*100:.1f}% "
                f">= {self.alpha_threshold*100:.1f}%"
            )
            logger.info("alpha_health_check_passed", alpha_pct=alpha_pct)
        else:
            message = (
                f"Alpha health FAIL: {alpha_pct*100:.1f}% "
                f"< {self.alpha_threshold*100:.1f}%"
            )
            logger.warning("alpha_health_check_failed", alpha_pct=alpha_pct)

        return is_healthy, message

    def get_attribution_report(self) -> dict:
        """
        生成归因报告

        Returns:
            dict: 归因报告
        """
        cumulative = self.get_cumulative_attribution()
        percentages = self.get_attribution_percentages()
        is_healthy, health_message = self.check_alpha_health()

        return {
            "cumulative": {
                "alpha": float(cumulative["alpha"]),
                "fee": float(cumulative["fee"]),
                "slippage": float(cumulative["slippage"]),
                "impact": float(cumulative["impact"]),
                "rebate": float(cumulative["rebate"]),
                "total": float(cumulative["total"]),
            },
            "percentages": percentages,
            "health_check": {
                "is_healthy": is_healthy,
                "message": health_message,
                "alpha_threshold": self.alpha_threshold * 100,
            },
            "trade_count": len(self._attribution_history),
        }

    def get_recent_attributions(self, n: int = 10) -> list[TradeAttribution]:
        """
        获取最近 N 笔归因记录

        Args:
            n: 记录数量

        Returns:
            List[TradeAttribution]: 归因列表（最新在前）
        """
        attributions = list(self._attribution_history)
        attributions.reverse()
        return attributions[:n]

    def __repr__(self) -> str:
        percentages = self.get_attribution_percentages()
        return (
            f"PnLAttribution(trades={len(self._attribution_history)}, "
            f"alpha={percentages['alpha']:.1f}%, "
            f"total_pnl={float(self._cumulative_total):.2f})"
        )
