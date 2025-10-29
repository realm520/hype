"""影子持仓管理器

用于影子交易系统，跟踪模拟持仓和盈亏。
与 PositionManager 接口一致，方便切换到真实交易。
"""

import time
from dataclasses import dataclass
from decimal import Decimal

import structlog

from src.core.types import OrderSide, OrderStatus
from src.execution.shadow_executor import ShadowExecutionRecord
from src.risk.position_lifecycle import ClosedPosition, PositionLifecycleTracker

logger = structlog.get_logger()


@dataclass
class ShadowPosition:
    """影子持仓信息（模拟）"""

    symbol: str
    size: Decimal  # 持仓数量（正数多头，负数空头）
    entry_price: Decimal  # 平均开仓价
    current_price: Decimal  # 当前价格
    unrealized_pnl: Decimal  # 未实现盈亏
    realized_pnl: Decimal  # 已实现盈亏
    open_timestamp: int = 0  # 开仓时间戳（毫秒）
    side: OrderSide | None = None  # 持仓方向（BUY=多头，SELL=空头）

    @property
    def position_value_usd(self) -> Decimal:
        """持仓价值（USD）"""
        return abs(self.size) * self.current_price

    @property
    def is_long(self) -> bool:
        """是否多头"""
        return self.size > 0

    @property
    def is_short(self) -> bool:
        """是否空头"""
        return self.size < 0

    @property
    def is_flat(self) -> bool:
        """是否平仓"""
        return self.size == 0


class ShadowPositionManager(PositionLifecycleTracker):
    """影子持仓管理器

    职责：
        1. 跟踪每个交易对的模拟持仓
        2. 计算未实现盈亏（基于当前市场价格）
        3. 计算已实现盈亏（平仓时）
        4. 提供持仓查询接口
        5. 记录持仓生命周期（开仓 → 平仓）

    与 PositionManager 接口一致，方便切换到真实交易。
    继承 PositionLifecycleTracker，提供胜率/盈亏比追踪。
    """

    def __init__(self) -> None:
        """初始化影子持仓管理器"""
        super().__init__()  # 初始化生命周期追踪器

        # symbol -> ShadowPosition
        self._positions: dict[str, ShadowPosition] = {}

        logger.info("shadow_position_manager_initialized")

    def update_from_execution_record(
        self, record: ShadowExecutionRecord, fill_price: Decimal | None = None
    ) -> None:
        """
        根据影子执行记录更新持仓

        Args:
            record: 影子执行记录
            fill_price: 实际成交价（如果为 None，使用记录中的平均成交价）
        """
        order = record.order

        # 只处理成交的订单
        if order.status not in [OrderStatus.FILLED, OrderStatus.PARTIAL_FILLED]:
            return

        # 跳过的订单不更新持仓
        if record.skipped:
            return

        # 确定成交价
        if fill_price is not None:
            actual_price = fill_price
        elif order.avg_fill_price is not None:
            actual_price = order.avg_fill_price
        else:
            actual_price = order.price

        fill_size = order.filled_size if order.filled_size > 0 else order.size

        # 获取或创建持仓
        if order.symbol not in self._positions:
            self._positions[order.symbol] = ShadowPosition(
                symbol=order.symbol,
                size=Decimal("0"),
                entry_price=Decimal("0"),
                current_price=actual_price,
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
                open_timestamp=int(time.time() * 1000),  # 毫秒时间戳
                side=None,
            )

        position = self._positions[order.symbol]

        # 计算新持仓
        old_size = position.size
        trade_size = fill_size if order.side == OrderSide.BUY else -fill_size
        new_size = old_size + trade_size

        # 首次开仓（从 0 到非 0）
        if old_size == 0 and new_size != 0:
            position.side = OrderSide.BUY if new_size > 0 else OrderSide.SELL
            position.open_timestamp = int(time.time() * 1000)

        # 计算已实现盈亏（如果是平仓交易）
        if (old_size > 0 and trade_size < 0) or (old_size < 0 and trade_size > 0):
            # 平仓交易，计算已实现盈亏
            close_size = min(abs(old_size), abs(trade_size))
            if old_size > 0:
                # 平多仓
                realized_pnl = close_size * (actual_price - position.entry_price)
            else:
                # 平空仓
                realized_pnl = close_size * (position.entry_price - actual_price)

            position.realized_pnl += realized_pnl

            logger.info(
                "shadow_position_closed",
                symbol=order.symbol,
                close_size=float(close_size),
                entry_price=float(position.entry_price),
                exit_price=float(actual_price),
                realized_pnl=float(realized_pnl),
            )

        # 更新持仓和开仓价
        if new_size == 0:
            # 完全平仓 - 记录闭仓
            if position.side is not None and old_size != 0:
                # 记录闭仓到生命周期追踪器
                closed_position = ClosedPosition(
                    symbol=order.symbol,
                    side=position.side,
                    entry_price=position.entry_price,
                    exit_price=actual_price,
                    size=abs(old_size),
                    realized_pnl=position.realized_pnl,
                    open_timestamp=position.open_timestamp,
                    close_timestamp=int(time.time() * 1000),  # 毫秒时间戳
                )
                self.record_closed_position(closed_position)

            position.size = Decimal("0")
            position.entry_price = Decimal("0")
            position.side = None
            position.open_timestamp = 0
        elif (old_size > 0 and new_size > 0 and trade_size > 0) or (
            old_size < 0 and new_size < 0 and trade_size < 0
        ):
            # 加仓（同方向交易）
            total_cost = abs(old_size) * position.entry_price + abs(
                trade_size
            ) * actual_price
            position.entry_price = total_cost / abs(new_size)
            position.size = new_size
            # 保持 side 和 open_timestamp
        elif (old_size > 0 and new_size > 0) or (old_size < 0 and new_size < 0):
            # 部分平仓（保持 entry_price 不变）
            position.size = new_size
            # entry_price, side, open_timestamp 保持不变
        else:
            # 反向开仓（新持仓）
            position.size = new_size
            position.entry_price = actual_price
            position.side = OrderSide.BUY if new_size > 0 else OrderSide.SELL
            position.open_timestamp = int(time.time() * 1000)

        position.current_price = actual_price

        logger.info(
            "shadow_position_updated",
            symbol=order.symbol,
            old_size=float(old_size),
            new_size=float(position.size),
            entry_price=float(position.entry_price),
            current_price=float(actual_price),
        )

    def update_prices(self, prices: dict[str, Decimal]) -> None:
        """
        更新所有持仓的当前价格

        Args:
            prices: symbol -> price 映射
        """
        for symbol, position in self._positions.items():
            if symbol in prices:
                position.current_price = prices[symbol]

                # 重新计算未实现盈亏
                if position.size != 0:
                    if position.size > 0:
                        # 多头
                        position.unrealized_pnl = position.size * (
                            position.current_price - position.entry_price
                        )
                    else:
                        # 空头
                        position.unrealized_pnl = abs(position.size) * (
                            position.entry_price - position.current_price
                        )

    def get_position(self, symbol: str) -> ShadowPosition | None:
        """
        获取持仓

        Args:
            symbol: 交易对

        Returns:
            Optional[ShadowPosition]: 持仓对象，未找到返回 None
        """
        return self._positions.get(symbol)

    def get_all_positions(self) -> dict[str, ShadowPosition]:
        """
        获取所有持仓

        Returns:
            Dict[str, ShadowPosition]: 所有持仓
        """
        return self._positions.copy()

    def get_total_position_value(self) -> Decimal:
        """
        获取总持仓价值（USD）

        Returns:
            Decimal: 总持仓价值
        """
        total = Decimal("0")
        for position in self._positions.values():
            total += position.position_value_usd

        return total

    def get_total_unrealized_pnl(self) -> Decimal:
        """
        获取总未实现盈亏

        Returns:
            Decimal: 总未实现盈亏
        """
        total = Decimal("0")
        for position in self._positions.values():
            total += position.unrealized_pnl

        return total

    def get_total_realized_pnl(self) -> Decimal:
        """
        获取总已实现盈亏

        Returns:
            Decimal: 总已实现盈亏
        """
        total = Decimal("0")
        for position in self._positions.values():
            total += position.realized_pnl

        return total

    def get_total_pnl(self) -> Decimal:
        """
        获取总盈亏（已实现 + 未实现）

        Returns:
            Decimal: 总盈亏
        """
        return self.get_total_realized_pnl() + self.get_total_unrealized_pnl()

    def get_statistics(self) -> dict:
        """
        获取持仓统计信息

        Returns:
            dict: 统计信息
        """
        total_positions = len(self._positions)
        long_positions = sum(1 for p in self._positions.values() if p.is_long)
        short_positions = sum(1 for p in self._positions.values() if p.is_short)
        flat_positions = sum(1 for p in self._positions.values() if p.is_flat)

        return {
            "total_positions": total_positions,
            "long_positions": long_positions,
            "short_positions": short_positions,
            "flat_positions": flat_positions,
            "total_position_value": float(self.get_total_position_value()),
            "total_unrealized_pnl": float(self.get_total_unrealized_pnl()),
            "total_realized_pnl": float(self.get_total_realized_pnl()),
            "total_pnl": float(self.get_total_pnl()),
        }

    def reset(self) -> None:
        """
        重置所有持仓（用于重新开始影子交易）
        """
        logger.warning("shadow_position_manager_reset")
        self._positions.clear()

    def __repr__(self) -> str:
        return (
            f"ShadowPositionManager(positions={len(self._positions)}, "
            f"total_value={float(self.get_total_position_value()):.2f}, "
            f"total_pnl={float(self.get_total_pnl()):.2f})"
        )
