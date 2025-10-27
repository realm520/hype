"""OBI 信号（Order Book Imbalance）

订单簿不平衡度信号，反映买卖盘力量对比。
"""

import time
from decimal import Decimal

import structlog

from src.core.types import Level, MarketData
from src.signals.base import BaseSignal

logger = structlog.get_logger()


class OBISignal(BaseSignal):
    """OBI 信号

    计算订单簿买卖盘不平衡度，反映市场供需力量对比。

    公式：
        OBI = (BidVolume - AskVolume) / (BidVolume + AskVolume)

    返回值：
        - 正值：买盘强于卖盘（看涨）
        - 负值：卖盘强于买盘（看跌）
        - 范围：[-1, 1]
    """

    def __init__(self, levels: int = 5, weight: float = 0.4, use_weighted: bool = True):
        """
        初始化 OBI 信号

        Args:
            levels: 使用的订单簿档位数（默认 5）
            weight: 信号权重（默认 0.4）
            use_weighted: 是否使用距离加权（默认 True，越接近最优价权重越大）
        """
        super().__init__(weight)
        self.levels = levels
        self.use_weighted = use_weighted

        logger.info(
            "obi_signal_initialized",
            levels=levels,
            weight=weight,
            use_weighted=use_weighted,
        )

    def calculate(self, market_data: MarketData) -> float:
        """
        计算 OBI 信号值

        Args:
            market_data: 市场数据

        Returns:
            float: OBI 信号值（-1 到 1）
        """
        start_time = time.time()

        try:
            # 检查数据有效性
            if not market_data.bids or not market_data.asks:
                logger.warning(
                    "obi_empty_orderbook",
                    symbol=market_data.symbol,
                    has_bids=bool(market_data.bids),
                    has_asks=bool(market_data.asks),
                )
                return 0.0

            # 计算买卖盘量
            bid_volume = self._calculate_volume(market_data.bids[: self.levels])
            ask_volume = self._calculate_volume(market_data.asks[: self.levels])

            # 处理零总量情况
            total_volume = bid_volume + ask_volume
            if total_volume == 0:
                logger.warning(
                    "obi_zero_volume",
                    symbol=market_data.symbol,
                    bid_volume=bid_volume,
                    ask_volume=ask_volume,
                )
                return 0.0

            # 计算 OBI
            obi_value = float((bid_volume - ask_volume) / total_volume)

            # 归一化到 [-1, 1]
            obi_value = self._normalize(obi_value)

            # 保存结果
            self._last_value = obi_value

            # 监控性能
            latency_ms = (time.time() - start_time) * 1000
            if latency_ms > 1.0:
                logger.warning(
                    "obi_calculation_slow",
                    symbol=market_data.symbol,
                    latency_ms=latency_ms,
                )

            logger.debug(
                "obi_calculated",
                symbol=market_data.symbol,
                value=obi_value,
                bid_volume=float(bid_volume),
                ask_volume=float(ask_volume),
                latency_ms=latency_ms,
            )

            return obi_value

        except Exception as e:
            logger.error(
                "obi_calculation_error",
                symbol=market_data.symbol,
                error=str(e),
                exc_info=True,
            )
            return 0.0

    def _calculate_volume(self, levels: list[Level]) -> Decimal:
        """
        计算订单簿档位的总量

        Args:
            levels: 订单簿档位列表

        Returns:
            Decimal: 总量（可能带距离加权）
        """
        if not levels:
            return Decimal("0")

        if not self.use_weighted:
            # 简单求和
            return sum((level.size for level in levels), Decimal("0"))

        # 距离加权：越接近最优价权重越大
        # 权重公式：weight[i] = (n - i) / sum(1..n)
        # 例如 5 档：[5/15, 4/15, 3/15, 2/15, 1/15]
        n = len(levels)
        weight_sum = sum(range(1, n + 1))

        weighted_volume = Decimal("0")
        for i, level in enumerate(levels):
            weight = Decimal(n - i) / Decimal(weight_sum)
            weighted_volume += level.size * weight

        return weighted_volume

    def validate(self) -> bool:
        """
        验证信号配置

        Returns:
            bool: 配置是否有效
        """
        if self.levels <= 0:
            logger.error("obi_invalid_levels", levels=self.levels)
            return False

        if self.weight < 0 or self.weight > 1:
            logger.error("obi_invalid_weight", weight=self.weight)
            return False

        return True

    def __repr__(self) -> str:
        return (
            f"OBISignal(levels={self.levels}, weight={self.weight}, "
            f"weighted={self.use_weighted})"
        )
