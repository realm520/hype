"""影子 IOC 订单执行器

用于影子交易系统，模拟 IOC 订单执行但不实际下单。
复用 IOCExecutor 的决策逻辑，但使用 FillSimulator 模拟成交。
"""

import time
import uuid
from dataclasses import dataclass
from decimal import Decimal

import structlog

from src.core.types import (
    ConfidenceLevel,
    ExecutionResult,
    MarketData,
    Order,
    OrderBookSnapshot,
    OrderSide,
    OrderStatus,
    OrderType,
    SignalScore,
)
from src.execution.fill_simulator import FillSimulationResult, FillSimulator

logger = structlog.get_logger()


@dataclass
class ShadowExecutionRecord:
    """影子执行记录（包含完整决策链）"""

    order: Order
    fill_result: FillSimulationResult | None
    execution_result: ExecutionResult | None
    signal_timestamp: int
    decision_timestamp: int
    execution_timestamp: int
    signal_latency_ms: float
    decision_latency_ms: float
    total_latency_ms: float
    skipped: bool
    skip_reason: str | None = None


class ShadowIOCExecutor:
    """影子 IOC 订单执行器

    Week 1 策略（与 IOCExecutor 一致）：
        - HIGH 置信度 → 执行 IOC
        - MEDIUM/LOW 置信度 → 跳过

    执行逻辑（模拟）：
        1. 信号 > theta_1 → 模拟买入
        2. 信号 < -theta_1 → 模拟卖出
        3. |信号| ≤ theta_1 → 跳过
        4. 使用 FillSimulator 基于订单簿深度模拟成交
    """

    def __init__(
        self,
        fill_simulator: FillSimulator,
        default_size: Decimal = Decimal("0.01"),
        price_adjustment_bps: float = 10.0,
    ):
        """
        初始化影子 IOC 执行器

        Args:
            fill_simulator: 成交模拟器
            default_size: 默认订单大小（默认 0.01）
            price_adjustment_bps: 价格调整（基点），与真实执行器一致
        """
        self.fill_simulator = fill_simulator
        self.default_size = default_size
        self.price_adjustment_bps = price_adjustment_bps

        logger.info(
            "shadow_executor_initialized",
            default_size=float(default_size),
            price_adjustment_bps=price_adjustment_bps,
        )

    async def execute(
        self,
        signal_score: SignalScore,
        market_data: MarketData,
        size: Decimal | None = None,
    ) -> ShadowExecutionRecord:
        """
        根据信号评分执行影子 IOC 订单

        Args:
            signal_score: 信号评分
            market_data: 市场数据
            size: 订单大小（如果为 None，使用默认大小）

        Returns:
            ShadowExecutionRecord: 影子执行记录（包含完整决策链）
        """
        signal_timestamp = signal_score.timestamp
        decision_timestamp = int(time.time() * 1000)

        # 信号延迟
        signal_latency_ms = decision_timestamp - signal_timestamp

        try:
            # 检查置信度（与 IOCExecutor 一致）
            if signal_score.confidence != ConfidenceLevel.HIGH:
                logger.info(
                    "shadow_execution_skipped_low_confidence",
                    symbol=market_data.symbol,
                    signal_value=signal_score.value,
                    confidence=signal_score.confidence.name,
                )
                return self._create_skipped_record(
                    signal_score,
                    market_data,
                    signal_timestamp,
                    decision_timestamp,
                    "low_confidence",
                )

            # 确定订单方向（与 IOCExecutor 一致）
            if signal_score.value > 0:
                side = OrderSide.BUY
            elif signal_score.value < 0:
                side = OrderSide.SELL
            else:
                logger.info(
                    "shadow_execution_skipped_zero_signal",
                    symbol=market_data.symbol,
                )
                return self._create_skipped_record(
                    signal_score,
                    market_data,
                    signal_timestamp,
                    decision_timestamp,
                    "zero_signal",
                )

            # 计算订单参数（与 IOCExecutor 一致）
            order_size = size if size is not None else self.default_size
            order_price = self._calculate_execution_price(market_data, side)

            # 创建订单对象
            order = self._create_order(
                market_data.symbol, side, order_size, order_price, decision_timestamp
            )

            # 记录执行意图
            logger.info(
                "shadow_executing_ioc_order",
                symbol=market_data.symbol,
                side=side.name,
                size=float(order_size),
                price=float(order_price),
                signal_value=signal_score.value,
                confidence=signal_score.confidence.name,
            )

            # 模拟订单成交
            execution_start = time.time()
            orderbook = self._convert_to_orderbook_snapshot(market_data)
            fill_result = self.fill_simulator.simulate_ioc_fill(order, orderbook)
            execution_timestamp = int(time.time() * 1000)

            # 决策延迟（决策 → 执行完成）
            decision_latency_ms = (time.time() - (decision_timestamp / 1000)) * 1000
            total_latency_ms = execution_timestamp - signal_timestamp

            if fill_result is None:
                logger.warning(
                    "shadow_execution_no_fill",
                    symbol=market_data.symbol,
                    order_id=order.id,
                )
                # 更新订单状态为取消
                order.status = OrderStatus.CANCELLED
                return ShadowExecutionRecord(
                    order=order,
                    fill_result=None,
                    execution_result=None,
                    signal_timestamp=signal_timestamp,
                    decision_timestamp=decision_timestamp,
                    execution_timestamp=execution_timestamp,
                    signal_latency_ms=signal_latency_ms,
                    decision_latency_ms=decision_latency_ms,
                    total_latency_ms=total_latency_ms,
                    skipped=False,
                )

            # 更新订单状态
            if fill_result.partial_fill:
                order.status = OrderStatus.PARTIAL_FILLED
            else:
                order.status = OrderStatus.FILLED

            order.filled_size = fill_result.filled_size
            order.avg_fill_price = fill_result.avg_fill_price

            # 创建执行结果
            execution_result = self.fill_simulator.convert_to_execution_result(
                order, fill_result, execution_timestamp
            )

            logger.info(
                "shadow_ioc_order_executed",
                symbol=market_data.symbol,
                order_id=order.id,
                side=side.name,
                filled_size=float(fill_result.filled_size),
                avg_price=float(fill_result.avg_fill_price),
                slippage_bps=fill_result.slippage_bps,
                partial_fill=fill_result.partial_fill,
                total_latency_ms=total_latency_ms,
            )

            # 延迟警告
            if total_latency_ms > 150:
                logger.warning(
                    "shadow_execution_latency_high",
                    symbol=market_data.symbol,
                    total_latency_ms=total_latency_ms,
                    target_ms=150,
                )

            return ShadowExecutionRecord(
                order=order,
                fill_result=fill_result,
                execution_result=execution_result,
                signal_timestamp=signal_timestamp,
                decision_timestamp=decision_timestamp,
                execution_timestamp=execution_timestamp,
                signal_latency_ms=signal_latency_ms,
                decision_latency_ms=decision_latency_ms,
                total_latency_ms=total_latency_ms,
                skipped=False,
            )

        except Exception as e:
            logger.error(
                "shadow_execution_error",
                symbol=market_data.symbol,
                error=str(e),
                exc_info=True,
            )
            # 返回错误记录
            return self._create_error_record(
                signal_score,
                market_data,
                signal_timestamp,
                decision_timestamp,
                str(e),
            )

    def _calculate_execution_price(
        self, market_data: MarketData, side: OrderSide
    ) -> Decimal:
        """
        计算执行价格（与 IOCExecutor 完全一致）

        策略：
            - 买入：在最优卖价基础上增加 N bps
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

    def _create_order(
        self,
        symbol: str,
        side: OrderSide,
        size: Decimal,
        price: Decimal,
        timestamp: int,
    ) -> Order:
        """创建订单对象"""
        return Order(
            id=f"shadow_{uuid.uuid4().hex[:8]}",
            symbol=symbol,
            side=side,
            order_type=OrderType.IOC,
            price=price,
            size=size,
            filled_size=Decimal("0"),
            status=OrderStatus.PENDING,
            created_at=timestamp,
        )

    def _convert_to_orderbook_snapshot(
        self, market_data: MarketData
    ) -> OrderBookSnapshot:
        """将 MarketData 转换为 OrderBookSnapshot"""
        return OrderBookSnapshot(
            symbol=market_data.symbol,
            timestamp=market_data.timestamp,
            bids=market_data.bids,
            asks=market_data.asks,
            mid_price=market_data.mid_price,
        )

    def _create_skipped_record(
        self,
        signal_score: SignalScore,
        market_data: MarketData,
        signal_timestamp: int,
        decision_timestamp: int,
        skip_reason: str,
    ) -> ShadowExecutionRecord:
        """创建跳过执行记录"""
        order = self._create_order(
            market_data.symbol,
            OrderSide.BUY if signal_score.value > 0 else OrderSide.SELL,
            self.default_size,
            market_data.mid_price,
            decision_timestamp,
        )
        order.status = OrderStatus.CANCELLED

        return ShadowExecutionRecord(
            order=order,
            fill_result=None,
            execution_result=None,
            signal_timestamp=signal_timestamp,
            decision_timestamp=decision_timestamp,
            execution_timestamp=decision_timestamp,
            signal_latency_ms=decision_timestamp - signal_timestamp,
            decision_latency_ms=0.0,
            total_latency_ms=decision_timestamp - signal_timestamp,
            skipped=True,
            skip_reason=skip_reason,
        )

    def _create_error_record(
        self,
        signal_score: SignalScore,
        market_data: MarketData,
        signal_timestamp: int,
        decision_timestamp: int,
        error_message: str,
    ) -> ShadowExecutionRecord:
        """创建错误记录"""
        order = self._create_order(
            market_data.symbol,
            OrderSide.BUY if signal_score.value > 0 else OrderSide.SELL,
            self.default_size,
            market_data.mid_price,
            decision_timestamp,
        )
        order.status = OrderStatus.REJECTED
        order.error_message = error_message

        execution_timestamp = int(time.time() * 1000)

        return ShadowExecutionRecord(
            order=order,
            fill_result=None,
            execution_result=None,
            signal_timestamp=signal_timestamp,
            decision_timestamp=decision_timestamp,
            execution_timestamp=execution_timestamp,
            signal_latency_ms=decision_timestamp - signal_timestamp,
            decision_latency_ms=execution_timestamp - decision_timestamp,
            total_latency_ms=execution_timestamp - signal_timestamp,
            skipped=False,
            skip_reason=f"error: {error_message}",
        )

    def should_execute(self, signal_score: SignalScore) -> bool:
        """
        判断是否应该执行订单（与 IOCExecutor 一致）

        Args:
            signal_score: 信号评分

        Returns:
            bool: 是否执行
        """
        return signal_score.confidence == ConfidenceLevel.HIGH

    def __repr__(self) -> str:
        return (
            f"ShadowIOCExecutor(default_size={self.default_size}, "
            f"price_adjustment_bps={self.price_adjustment_bps})"
        )
