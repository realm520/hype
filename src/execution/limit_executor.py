"""限价单执行器

Week 2 核心执行策略：中等置信度信号使用被动限价单降低成本。
"""

import asyncio
import time
from decimal import Decimal

import structlog

from src.core.logging import get_audit_logger
from src.core.types import (
    ConfidenceLevel,
    MarketData,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    SignalScore,
)
from src.hyperliquid.api_client import HyperliquidAPIClient

logger = structlog.get_logger()
audit_logger = get_audit_logger()


class LimitExecutor:
    """限价单执行器（Post-only）

    Week 2 策略：
        - MEDIUM 置信度 → 执行限价单（Post-only）
        - 贴盘口价格，使用 Maker 费率（+0.015%，比 Taker 节省 3 bps）
        - 超时未成交 → 撤单

    执行逻辑：
        1. 信号 theta_2 < |signal| ≤ theta_1 → 限价单
        2. 下单后监控成交状态
        3. 超时未成交 → 撤单（返回 None 供路由器重试）

    费率对比：
        - Maker：+0.015%（1.5 bps）
        - Taker：+0.045%（4.5 bps）
        - 节省：3 bps = 0.03%
    """

    def __init__(
        self,
        api_client: HyperliquidAPIClient,
        default_size: Decimal = Decimal("0.01"),
        timeout_seconds: float = 5.0,
        use_post_only: bool = True,
    ):
        """
        初始化限价单执行器

        Args:
            api_client: Hyperliquid API 客户端
            default_size: 默认订单大小（默认 0.01）
            timeout_seconds: 成交超时时间（秒），超时后撤单
            use_post_only: 是否使用 Post-only（确保成为 Maker）
        """
        self.api_client = api_client
        self.default_size = default_size
        self.timeout_seconds = timeout_seconds
        self.use_post_only = use_post_only

        logger.info(
            "limit_executor_initialized",
            default_size=float(default_size),
            timeout_seconds=timeout_seconds,
            use_post_only=use_post_only,
        )

    async def execute(
        self,
        signal_score: SignalScore,
        market_data: MarketData,
        size: Decimal | None = None,
    ) -> Order | None:
        """
        根据信号评分执行限价单

        Args:
            signal_score: 信号评分
            market_data: 市场数据
            size: 订单大小（如果为 None，使用默认大小）

        Returns:
            Optional[Order]: 执行的订单，如果超时撤单则返回 None
        """
        start_time = time.time()

        try:
            # 检查置信度（仅接受 MEDIUM）
            if signal_score.confidence != ConfidenceLevel.MEDIUM:
                logger.info(
                    "execution_skipped_wrong_confidence",
                    symbol=market_data.symbol,
                    signal_value=signal_score.value,
                    confidence=signal_score.confidence.name,
                    expected="MEDIUM",
                )
                return None

            # 确定订单方向
            if signal_score.value > 0:
                side = OrderSide.BUY
            elif signal_score.value < 0:
                side = OrderSide.SELL
            else:
                logger.warning(
                    "execution_skipped_zero_signal",
                    symbol=market_data.symbol,
                )
                return None

            # 计算订单参数
            order_size = size if size is not None else self.default_size
            order_price = self._calculate_limit_price(market_data, side)

            # 记录执行意图
            logger.info(
                "executing_limit_order",
                symbol=market_data.symbol,
                side=side.name,
                size=float(order_size),
                price=float(order_price),
                signal_value=signal_score.value,
                confidence=signal_score.confidence.name,
                post_only=self.use_post_only,
            )

            # 执行限价单
            order_result = await self.api_client.place_order(
                symbol=market_data.symbol,
                side=side,
                size=order_size,
                price=order_price,
                order_type=OrderType.LIMIT,
                post_only=self.use_post_only,
            )

            # 解析订单结果
            order = self._parse_order_result(
                order_result,
                market_data.symbol,
                side,
                order_size,
                order_price,
            )

            # 如果订单被拒绝，直接返回
            if order.status == OrderStatus.REJECTED:
                logger.warning(
                    "limit_order_rejected",
                    symbol=market_data.symbol,
                    order_id=order.id,
                    error=order.error_message,
                )
                return None

            # 等待成交或超时
            filled_order = await self._wait_for_fill(order, market_data.symbol)

            # 计算延迟
            latency_ms = (time.time() - start_time) * 1000

            if filled_order is not None:
                # 成交成功
                logger.info(
                    "limit_order_filled",
                    symbol=market_data.symbol,
                    order_id=filled_order.id,
                    side=side.name,
                    size=float(order_size),
                    price=float(order_price),
                    filled_size=float(filled_order.filled_size),
                    latency_ms=latency_ms,
                )

                # 记录审计日志（关键交易操作）
                audit_logger.info(
                    "order_executed",
                    order_id=filled_order.id,
                    symbol=market_data.symbol,
                    side=side.name,
                    order_type="LIMIT",
                    size=float(order_size),
                    price=float(order_price),
                    filled_size=float(filled_order.filled_size),
                    status=filled_order.status.name,
                    signal_value=signal_score.value,
                    signal_confidence=signal_score.confidence.name,
                    latency_ms=latency_ms,
                    post_only=self.use_post_only,
                )

                return filled_order
            else:
                # 超时未成交
                logger.warning(
                    "limit_order_timeout_cancelled",
                    symbol=market_data.symbol,
                    order_id=order.id,
                    timeout_seconds=self.timeout_seconds,
                    latency_ms=latency_ms,
                )
                return None

        except Exception as e:
            logger.error(
                "limit_execution_error",
                symbol=market_data.symbol,
                error=str(e),
                exc_info=True,
            )
            return None

    async def _wait_for_fill(
        self, order: Order, symbol: str, check_interval: float = 0.1
    ) -> Order | None:
        """
        等待订单成交或超时

        Args:
            order: 待成交订单
            symbol: 交易对
            check_interval: 检查间隔（秒）

        Returns:
            Optional[Order]: 成交后的订单，超时则撤单并返回 None
        """
        start_time = time.time()

        while time.time() - start_time < self.timeout_seconds:
            # 查询订单状态
            try:
                order_status = await self.api_client.get_order_status(
                    symbol=symbol, order_id=order.id
                )

                # 检查是否成交
                if order_status.get("status") == "filled":
                    # 更新订单对象
                    order.status = OrderStatus.FILLED
                    order.filled_size = Decimal(
                        str(order_status.get("filled_size", order.size))
                    )
                    return order

                # 检查是否被拒绝或取消
                if order_status.get("status") in ["rejected", "cancelled"]:
                    return None

            except Exception as e:
                logger.error(
                    "order_status_query_error",
                    symbol=symbol,
                    order_id=order.id,
                    error=str(e),
                )

            # 等待一段时间后重试
            await asyncio.sleep(check_interval)

        # 超时，尝试撤单
        try:
            await self.api_client.cancel_order(symbol=symbol, order_id=order.id)
            logger.info(
                "limit_order_cancelled_on_timeout",
                symbol=symbol,
                order_id=order.id,
                elapsed_seconds=self.timeout_seconds,
            )
        except Exception as e:
            logger.error(
                "order_cancellation_error",
                symbol=symbol,
                order_id=order.id,
                error=str(e),
            )

        return None

    def _calculate_limit_price(
        self, market_data: MarketData, side: OrderSide
    ) -> Decimal:
        """
        计算限价单价格（贴盘口）

        策略：
            - 买入：使用最优买价（成为 Maker，排队等待）
            - 卖出：使用最优卖价（成为 Maker，排队等待）

        Args:
            market_data: 市场数据
            side: 订单方向

        Returns:
            Decimal: 限价单价格
        """
        if side == OrderSide.BUY:
            # 买入：使用最优买价（排队在买盘顶部）
            best_bid = market_data.bids[0]
            price = best_bid.price
        else:
            # 卖出：使用最优卖价（排队在卖盘顶部）
            best_ask = market_data.asks[0]
            price = best_ask.price

        return price

    def _parse_order_result(
        self,
        result: dict,
        symbol: str,
        side: OrderSide,
        size: Decimal,
        price: Decimal,
    ) -> Order:
        """
        解析 API 返回的订单结果

        Args:
            result: API 返回结果
            symbol: 交易对
            side: 订单方向
            size: 订单大小
            price: 订单价格

        Returns:
            Order: 订单对象
        """
        # Hyperliquid API 返回格式
        status = result.get("status", "unknown")

        # 映射状态
        if status == "success":
            order_status = OrderStatus.PENDING  # 限价单初始状态为 PENDING
        elif status == "error":
            order_status = OrderStatus.REJECTED
        else:
            order_status = OrderStatus.PENDING

        # 提取订单信息
        order_data = result.get("response", {}).get("data", {})
        statuses = order_data.get("statuses", [{}])
        first_status = statuses[0] if statuses else {}

        return Order(
            id=str(result.get("id", "unknown")),
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            price=price,
            size=size,
            filled_size=Decimal("0"),  # 限价单初始未成交
            status=order_status,
            created_at=int(time.time() * 1000),
            error_message=first_status.get("error", None),
        )

    def should_execute(self, signal_score: SignalScore) -> bool:
        """
        判断是否应该执行订单

        Args:
            signal_score: 信号评分

        Returns:
            bool: 是否执行
        """
        return signal_score.confidence == ConfidenceLevel.MEDIUM

    def __repr__(self) -> str:
        return (
            f"LimitExecutor(default_size={self.default_size}, "
            f"timeout_seconds={self.timeout_seconds}, "
            f"use_post_only={self.use_post_only})"
        )
