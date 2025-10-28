"""IOC 订单成交模拟器

基于订单簿深度真实模拟 IOC 订单的成交情况。
用于影子交易系统，不实际下单。
"""

import time
from dataclasses import dataclass
from decimal import Decimal

import structlog

from src.core.types import ExecutionResult, Level, Order, OrderBookSnapshot, OrderSide

logger = structlog.get_logger()


@dataclass
class FillSimulationResult:
    """成交模拟结果"""

    filled_size: Decimal  # 实际成交数量
    avg_fill_price: Decimal  # 加权平均成交价
    slippage: Decimal  # 相对订单价格的滑点
    slippage_bps: float  # 滑点（基点）
    levels_consumed: int  # 消耗的价格档位数
    partial_fill: bool  # 是否部分成交
    fill_percentage: float  # 成交比例 (0-100%)
    total_cost: Decimal  # 总成本（数量 × 价格）


class FillSimulator:
    """IOC 订单成交模拟器

    模拟逻辑：
    1. IOC 订单立即尝试成交，无法成交则取消
    2. 按照订单簿从最优价格开始逐档消耗
    3. 考虑每档的实际流动性限制
    4. 计算加权平均成交价和滑点
    5. 返回详细的成交结果
    """

    def __init__(self, max_slippage_bps: float = 50.0):
        """
        初始化成交模拟器

        Args:
            max_slippage_bps: 最大可接受滑点（基点），超过则部分成交
        """
        self.max_slippage_bps = max_slippage_bps
        logger.info("fill_simulator_initialized", max_slippage_bps=max_slippage_bps)

    def simulate_ioc_fill(
        self, order: Order, orderbook: OrderBookSnapshot
    ) -> FillSimulationResult | None:
        """
        模拟 IOC 订单成交

        Args:
            order: 订单对象
            orderbook: 订单簿快照

        Returns:
            Optional[FillSimulationResult]: 成交结果，无法成交返回 None

        成交逻辑：
        - 买单：从 ask 盘最优价开始逐档消耗
        - 卖单：从 bid 盘最优价开始逐档消耗
        - 如果滑点超过阈值，停止成交
        """
        try:
            if order.side == OrderSide.BUY:
                levels = orderbook.asks
                reference_price = (
                    orderbook.asks[0].price if orderbook.asks else Decimal("0")
                )
            else:
                levels = orderbook.bids
                reference_price = (
                    orderbook.bids[0].price if orderbook.bids else Decimal("0")
                )

            if not levels or reference_price == Decimal("0"):
                logger.warning(
                    "no_liquidity",
                    side=order.side.value,
                    symbol=order.symbol,
                )
                return None

            # 逐档消耗订单簿
            result = self._consume_orderbook(order, levels, reference_price)

            if result is None or result.filled_size == Decimal("0"):
                logger.info(
                    "fill_simulation_no_fill",
                    order_id=order.id,
                    symbol=order.symbol,
                    side=order.side.value,
                )
                return None

            logger.info(
                "fill_simulation_success",
                order_id=order.id,
                symbol=order.symbol,
                side=order.side.value,
                filled_size=float(result.filled_size),
                avg_price=float(result.avg_fill_price),
                slippage_bps=result.slippage_bps,
                partial_fill=result.partial_fill,
            )

            return result

        except Exception as e:
            logger.error(
                "fill_simulation_error",
                order_id=order.id,
                error=str(e),
                exc_info=True,
            )
            return None

    def _consume_orderbook(
        self, order: Order, levels: list[Level], reference_price: Decimal
    ) -> FillSimulationResult | None:
        """
        逐档消耗订单簿

        Args:
            order: 订单对象
            levels: 订单簿档位列表（买单用 asks，卖单用 bids）
            reference_price: 参考价格（用于计算滑点）

        Returns:
            Optional[FillSimulationResult]: 成交结果
        """
        remaining_size = order.size
        filled_value = Decimal("0")  # 累计成交金额
        filled_size = Decimal("0")  # 累计成交数量
        levels_consumed = 0

        for level in levels:
            if remaining_size <= Decimal("0"):
                break

            # 当前档位可成交量
            available_size = min(level.size, remaining_size)

            # 计算当前档位的滑点
            current_slippage_bps = self._calculate_slippage_bps(
                level.price, reference_price, order.side
            )

            # 如果滑点超过阈值，停止成交
            if current_slippage_bps > self.max_slippage_bps:
                logger.debug(
                    "slippage_threshold_exceeded",
                    order_id=order.id,
                    current_slippage_bps=current_slippage_bps,
                    max_slippage_bps=self.max_slippage_bps,
                )
                break

            # 成交
            filled_size += available_size
            filled_value += available_size * level.price
            remaining_size -= available_size
            levels_consumed += 1

        if filled_size == Decimal("0"):
            return None

        # 计算加权平均成交价
        avg_fill_price = filled_value / filled_size

        # 计算滑点
        slippage = avg_fill_price - reference_price
        if order.side == OrderSide.SELL:
            slippage = reference_price - avg_fill_price  # 卖单反向

        slippage_bps = float(abs(slippage) / reference_price * Decimal("10000"))

        # 计算成交比例
        fill_percentage = float(filled_size / order.size * Decimal("100"))

        # 判断是否部分成交
        partial_fill = filled_size < order.size

        return FillSimulationResult(
            filled_size=filled_size,
            avg_fill_price=avg_fill_price,
            slippage=slippage,
            slippage_bps=slippage_bps,
            levels_consumed=levels_consumed,
            partial_fill=partial_fill,
            fill_percentage=fill_percentage,
            total_cost=filled_value,
        )

    def _calculate_slippage_bps(
        self, current_price: Decimal, reference_price: Decimal, side: OrderSide
    ) -> float:
        """
        计算相对参考价格的滑点（基点）

        Args:
            current_price: 当前成交价
            reference_price: 参考价格（最优价）
            side: 订单方向

        Returns:
            float: 滑点（基点）
        """
        if reference_price == Decimal("0"):
            return 0.0

        if side == OrderSide.BUY:
            # 买单：价格越高滑点越大
            slippage = (current_price - reference_price) / reference_price
        else:
            # 卖单：价格越低滑点越大
            slippage = (reference_price - current_price) / reference_price

        return float(slippage * Decimal("10000"))

    def convert_to_execution_result(
        self, order: Order, fill_result: FillSimulationResult, timestamp: int
    ) -> ExecutionResult:
        """
        将成交模拟结果转换为执行结果

        Args:
            order: 原始订单
            fill_result: 成交模拟结果
            timestamp: 时间戳

        Returns:
            ExecutionResult: 执行结果对象
        """
        return ExecutionResult(
            order_id=order.id,
            fill_price=fill_result.avg_fill_price,
            fill_size=fill_result.filled_size,
            expected_price=order.price,
            slippage=fill_result.slippage,
            timestamp=timestamp,
        )

    def simulate_limit_fill(
        self,
        market_data,  # MarketData type
        side: OrderSide,
        size: Decimal,
        price: Decimal,
    ) -> "FillSimulationResult":
        """
        模拟限价单成交（Maker 费率 +0.015%）

        限价单特点：
            - 贴盘口价格
            - 成为 Maker（提供流动性）
            - 费率 +0.015%（1.5 bps 正费率，不是 rebate）
            - 无滑点（价格精确）

        Args:
            market_data: 市场数据
            side: 订单方向
            size: 订单大小
            price: 限价单价格

        Returns:
            FillSimulationResult: 成交结果
        """
        # 限价单成交：全部成交，无滑点，Maker 费率
        filled_size = size
        avg_fill_price = price
        slippage = Decimal("0")  # 限价单无滑点
        slippage_bps = 0.0
        levels_consumed = 1  # 单一价格档位
        partial_fill = False  # 假设全部成交
        fill_percentage = 100.0
        total_cost = filled_size * avg_fill_price

        logger.info(
            "limit_fill_simulated",
            symbol=market_data.symbol,
            side=side.name,
            filled_size=float(filled_size),
            price=float(price),
            fee_bps=0.15,  # Maker 费率 1.5 bps（正费率）
        )

        result = FillSimulationResult(
            filled_size=filled_size,
            avg_fill_price=avg_fill_price,
            slippage=slippage,
            slippage_bps=slippage_bps,
            levels_consumed=levels_consumed,
            partial_fill=partial_fill,
            fill_percentage=fill_percentage,
            total_cost=total_cost,
        )

        # 添加 to_execution_result 方法引用
        def to_execution_result() -> ExecutionResult:
            return ExecutionResult(
                order_id="shadow_limit",
                fill_price=avg_fill_price,
                fill_size=filled_size,
                expected_price=price,
                slippage=slippage,
                timestamp=int(time.time() * 1000),
            )

        result.to_execution_result = to_execution_result
        return result

    def __repr__(self) -> str:
        return f"FillSimulator(max_slippage_bps={self.max_slippage_bps})"
