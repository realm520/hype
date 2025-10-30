"""浅被动 Maker 执行器

Week 1.5 核心执行策略：盘口 +1 tick 挂单，降低成本提高成交概率。
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


class ShallowMakerExecutor:
    """浅被动 Maker 执行器（盘口 +1 tick）

    Week 1.5 策略：
        - HIGH/MEDIUM 置信度 → 执行浅被动 Maker 订单
        - 盘口 +1 tick 价格，提高成交概率同时保持 Maker 费率
        - 超时未成交 → 撤单并返回 None（供 HybridExecutor 决定是否 IOC 回退）

    执行逻辑：
        1. 信号置信度 HIGH 或 MEDIUM → 浅被动 Maker
        2. 下单后监控成交状态（异步轮询）
        3. 超时未成交 → 撤单
            - HIGH: 5 秒超时（更激进）
            - MEDIUM: 3 秒超时（快速放弃）

    费率优势：
        - Maker：+0.015%（1.5 bps）
        - Taker：+0.045%（4.5 bps）
        - 节省：3 bps = 0.03%（单边），往返 6 bps

    价格策略：
        - 买入：best_bid + 1 tick（稍高于盘口，排队靠前）
        - 卖出：best_ask - 1 tick（稍低于盘口，排队靠前）
        - tick_offset = 0.1 美元（BTC/ETH 标准）
    """

    def __init__(
        self,
        api_client: HyperliquidAPIClient,
        default_size: Decimal = Decimal("0.01"),
        timeout_high: float = 5.0,
        timeout_medium: float = 3.0,
        tick_offset: Decimal = Decimal("0.1"),
        use_post_only: bool = True,
    ):
        """
        初始化浅被动 Maker 执行器

        Args:
            api_client: Hyperliquid API 客户端
            default_size: 默认订单大小（默认 0.01）
            timeout_high: HIGH 置信度超时时间（秒）
            timeout_medium: MEDIUM 置信度超时时间（秒）
            tick_offset: 价格偏移量（tick，默认 0.1）
            use_post_only: 是否使用 Post-only（确保成为 Maker）
        """
        self.api_client = api_client
        self.default_size = default_size
        self.timeout_high = timeout_high
        self.timeout_medium = timeout_medium
        self.tick_offset = tick_offset
        self.use_post_only = use_post_only

        logger.info(
            "shallow_maker_executor_initialized",
            default_size=float(default_size),
            timeout_high=timeout_high,
            timeout_medium=timeout_medium,
            tick_offset=float(tick_offset),
            use_post_only=use_post_only,
        )

    async def execute(
        self,
        signal_score: SignalScore,
        market_data: MarketData,
        size: Decimal | None = None,
    ) -> Order | None:
        """
        根据信号评分执行浅被动 Maker 订单

        Args:
            signal_score: 信号评分
            market_data: 市场数据
            size: 订单大小（如果为 None，使用默认大小）

        Returns:
            Optional[Order]: 执行的订单，如果超时撤单则返回 None
        """
        start_time = time.time()

        try:
            # 检查置信度（接受 HIGH 和 MEDIUM）
            if signal_score.confidence not in [
                ConfidenceLevel.HIGH,
                ConfidenceLevel.MEDIUM,
            ]:
                logger.info(
                    "execution_skipped_wrong_confidence",
                    symbol=market_data.symbol,
                    signal_value=signal_score.value,
                    confidence=signal_score.confidence.name,
                    expected="HIGH or MEDIUM",
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
            order_price = self._calculate_shallow_maker_price(market_data, side)

            # 根据置信度选择超时时间
            timeout_seconds = (
                self.timeout_high
                if signal_score.confidence == ConfidenceLevel.HIGH
                else self.timeout_medium
            )

            # 记录执行意图
            logger.info(
                "executing_shallow_maker_order",
                symbol=market_data.symbol,
                side=side.name,
                size=float(order_size),
                price=float(order_price),
                signal_value=signal_score.value,
                confidence=signal_score.confidence.name,
                timeout_seconds=timeout_seconds,
                tick_offset=float(self.tick_offset),
                post_only=self.use_post_only,
            )

            # 执行浅被动 Maker 订单
            # TODO: API Client 需要支持 post_only 参数
            order_result = await self.api_client.place_order(
                symbol=market_data.symbol,
                side=side,
                size=order_size,
                price=order_price,
                order_type=OrderType.LIMIT,
                # post_only=self.use_post_only,  # 暂不支持
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
                    "shallow_maker_order_rejected",
                    symbol=market_data.symbol,
                    order_id=order.id,
                    error=order.error_message,
                )
                return None

            # 等待成交或超时
            filled_order = await self._wait_for_fill(
                order, market_data.symbol, timeout_seconds
            )

            # 计算延迟
            latency_ms = (time.time() - start_time) * 1000

            if filled_order is not None:
                # 成交成功
                logger.info(
                    "shallow_maker_order_filled",
                    symbol=market_data.symbol,
                    order_id=filled_order.id,
                    side=side.name,
                    size=float(order_size),
                    price=float(order_price),
                    filled_size=float(filled_order.filled_size),
                    confidence=signal_score.confidence.name,
                    latency_ms=latency_ms,
                )

                # 记录审计日志（关键交易操作）
                audit_logger.info(
                    "order_executed",
                    order_id=filled_order.id,
                    symbol=market_data.symbol,
                    side=side.name,
                    order_type="SHALLOW_MAKER",
                    size=float(order_size),
                    price=float(order_price),
                    filled_size=float(filled_order.filled_size),
                    status=filled_order.status.name,
                    signal_value=signal_score.value,
                    signal_confidence=signal_score.confidence.name,
                    latency_ms=latency_ms,
                    tick_offset=float(self.tick_offset),
                    post_only=self.use_post_only,
                )

                return filled_order
            else:
                # 超时未成交
                logger.warning(
                    "shallow_maker_order_timeout_cancelled",
                    symbol=market_data.symbol,
                    order_id=order.id,
                    confidence=signal_score.confidence.name,
                    timeout_seconds=timeout_seconds,
                    latency_ms=latency_ms,
                )
                return None

        except Exception as e:
            logger.error(
                "shallow_maker_execution_error",
                symbol=market_data.symbol,
                error=str(e),
                exc_info=True,
            )
            return None

    async def _wait_for_fill(
        self, order: Order, symbol: str, timeout_seconds: float, check_interval: float = 0.1
    ) -> Order | None:
        """
        等待订单成交或超时

        Args:
            order: 待成交订单
            symbol: 交易对
            timeout_seconds: 超时时间（秒）
            check_interval: 检查间隔（秒）

        Returns:
            Optional[Order]: 成交后的订单，超时则撤单并返回 None
        """
        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            # 查询订单状态
            try:
                # TODO: order.id 需要转换为 int（当前 API 接口要求）
                order_status = await self.api_client.get_order_status(
                    order_id=int(order.id) if isinstance(order.id, str) else order.id
                )

                # 检查是否成交
                if order_status and order_status.get("status") == "filled":
                    # 更新订单对象
                    order.status = OrderStatus.FILLED
                    order.filled_size = Decimal(
                        str(order_status.get("filled_size", order.size))
                    )
                    return order

                # 检查是否被拒绝或取消
                if order_status and order_status.get("status") in ["rejected", "cancelled"]:
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
            # TODO: order.id 需要转换为 int（当前 API 接口要求）
            order_id_int = int(order.id) if isinstance(order.id, str) else order.id
            await self.api_client.cancel_order(symbol=symbol, order_id=order_id_int)
            logger.info(
                "shallow_maker_order_cancelled_on_timeout",
                symbol=symbol,
                order_id=order.id,
                elapsed_seconds=timeout_seconds,
            )
        except Exception as e:
            logger.error(
                "order_cancellation_error",
                symbol=symbol,
                order_id=order.id,
                error=str(e),
            )

        return None

    def _calculate_shallow_maker_price(
        self, market_data: MarketData, side: OrderSide
    ) -> Decimal:
        """
        计算浅被动 Maker 价格（盘口 +1 tick）

        策略：
            - 买入：best_bid + 1 tick（排队靠前，提高成交概率）
            - 卖出：best_ask - 1 tick（排队靠前，提高成交概率）

        Args:
            market_data: 市场数据
            side: 订单方向

        Returns:
            Decimal: 浅被动 Maker 价格
        """
        if side == OrderSide.BUY:
            # 买入：盘口买价 + 1 tick（比贴盘口更激进，但仍是 Maker）
            best_bid = market_data.bids[0]
            price = best_bid.price + self.tick_offset
        else:
            # 卖出：盘口卖价 - 1 tick（比贴盘口更激进，但仍是 Maker）
            best_ask = market_data.asks[0]
            price = best_ask.price - self.tick_offset

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
        return signal_score.confidence in [
            ConfidenceLevel.HIGH,
            ConfidenceLevel.MEDIUM,
        ]

    def __repr__(self) -> str:
        return (
            f"ShallowMakerExecutor(default_size={self.default_size}, "
            f"timeout_high={self.timeout_high}, timeout_medium={self.timeout_medium}, "
            f"tick_offset={self.tick_offset}, use_post_only={self.use_post_only})"
        )
