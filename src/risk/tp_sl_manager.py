"""止盈止损管理器

Week 2 核心模块：固定百分比 TP/SL 风控。
"""

from decimal import Decimal

import structlog

from src.core.logging import get_audit_logger
from src.core.types import OrderSide, Position

logger = structlog.get_logger()
audit_logger = get_audit_logger()


class TPSLManager:
    """止盈止损管理器

    Week 2 固定 TP/SL 策略：
        - Take Profit: 2% (从开仓价格计算)
        - Stop Loss: 1% (从开仓价格计算)

    未来扩展（Week 3）：
        - 动态 TP/SL（基于波动率）
        - 追踪止损
        - 分批止盈
    """

    def __init__(
        self,
        take_profit_pct: float = 0.02,
        stop_loss_pct: float = 0.01,
    ):
        """
        初始化 TP/SL 管理器

        Args:
            take_profit_pct: 止盈百分比（默认 2%，0.02）
            stop_loss_pct: 止损百分比（默认 1%，0.01）

        注意：
            - 百分比为小数形式（0.02 = 2%）
            - 计算基准为开仓价格（entry_price）
            - 多头和空头计算方向不同
        """
        self.take_profit_pct = Decimal(str(take_profit_pct))
        self.stop_loss_pct = Decimal(str(stop_loss_pct))

        logger.info(
            "tp_sl_manager_initialized",
            take_profit_pct=take_profit_pct,
            stop_loss_pct=stop_loss_pct,
        )

    def check_position_risk(
        self,
        position: Position,
        current_price: Decimal,
    ) -> tuple[bool, str]:
        """
        检查持仓是否触发 TP/SL

        Args:
            position: 当前持仓
            current_price: 当前市场价格

        Returns:
            tuple[bool, str]: (是否应该平仓, 触发原因)
                - (True, "take_profit") - 触发止盈
                - (True, "stop_loss") - 触发止损
                - (False, "") - 未触发

        说明：
            多头持仓（size > 0）：
                - TP: current_price >= entry_price * (1 + tp_pct)
                - SL: current_price <= entry_price * (1 - sl_pct)

            空头持仓（size < 0）：
                - TP: current_price <= entry_price * (1 - tp_pct)
                - SL: current_price >= entry_price * (1 + sl_pct)
        """
        # 验证持仓有效性
        if position.size == 0:
            return False, ""

        if position.entry_price is None or position.entry_price == 0:
            logger.warning(
                "tp_sl_check_skipped_no_entry_price",
                symbol=position.symbol,
                size=float(position.size),
            )
            return False, ""

        # 计算止盈止损价格
        entry_price = position.entry_price
        is_long = position.size > 0

        if is_long:
            # 多头持仓
            tp_price = entry_price * (Decimal("1") + self.take_profit_pct)
            sl_price = entry_price * (Decimal("1") - self.stop_loss_pct)

            # 检查止盈
            if current_price >= tp_price:
                pnl_pct = float((current_price - entry_price) / entry_price * 100)
                logger.info(
                    "take_profit_triggered",
                    symbol=position.symbol,
                    side="LONG",
                    entry_price=float(entry_price),
                    current_price=float(current_price),
                    tp_price=float(tp_price),
                    pnl_pct=pnl_pct,
                )
                audit_logger.info(
                    "tp_sl_triggered",
                    trigger="take_profit",
                    symbol=position.symbol,
                    side="LONG",
                    entry_price=float(entry_price),
                    exit_price=float(current_price),
                    target_price=float(tp_price),
                    pnl_pct=pnl_pct,
                )
                return True, "take_profit"

            # 检查止损
            if current_price <= sl_price:
                pnl_pct = float((current_price - entry_price) / entry_price * 100)
                logger.warning(
                    "stop_loss_triggered",
                    symbol=position.symbol,
                    side="LONG",
                    entry_price=float(entry_price),
                    current_price=float(current_price),
                    sl_price=float(sl_price),
                    pnl_pct=pnl_pct,
                )
                audit_logger.warning(
                    "tp_sl_triggered",
                    trigger="stop_loss",
                    symbol=position.symbol,
                    side="LONG",
                    entry_price=float(entry_price),
                    exit_price=float(current_price),
                    target_price=float(sl_price),
                    pnl_pct=pnl_pct,
                )
                return True, "stop_loss"

        else:
            # 空头持仓（size < 0）
            tp_price = entry_price * (Decimal("1") - self.take_profit_pct)
            sl_price = entry_price * (Decimal("1") + self.stop_loss_pct)

            # 检查止盈（价格下跌到 TP）
            if current_price <= tp_price:
                pnl_pct = float((entry_price - current_price) / entry_price * 100)
                logger.info(
                    "take_profit_triggered",
                    symbol=position.symbol,
                    side="SHORT",
                    entry_price=float(entry_price),
                    current_price=float(current_price),
                    tp_price=float(tp_price),
                    pnl_pct=pnl_pct,
                )
                audit_logger.info(
                    "tp_sl_triggered",
                    trigger="take_profit",
                    symbol=position.symbol,
                    side="SHORT",
                    entry_price=float(entry_price),
                    exit_price=float(current_price),
                    target_price=float(tp_price),
                    pnl_pct=pnl_pct,
                )
                return True, "take_profit"

            # 检查止损（价格上涨到 SL）
            if current_price >= sl_price:
                pnl_pct = float((entry_price - current_price) / entry_price * 100)
                logger.warning(
                    "stop_loss_triggered",
                    symbol=position.symbol,
                    side="SHORT",
                    entry_price=float(entry_price),
                    current_price=float(current_price),
                    sl_price=float(sl_price),
                    pnl_pct=pnl_pct,
                )
                audit_logger.warning(
                    "tp_sl_triggered",
                    trigger="stop_loss",
                    symbol=position.symbol,
                    side="SHORT",
                    entry_price=float(entry_price),
                    exit_price=float(current_price),
                    target_price=float(sl_price),
                    pnl_pct=pnl_pct,
                )
                return True, "stop_loss"

        # 未触发
        return False, ""

    def get_tp_sl_prices(
        self,
        entry_price: Decimal,
        side: OrderSide,
    ) -> tuple[Decimal, Decimal]:
        """
        计算止盈止损价格

        Args:
            entry_price: 开仓价格
            side: 持仓方向

        Returns:
            tuple[Decimal, Decimal]: (TP 价格, SL 价格)
        """
        if side == OrderSide.BUY:
            # 多头
            tp_price = entry_price * (Decimal("1") + self.take_profit_pct)
            sl_price = entry_price * (Decimal("1") - self.stop_loss_pct)
        else:
            # 空头
            tp_price = entry_price * (Decimal("1") - self.take_profit_pct)
            sl_price = entry_price * (Decimal("1") + self.stop_loss_pct)

        return tp_price, sl_price

    def __repr__(self) -> str:
        return (
            f"TPSLManager(tp={self.take_profit_pct*100:.1f}%, "
            f"sl={self.stop_loss_pct*100:.1f}%)"
        )
