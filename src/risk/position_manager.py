"""持仓管理器

跟踪和管理所有交易对的持仓状态。
"""

import time
from decimal import Decimal

import structlog

from src.core.types import Order, OrderSide, OrderStatus, Position

logger = structlog.get_logger()


class PositionManager:
    """持仓管理器

    职责：
        1. 跟踪每个交易对的持仓
        2. 计算未实现盈亏
        3. 更新持仓状态
        4. 提供持仓查询接口
    """

    def __init__(self) -> None:
        """初始化持仓管理器"""
        # symbol -> Position
        self._positions: dict[str, Position] = {}

        logger.info("position_manager_initialized")

    def update_from_order(self, order: Order, fill_price: Decimal | None = None) -> None:
        """
        根据订单更新持仓

        Args:
            order: 订单对象
            fill_price: 实际成交价（如果为 None，使用订单价格）
        """
        # 只处理成交的订单
        if order.status != OrderStatus.FILLED:
            return

        # 确定成交价
        actual_price = fill_price if fill_price is not None else order.price
        fill_size = order.filled_size if order.filled_size > 0 else order.size

        # 获取或创建持仓
        if order.symbol not in self._positions:
            self._positions[order.symbol] = Position(
                symbol=order.symbol,
                size=Decimal("0"),
                entry_price=Decimal("0"),
                current_price=actual_price,
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
                open_timestamp=None,  # Week 2: 初始状态无开仓时间
                side=None,  # Week 2: 初始状态无方向
            )

        position = self._positions[order.symbol]

        # 计算新持仓
        old_size = position.size
        trade_size = fill_size if order.side == OrderSide.BUY else -fill_size
        new_size = old_size + trade_size

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
                "position_closed",
                symbol=order.symbol,
                close_size=float(close_size),
                entry_price=float(position.entry_price),
                exit_price=float(actual_price),
                realized_pnl=float(realized_pnl),
            )

        # 更新持仓和开仓价
        if new_size == 0:
            # 完全平仓
            position.size = Decimal("0")
            position.entry_price = Decimal("0")
            # Week 2: 清空生命周期字段
            position.open_timestamp = None
            position.side = None
        elif (old_size > 0 and new_size > 0 and trade_size > 0) or (old_size < 0 and new_size < 0 and trade_size < 0):
            # 加仓（同方向交易）
            total_cost = abs(old_size) * position.entry_price + abs(trade_size) * actual_price
            position.entry_price = total_cost / abs(new_size)
            position.size = new_size
            # Week 2: 保持开仓时间和方向不变（加仓不更新）
        elif (old_size > 0 and new_size > 0) or (old_size < 0 and new_size < 0):
            # 部分平仓（保持 entry_price 不变）
            position.size = new_size
            # entry_price 保持不变
            # Week 2: 保持开仓时间和方向不变
        else:
            # 反向开仓（从空仓或反向开仓）
            position.size = new_size
            position.entry_price = actual_price
            # Week 2: 记录新开仓的时间和方向
            if old_size == 0:
                position.open_timestamp = int(time.time() * 1000)  # 毫秒时间戳
                position.side = order.side  # BUY 或 SELL

        position.current_price = actual_price

        logger.info(
            "position_updated",
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

    def get_position(self, symbol: str) -> Position | None:
        """
        获取持仓

        Args:
            symbol: 交易对

        Returns:
            Optional[Position]: 持仓对象，未找到返回 None
        """
        return self._positions.get(symbol)

    def get_all_positions(self) -> dict[str, Position]:
        """
        获取所有持仓

        Returns:
            Dict[str, Position]: 所有持仓
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
        }

    def get_position_age_seconds(self, symbol: str) -> float | None:
        """
        获取持仓存活时间（秒）

        Week 2 新增：用于超时平仓检测

        Args:
            symbol: 交易对

        Returns:
            float | None: 持仓存活时间（秒），未找到或未开仓返回 None
        """
        position = self.get_position(symbol)
        if not position or position.open_timestamp is None:
            return None

        current_time_ms = int(time.time() * 1000)
        age_ms = current_time_ms - position.open_timestamp
        return age_ms / 1000.0  # 转换为秒

    def is_position_stale(self, symbol: str, max_age_seconds: float) -> bool:
        """
        检查持仓是否过期（超过最大存活时间）

        Week 2 新增：用于超时平仓触发器

        Args:
            symbol: 交易对
            max_age_seconds: 最大存活时间（秒）

        Returns:
            bool: True 表示持仓过期，False 表示未过期或不存在
        """
        age = self.get_position_age_seconds(symbol)
        if age is None:
            return False  # 未开仓或不存在，不算过期

        return age > max_age_seconds

    def __repr__(self) -> str:
        return (
            f"PositionManager(positions={len(self._positions)}, "
            f"total_value={float(self.get_total_position_value()):.2f})"
        )
