"""订单管理器

协调订单执行、滑点估算和订单跟踪。
"""

from collections import deque
from decimal import Decimal
from typing import cast

import structlog

from src.core.types import MarketData, Order, OrderSide, OrderStatus, SignalScore
from src.execution.ioc_executor import IOCExecutor
from src.execution.slippage_estimator import SlippageEstimator

logger = structlog.get_logger()


class OrderManager:
    """订单管理器

    职责：
        1. 执行前滑点评估
        2. 协调 IOC 执行器下单
        3. 跟踪订单状态
        4. 记录订单历史
    """

    def __init__(
        self,
        executor: IOCExecutor,
        slippage_estimator: SlippageEstimator,
        max_order_history: int = 10000,
    ):
        """
        初始化订单管理器

        Args:
            executor: IOC 执行器
            slippage_estimator: 滑点估算器
            max_order_history: 最大订单历史记录数
        """
        self.executor = executor
        self.slippage_estimator = slippage_estimator
        self.max_order_history = max_order_history

        # 订单历史（使用 deque 自动限制大小）
        self._order_history: deque = deque(maxlen=max_order_history)

        # 活跃订单（order_id -> Order）
        self._active_orders: dict[str, Order] = {}

        logger.info(
            "order_manager_initialized",
            max_order_history=max_order_history,
        )

    async def execute_signal(
        self,
        signal_score: SignalScore,
        market_data: MarketData,
        size: Decimal | None = None,
    ) -> Order | None:
        """
        根据信号执行订单

        流程：
            1. 判断是否应该执行
            2. 估算滑点
            3. 检查滑点是否可接受
            4. 执行订单
            5. 记录订单

        Args:
            signal_score: 信号评分
            market_data: 市场数据
            size: 订单大小（可选）

        Returns:
            Optional[Order]: 执行的订单，如果跳过则返回 None
        """
        try:
            # 1. 判断是否执行
            if not self.executor.should_execute(signal_score):
                logger.info(
                    "execution_skipped",
                    symbol=market_data.symbol,
                    confidence=signal_score.confidence.name,
                    signal_value=signal_score.value,
                )
                return None

            # 2. 确定订单参数
            order_size = size if size is not None else self.executor.default_size
            side = self._determine_side(signal_score.value)

            if side is None:
                logger.warning(
                    "cannot_determine_side",
                    symbol=market_data.symbol,
                    signal_value=signal_score.value,
                )
                return None

            # 3. 估算滑点
            slippage_result = self.slippage_estimator.estimate(
                market_data=market_data,
                side=side,
                size=order_size,
            )

            # 4. 检查滑点
            if not slippage_result["is_acceptable"]:
                logger.warning(
                    "execution_rejected_high_slippage",
                    symbol=market_data.symbol,
                    side=side.name,
                    size=float(order_size),
                    slippage_bps=slippage_result["slippage_bps"],
                    max_slippage_bps=self.slippage_estimator.max_slippage_bps,
                )
                return None

            # 5. 执行订单
            order = await self.executor.execute(
                signal_score=signal_score,
                market_data=market_data,
                size=order_size,
            )

            if order:
                # 6. 记录订单
                self._record_order(order)

                logger.info(
                    "order_executed",
                    order_id=order.id,
                    symbol=order.symbol,
                    side=order.side.name,
                    size=float(order.size),
                    price=float(order.price),
                    status=order.status.name,
                )

            return order

        except Exception as e:
            logger.error(
                "order_execution_error",
                symbol=market_data.symbol,
                error=str(e),
                exc_info=True,
            )
            return None

    def _determine_side(self, signal_value: float) -> OrderSide | None:
        """确定订单方向"""
        if signal_value > 0:
            return OrderSide.BUY
        elif signal_value < 0:
            return OrderSide.SELL
        else:
            return None

    def _record_order(self, order: Order) -> None:
        """
        记录订单

        Args:
            order: 订单对象
        """
        # 添加到历史
        self._order_history.append(order)

        # 如果是活跃订单，添加到活跃订单字典
        if order.status in [OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED]:
            self._active_orders[order.id] = order
        elif order.id in self._active_orders:
            # 订单完结，从活跃订单中移除
            del self._active_orders[order.id]

        logger.debug(
            "order_recorded",
            order_id=order.id,
            status=order.status.name,
            active_orders_count=len(self._active_orders),
            history_count=len(self._order_history),
        )

    def get_order_history(
        self,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[Order]:
        """
        获取订单历史

        Args:
            symbol: 交易对过滤（可选）
            limit: 最大返回数量

        Returns:
            List[Order]: 订单列表（最新在前）
        """
        orders = list(self._order_history)

        # 按时间倒序
        orders.reverse()

        # 过滤交易对
        if symbol:
            orders = [order for order in orders if order.symbol == symbol]

        # 限制数量
        return orders[:limit]

    def get_active_orders(self, symbol: str | None = None) -> list[Order]:
        """
        获取活跃订单

        Args:
            symbol: 交易对过滤（可选）

        Returns:
            List[Order]: 活跃订单列表
        """
        orders = list(self._active_orders.values())

        if symbol:
            orders = [order for order in orders if order.symbol == symbol]

        return orders

    def get_order_by_id(self, order_id: str) -> Order | None:
        """
        根据 ID 获取订单

        Args:
            order_id: 订单 ID

        Returns:
            Optional[Order]: 订单对象，未找到返回 None
        """
        # 先查活跃订单
        if order_id in self._active_orders:
            return self._active_orders[order_id]

        # 再查历史订单
        for order in self._order_history:
            if order.id == order_id:
                return cast(Order, order)

        return None

    def get_statistics(self) -> dict:
        """
        获取订单统计信息

        Returns:
            dict: 统计信息
        """
        total_orders = len(self._order_history)
        active_orders = len(self._active_orders)

        # 统计各状态订单数
        status_counts: dict[str, int] = {}
        for order in self._order_history:
            status = order.status.name
            status_counts[status] = status_counts.get(status, 0) + 1

        # 统计各交易对订单数
        symbol_counts: dict[str, int] = {}
        for order in self._order_history:
            symbol = order.symbol
            symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1

        return {
            "total_orders": total_orders,
            "active_orders": active_orders,
            "status_counts": status_counts,
            "symbol_counts": symbol_counts,
        }

    def __repr__(self) -> str:
        return (
            f"OrderManager(active_orders={len(self._active_orders)}, "
            f"history_count={len(self._order_history)})"
        )
