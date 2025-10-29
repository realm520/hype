"""持仓生命周期追踪器

提供持仓从开仓到平仓的完整生命周期管理。
核心逻辑可被 Shadow 和实盘系统共享。
"""

from dataclasses import dataclass
from decimal import Decimal

import structlog

from src.core.types import OrderSide

logger = structlog.get_logger()


@dataclass
class ClosedPosition:
    """已平仓记录（Shadow + 实盘共用）"""

    symbol: str
    side: OrderSide  # 持仓方向（BUY=多头，SELL=空头）
    entry_price: Decimal  # 平均开仓价
    exit_price: Decimal  # 平均平仓价
    size: Decimal  # 持仓数量
    realized_pnl: Decimal  # 已实现盈亏
    open_timestamp: int  # 开仓时间戳（毫秒）
    close_timestamp: int  # 平仓时间戳（毫秒）

    @property
    def holding_duration_seconds(self) -> float:
        """持仓时长（秒）"""
        return (self.close_timestamp - self.open_timestamp) / 1000.0

    @property
    def is_win(self) -> bool:
        """是否盈利"""
        return self.realized_pnl > 0

    @property
    def return_percentage(self) -> float:
        """收益率（%）"""
        if self.entry_price == 0:
            return 0.0
        return float((self.exit_price - self.entry_price) / self.entry_price * 100)


class PositionLifecycleTracker:
    """持仓生命周期追踪器（Shadow + 实盘共用）

    职责：
        1. 记录已平仓交易
        2. 计算胜率（Win Rate）
        3. 计算盈亏比（Profit/Loss Ratio）
        4. 提供闭仓历史查询
    """

    def __init__(self):
        """初始化生命周期追踪器"""
        self._closed_positions: list[ClosedPosition] = []

        logger.info("position_lifecycle_tracker_initialized")

    def record_closed_position(self, position: ClosedPosition) -> None:
        """
        记录已平仓

        Args:
            position: 已平仓记录
        """
        self._closed_positions.append(position)

        logger.info(
            "position_closed",
            symbol=position.symbol,
            side=position.side.name,
            entry_price=float(position.entry_price),
            exit_price=float(position.exit_price),
            size=float(position.size),
            realized_pnl=float(position.realized_pnl),
            is_win=position.is_win,
            holding_duration_sec=position.holding_duration_seconds,
        )

    def get_closed_positions(
        self, symbol: str | None = None, last_n: int | None = None
    ) -> list[ClosedPosition]:
        """
        获取闭仓记录

        Args:
            symbol: 交易对符号（None=全部）
            last_n: 最近 N 笔（None=全部）

        Returns:
            list[ClosedPosition]: 闭仓记录列表
        """
        positions = self._closed_positions

        # 按 symbol 过滤
        if symbol:
            positions = [p for p in positions if p.symbol == symbol]

        # 取最近 N 笔
        if last_n:
            positions = positions[-last_n:]

        return positions

    def calculate_win_rate(self, symbol: str | None = None) -> float:
        """
        计算胜率

        Args:
            symbol: 交易对符号（None=全部）

        Returns:
            float: 胜率（%），目标 ≥ 60%
        """
        positions = self.get_closed_positions(symbol=symbol)

        if not positions:
            return 0.0

        wins = sum(1 for p in positions if p.is_win)
        win_rate = wins / len(positions) * 100

        logger.debug(
            "win_rate_calculated",
            symbol=symbol or "ALL",
            total_trades=len(positions),
            wins=wins,
            win_rate=win_rate,
        )

        return win_rate

    def calculate_profit_loss_ratio(self, symbol: str | None = None) -> float:
        """
        计算盈亏比

        Args:
            symbol: 交易对符号（None=全部）

        Returns:
            float: 盈亏比（avg_win / avg_loss），目标 ≥ 1.5
        """
        positions = self.get_closed_positions(symbol=symbol)

        if not positions:
            return 0.0

        # 分离盈利和亏损交易
        wins = [p.realized_pnl for p in positions if p.realized_pnl > 0]
        losses = [abs(p.realized_pnl) for p in positions if p.realized_pnl < 0]

        # 计算平均盈利和平均亏损
        if not wins or not losses:
            # 只有盈利或只有亏损，盈亏比无意义
            return 0.0

        avg_win = sum(wins) / len(wins)
        avg_loss = sum(losses) / len(losses)

        if avg_loss == 0:
            return 0.0

        profit_loss_ratio = float(avg_win / avg_loss)

        logger.debug(
            "profit_loss_ratio_calculated",
            symbol=symbol or "ALL",
            total_trades=len(positions),
            wins_count=len(wins),
            losses_count=len(losses),
            avg_win=float(avg_win),
            avg_loss=float(avg_loss),
            profit_loss_ratio=profit_loss_ratio,
        )

        return profit_loss_ratio

    def get_statistics(self, symbol: str | None = None) -> dict:
        """
        获取统计摘要

        Args:
            symbol: 交易对符号（None=全部）

        Returns:
            dict: 统计摘要
        """
        positions = self.get_closed_positions(symbol=symbol)

        if not positions:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_loss_ratio": 0.0,
                "total_pnl": 0.0,
                "avg_holding_duration_sec": 0.0,
            }

        total_pnl = sum(p.realized_pnl for p in positions)
        avg_duration = sum(p.holding_duration_seconds for p in positions) / len(
            positions
        )

        return {
            "total_trades": len(positions),
            "win_rate": self.calculate_win_rate(symbol),
            "profit_loss_ratio": self.calculate_profit_loss_ratio(symbol),
            "total_pnl": float(total_pnl),
            "avg_holding_duration_sec": avg_duration,
        }
