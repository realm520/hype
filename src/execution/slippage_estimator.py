"""滑点估算器

估算订单执行的预期滑点，用于风控和归因分析。
"""

from decimal import Decimal

import structlog

from src.core.types import Level, MarketData, OrderSide

logger = structlog.get_logger()


class SlippageEstimator:
    """滑点估算器

    基于订单簿深度估算订单执行滑点。

    滑点定义（统一约定）：
        - 滑点是执行成本，用基点（bps）表示
        - 滑点始终为正数，表示不利程度
        - 计算公式：
          * 买入：slippage_bps = (ExecutionPrice - ReferencePrice) / ReferencePrice * 10000
          * 卖出：slippage_bps = (ReferencePrice - ExecutionPrice) / ReferencePrice * 10000
        - 无论买卖，价格偏离越大，滑点越大

    估算方法：
        1. 模拟订单在订单簿上的执行过程
        2. 计算加权平均成交价
        3. 与参考价（最优价）比较得出滑点

    注意：
        - ReferencePrice 通常是下单时的最优价（买入为 best_ask，卖出为 best_bid）
        - 滑点为正表示实际成交价比预期差
        - 滑点为负表示实际成交价比预期好（罕见，通常是价格改善）
    """

    def __init__(self, max_slippage_bps: float = 20.0):
        """
        初始化滑点估算器

        Args:
            max_slippage_bps: 最大可接受滑点（基点，默认 20 bps = 0.2%）
        """
        self.max_slippage_bps = max_slippage_bps

        logger.info(
            "slippage_estimator_initialized",
            max_slippage_bps=max_slippage_bps,
        )

    def estimate(
        self,
        market_data: MarketData,
        side: OrderSide,
        size: Decimal,
    ) -> dict:
        """
        估算订单滑点

        Args:
            market_data: 市场数据
            side: 订单方向
            size: 订单大小

        Returns:
            dict: 滑点估算结果
                {
                    "estimated_price": 预期成交价,
                    "slippage_bps": 滑点（基点）,
                    "is_acceptable": 是否可接受,
                    "levels_consumed": 消耗的订单簿档位数,
                }
        """
        try:
            # 选择相应的订单簿边
            if side == OrderSide.BUY:
                levels = market_data.asks
                reference_price = market_data.asks[0].price if market_data.asks else Decimal("0")
            else:
                levels = market_data.bids
                reference_price = market_data.bids[0].price if market_data.bids else Decimal("0")

            if not levels or reference_price == 0:
                logger.warning(
                    "slippage_estimation_no_liquidity",
                    symbol=market_data.symbol,
                    side=side.name,
                )
                return {
                    "estimated_price": Decimal("0"),
                    "slippage_bps": float("inf"),
                    "is_acceptable": False,
                    "levels_consumed": 0,
                }

            # 模拟订单执行
            execution_result = self._simulate_execution(levels, size)

            # 计算滑点
            estimated_price = execution_result["weighted_price"]
            slippage = (estimated_price - reference_price) / reference_price

            # 买入时取正（价格越高滑点越大），卖出时取反
            if side == OrderSide.SELL:
                slippage = -slippage

            slippage_bps = float(slippage * Decimal("10000"))

            # 判断是否可接受
            is_acceptable = slippage_bps <= self.max_slippage_bps

            result = {
                "estimated_price": estimated_price,
                "slippage_bps": slippage_bps,
                "is_acceptable": is_acceptable,
                "levels_consumed": execution_result["levels_consumed"],
            }

            logger.debug(
                "slippage_estimated",
                symbol=market_data.symbol,
                side=side.name,
                size=float(size),
                estimated_price=float(estimated_price),
                slippage_bps=slippage_bps,
                is_acceptable=is_acceptable,
            )

            return result

        except Exception as e:
            logger.error(
                "slippage_estimation_error",
                symbol=market_data.symbol,
                side=side.name,
                error=str(e),
                exc_info=True,
            )
            return {
                "estimated_price": Decimal("0"),
                "slippage_bps": float("inf"),
                "is_acceptable": False,
                "levels_consumed": 0,
            }

    def _simulate_execution(self, levels: list[Level], size: Decimal) -> dict:
        """
        模拟订单在订单簿上的执行

        Args:
            levels: 订单簿档位
            size: 订单大小

        Returns:
            dict: 执行结果
                {
                    "weighted_price": 加权平均成交价,
                    "levels_consumed": 消耗的档位数,
                }
        """
        remaining_size = size
        total_cost = Decimal("0")
        filled_size = Decimal("0")
        levels_consumed = 0

        for level in levels:
            if remaining_size <= 0:
                break

            # 计算本档位可成交量
            fill_size = min(remaining_size, level.size)

            # 累计成本
            total_cost += fill_size * level.price
            filled_size += fill_size
            remaining_size -= fill_size
            levels_consumed += 1

        # 计算加权平均价
        if filled_size > 0:
            weighted_price = total_cost / filled_size
        else:
            weighted_price = Decimal("0")

        return {
            "weighted_price": weighted_price,
            "levels_consumed": levels_consumed,
        }

    def is_acceptable(self, slippage_bps: float) -> bool:
        """
        判断滑点是否可接受

        Args:
            slippage_bps: 滑点（基点）

        Returns:
            bool: 是否可接受
        """
        return slippage_bps <= self.max_slippage_bps

    def calculate_actual_slippage(
        self,
        execution_price: Decimal,
        reference_price: Decimal,
        side: OrderSide,
    ) -> float:
        """
        计算实际滑点

        Args:
            execution_price: 实际成交价
            reference_price: 参考价（通常是下单时的最优价）
            side: 订单方向

        Returns:
            float: 实际滑点（基点）

        说明：
            - 买入：execution_price > reference_price → 正滑点（不利）
            - 卖出：execution_price < reference_price → 正滑点（不利）
            - 滑点为正表示成本，为负表示价格改善（罕见）
        """
        if reference_price == 0:
            return float("inf")

        # 计算价格偏离
        price_diff = execution_price - reference_price

        # 买入：价格越高滑点越大（正）
        # 卖出：价格越低滑点越大（正），需要取反
        if side == OrderSide.SELL:
            price_diff = -price_diff

        # 转换为基点
        slippage = price_diff / reference_price
        return float(slippage * Decimal("10000"))

    def __repr__(self) -> str:
        return f"SlippageEstimator(max_slippage_bps={self.max_slippage_bps})"
