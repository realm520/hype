"""Impact 信号

成交冲击信号，分析近期成交对价格的冲击方向。
"""

import time
from decimal import Decimal

import structlog

from src.core.types import MarketData, OrderSide, Trade
from src.signals.base import BaseSignal

logger = structlog.get_logger()


class ImpactSignal(BaseSignal):
    """Impact 信号

    计算时间窗口内主动成交的冲击方向，反映市场压力。

    公式：
        BuyVolume = 买入成交量之和
        SellVolume = 卖出成交量之和
        Impact = (BuyVolume - SellVolume) / (BuyVolume + SellVolume)

    返回值：
        - 正值：买方冲击强（看涨）
        - 负值：卖方冲击强（看跌）
        - 范围：[-1, 1]

    解释：
        主动买入（Taker Buy）会推高价格，主动卖出（Taker Sell）会压低价格。
        统计近期成交方向和量，可以预测短期价格趋势。
    """

    def __init__(self, window_ms: int = 100, weight: float = 0.3):
        """
        初始化 Impact 信号

        Args:
            window_ms: 统计窗口（毫秒，默认 100ms）
            weight: 信号权重（默认 0.3）
        """
        super().__init__(weight)
        self.window_ms = window_ms

        logger.info(
            "impact_signal_initialized",
            window_ms=window_ms,
            weight=weight,
        )

    def calculate(self, market_data: MarketData) -> float:
        """
        计算 Impact 信号值

        Args:
            market_data: 市场数据

        Returns:
            float: Impact 信号值（-1 到 1）
        """
        start_time = time.time()

        try:
            # 检查成交数据
            if not market_data.trades:
                logger.debug(
                    "impact_no_trades",
                    symbol=market_data.symbol,
                )
                return 0.0

            # 过滤时间窗口内的成交
            current_time = market_data.timestamp
            window_start = current_time - self.window_ms
            recent_trades = self._filter_trades(market_data.trades, window_start)

            if not recent_trades:
                logger.debug(
                    "impact_no_recent_trades",
                    symbol=market_data.symbol,
                    window_ms=self.window_ms,
                )
                return 0.0

            # 计算买卖成交量
            buy_volume, sell_volume = self._calculate_volumes(recent_trades)

            # 处理零总量情况
            total_volume = buy_volume + sell_volume
            if total_volume == 0:
                logger.warning(
                    "impact_zero_volume",
                    symbol=market_data.symbol,
                    buy_volume=buy_volume,
                    sell_volume=sell_volume,
                )
                return 0.0

            # 计算 Impact
            impact_value = float((buy_volume - sell_volume) / total_volume)

            # 归一化到 [-1, 1]
            impact_value = self._normalize(impact_value)

            # 保存结果
            self._last_value = impact_value

            # 监控性能
            latency_ms = (time.time() - start_time) * 1000
            if latency_ms > 1.0:
                logger.warning(
                    "impact_calculation_slow",
                    symbol=market_data.symbol,
                    latency_ms=latency_ms,
                )

            logger.debug(
                "impact_calculated",
                symbol=market_data.symbol,
                value=impact_value,
                buy_volume=float(buy_volume),
                sell_volume=float(sell_volume),
                trades_count=len(recent_trades),
                latency_ms=latency_ms,
            )

            return impact_value

        except Exception as e:
            logger.error(
                "impact_calculation_error",
                symbol=market_data.symbol,
                error=str(e),
                exc_info=True,
            )
            return 0.0

    def _filter_trades(self, trades: list[Trade], window_start: int) -> list[Trade]:
        """
        过滤时间窗口内的成交

        Args:
            trades: 成交列表
            window_start: 窗口起始时间（Unix 毫秒）

        Returns:
            List[Trade]: 窗口内的成交
        """
        return [trade for trade in trades if trade.timestamp >= window_start]

    def _calculate_volumes(self, trades: list[Trade]) -> tuple[Decimal, Decimal]:
        """
        计算买卖成交量

        Args:
            trades: 成交列表

        Returns:
            tuple[Decimal, Decimal]: (买入量, 卖出量)
        """
        buy_volume = Decimal("0")
        sell_volume = Decimal("0")

        for trade in trades:
            if trade.side == OrderSide.BUY:
                buy_volume += Decimal(str(trade.size))
            else:
                sell_volume += Decimal(str(trade.size))

        return buy_volume, sell_volume

    def validate(self) -> bool:
        """
        验证信号配置

        Returns:
            bool: 配置是否有效
        """
        if self.window_ms <= 0:
            logger.error("impact_invalid_window", window_ms=self.window_ms)
            return False

        if self.weight < 0 or self.weight > 1:
            logger.error("impact_invalid_weight", weight=self.weight)
            return False

        return True

    def __repr__(self) -> str:
        return f"ImpactSignal(window_ms={self.window_ms}, weight={self.weight})"
