"""IOC 订单执行器

Week 1 核心执行策略：仅执行高置信度信号的 IOC 订单。
"""

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


class IOCExecutor:
    """IOC 订单执行器

    Week 1 策略：
        - HIGH 置信度 → 执行 IOC
        - MEDIUM/LOW 置信度 → 跳过

    执行逻辑：
        1. 信号 > theta_1 → 买入
        2. 信号 < -theta_1 → 卖出
        3. |信号| ≤ theta_1 → 不执行
    """

    def __init__(
        self,
        api_client: HyperliquidAPIClient,
        default_size: Decimal = Decimal("0.01"),
        price_adjustment_bps: float = 10.0,
    ):
        """
        初始化 IOC 执行器

        Args:
            api_client: Hyperliquid API 客户端
            default_size: 默认订单大小（默认 0.01）
            price_adjustment_bps: 价格调整（基点），用于提高成交概率
                                 买入时增加 N bps，卖出时减少 N bps
        """
        self.api_client = api_client
        self.default_size = default_size
        self.price_adjustment_bps = price_adjustment_bps

        logger.info(
            "ioc_executor_initialized",
            default_size=float(default_size),
            price_adjustment_bps=price_adjustment_bps,
        )

    async def execute(
        self,
        signal_score: SignalScore,
        market_data: MarketData,
        size: Decimal | None = None,
    ) -> Order | None:
        """
        根据信号评分执行 IOC 订单

        Args:
            signal_score: 信号评分
            market_data: 市场数据
            size: 订单大小（如果为 None，使用默认大小）

        Returns:
            Optional[Order]: 执行的订单，如果跳过则返回 None
        """
        start_time = time.time()

        try:
            # 检查置信度
            if signal_score.confidence != ConfidenceLevel.HIGH:
                logger.info(
                    "execution_skipped_low_confidence",
                    symbol=market_data.symbol,
                    signal_value=signal_score.value,
                    confidence=signal_score.confidence.name,
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
            order_price = self._calculate_execution_price(market_data, side)

            # 记录执行意图
            logger.info(
                "executing_ioc_order",
                symbol=market_data.symbol,
                side=side.name,
                size=float(order_size),
                price=float(order_price),
                signal_value=signal_score.value,
                confidence=signal_score.confidence.name,
            )

            # 执行 IOC 订单
            order_result = await self.api_client.place_order(
                symbol=market_data.symbol,
                side=side,
                size=order_size,
                price=order_price,
                order_type=OrderType.IOC,
            )

            # 解析订单结果
            order = self._parse_order_result(
                order_result,
                market_data.symbol,
                side,
                order_size,
                order_price,
            )

            # 监控执行延迟
            latency_ms = (time.time() - start_time) * 1000

            logger.info(
                "ioc_order_executed",
                symbol=market_data.symbol,
                order_id=order.id,
                side=side.name,
                size=float(order_size),
                price=float(order_price),
                status=order.status.name,
                latency_ms=latency_ms,
            )

            # 记录审计日志（关键交易操作）
            audit_logger.info(
                "order_executed",
                order_id=order.id,
                symbol=market_data.symbol,
                side=side.name,
                order_type="IOC",
                size=float(order_size),
                price=float(order_price),
                status=order.status.name,
                signal_value=signal_score.value,
                signal_confidence=signal_score.confidence.name,
                latency_ms=latency_ms,
            )

            # 检查延迟警告
            if latency_ms > 100:
                logger.warning(
                    "execution_latency_high",
                    symbol=market_data.symbol,
                    latency_ms=latency_ms,
                    target_ms=100,
                )

            return order

        except Exception as e:
            logger.error(
                "ioc_execution_error",
                symbol=market_data.symbol,
                error=str(e),
                exc_info=True,
            )
            return None

    def _calculate_execution_price(
        self, market_data: MarketData, side: OrderSide
    ) -> Decimal:
        """
        计算执行价格

        策略：
            - 买入：在最优卖价基础上增加 N bps（更激进，提高成交概率）
            - 卖出：在最优买价基础上减少 N bps

        Args:
            market_data: 市场数据
            side: 订单方向

        Returns:
            Decimal: 执行价格
        """
        adjustment_factor = Decimal(str(self.price_adjustment_bps / 10000))

        if side == OrderSide.BUY:
            # 买入：基于最优卖价，略微增加
            best_ask = market_data.asks[0]
            price = best_ask.price * (Decimal("1") + adjustment_factor)
        else:
            # 卖出：基于最优买价，略微减少
            best_bid = market_data.bids[0]
            price = best_bid.price * (Decimal("1") - adjustment_factor)

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
            order_status = OrderStatus.FILLED
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
            order_type=OrderType.IOC,
            price=price,
            size=size,
            filled_size=Decimal(str(first_status.get("filled", "0"))),
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
        return signal_score.confidence == ConfidenceLevel.HIGH

    def __repr__(self) -> str:
        return (
            f"IOCExecutor(default_size={self.default_size}, "
            f"price_adjustment_bps={self.price_adjustment_bps})"
        )
