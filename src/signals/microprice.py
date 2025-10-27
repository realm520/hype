"""Microprice 信号

微观价格信号，反映流动性不对称导致的价格压力。
"""

import time
from decimal import Decimal

import structlog

from src.core.types import MarketData
from src.signals.base import BaseSignal

logger = structlog.get_logger()


class MicropriceSignal(BaseSignal):
    """Microprice 信号

    计算微观价格相对于中间价的偏离，反映流动性不对称。

    公式：
        Microprice = (BestBid * AskSize + BestAsk * BidSize) / (BidSize + AskSize)
        Signal = (Microprice - MidPrice) / MidPrice

    返回值：
        - 正值：微观价格高于中间价（买盘流动性强）
        - 负值：微观价格低于中间价（卖盘流动性强）
        - 范围：[-1, 1]（归一化后）

    解释：
        微观价格是考虑了双边流动性的"真实"价格。如果买盘流动性强（BidSize大），
        则微观价格会偏向卖方最优价；反之偏向买方最优价。
    """

    def __init__(self, weight: float = 0.3, scale_factor: float = 10000.0):
        """
        初始化 Microprice 信号

        Args:
            weight: 信号权重（默认 0.3）
            scale_factor: 缩放因子，用于将小的价格偏离放大到 [-1, 1] 范围
                         默认 10000 意味着 0.01% 的偏离会映射到 0.1 的信号值
        """
        super().__init__(weight)
        self.scale_factor = scale_factor

        logger.info(
            "microprice_signal_initialized",
            weight=weight,
            scale_factor=scale_factor,
        )

    def calculate(self, market_data: MarketData) -> float:
        """
        计算 Microprice 信号值

        Args:
            market_data: 市场数据

        Returns:
            float: Microprice 信号值（-1 到 1）
        """
        start_time = time.time()

        try:
            # 检查数据有效性
            if not market_data.bids or not market_data.asks:
                logger.warning(
                    "microprice_empty_orderbook",
                    symbol=market_data.symbol,
                    has_bids=bool(market_data.bids),
                    has_asks=bool(market_data.asks),
                )
                return 0.0

            # 获取最优买卖价和量
            best_bid = market_data.bids[0]
            best_ask = market_data.asks[0]

            # 计算微观价格
            # Microprice = (BestBid * AskSize + BestAsk * BidSize) / (BidSize + AskSize)
            bid_size = best_bid.size
            ask_size = best_ask.size
            total_size = bid_size + ask_size

            if total_size == 0:
                logger.warning(
                    "microprice_zero_size",
                    symbol=market_data.symbol,
                    bid_size=bid_size,
                    ask_size=ask_size,
                )
                return 0.0

            microprice = (
                best_bid.price * ask_size + best_ask.price * bid_size
            ) / total_size

            # 获取中间价
            mid_price = market_data.mid_price
            if mid_price == 0:
                logger.warning("microprice_zero_midprice", symbol=market_data.symbol)
                return 0.0

            # 计算相对偏离
            # Signal = (Microprice - MidPrice) / MidPrice
            deviation = (microprice - mid_price) / mid_price

            # 放大并归一化
            # 乘以 scale_factor 使得小的偏离也能产生有意义的信号
            signal_value = float(deviation * Decimal(str(self.scale_factor)))
            signal_value = self._normalize(signal_value)

            # 保存结果
            self._last_value = signal_value

            # 监控性能
            latency_ms = (time.time() - start_time) * 1000
            if latency_ms > 1.0:
                logger.warning(
                    "microprice_calculation_slow",
                    symbol=market_data.symbol,
                    latency_ms=latency_ms,
                )

            logger.debug(
                "microprice_calculated",
                symbol=market_data.symbol,
                value=signal_value,
                microprice=float(microprice),
                mid_price=float(mid_price),
                deviation=float(deviation),
                latency_ms=latency_ms,
            )

            return signal_value

        except Exception as e:
            logger.error(
                "microprice_calculation_error",
                symbol=market_data.symbol,
                error=str(e),
                exc_info=True,
            )
            return 0.0

    def validate(self) -> bool:
        """
        验证信号配置

        Returns:
            bool: 配置是否有效
        """
        if self.weight < 0 or self.weight > 1:
            logger.error("microprice_invalid_weight", weight=self.weight)
            return False

        if self.scale_factor <= 0:
            logger.error("microprice_invalid_scale", scale_factor=self.scale_factor)
            return False

        return True

    def __repr__(self) -> str:
        return (
            f"MicropriceSignal(weight={self.weight}, "
            f"scale_factor={self.scale_factor})"
        )
