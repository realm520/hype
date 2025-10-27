"""订单簿管理器

维护实时 L2 订单簿，处理 WebSocket 推送的增量更新。
"""

import time
from decimal import Decimal
from typing import Any

import structlog

from src.core.types import Level, OrderBookSnapshot

logger = structlog.get_logger()


class OrderBook:
    """订单簿管理器"""

    def __init__(self, symbol: str, levels: int = 10):
        """
        初始化订单簿

        Args:
            symbol: 交易对（如 "BTC"）
            levels: 维护的档位数量
        """
        self.symbol = symbol
        self.levels = levels

        self._bids: list[Level] = []
        self._asks: list[Level] = []
        self._last_update_time: int = 0
        self._update_count: int = 0

        logger.info("orderbook_initialized", symbol=symbol, levels=levels)

    def update(self, l2_data: dict[str, Any]) -> None:
        """
        更新订单簿（处理 WebSocket L2 推送）

        Hyperliquid L2 数据格式：
        {
            "coin": "BTC",
            "levels": [
                [{"px": "50000.0", "sz": "1.5", "n": 3}, ...],  # bids (买盘)
                [{"px": "50001.0", "sz": "2.0", "n": 2}, ...]   # asks (卖盘)
            ],
            "time": 1234567890
        }

        Args:
            l2_data: L2 订单簿数据
        """
        start_time = time.time()

        try:
            levels_data = l2_data.get("levels", [])
            if len(levels_data) != 2:
                logger.warning("invalid_l2_data_format", data=l2_data)
                return

            # 解析 bids 和 asks
            bids_data = levels_data[0]
            asks_data = levels_data[1]

            # 更新 bids（买盘，价格从高到低）
            self._bids = [
                Level(price=Decimal(level["px"]), size=Decimal(level["sz"]))
                for level in bids_data[: self.levels]
            ]

            # 更新 asks（卖盘，价格从低到高）
            self._asks = [
                Level(price=Decimal(level["px"]), size=Decimal(level["sz"]))
                for level in asks_data[: self.levels]
            ]

            # 始终使用实时时间戳，确保延迟测量的准确性
            # Hyperliquid 的 "time" 字段可能是服务器时间，与本地执行延迟测量不一致
            self._last_update_time = int(time.time() * 1000)
            self._update_count += 1

            # 监控延迟
            latency_ms = (time.time() - start_time) * 1000
            if latency_ms > 5:  # 超过 5ms 记录警告
                logger.warning(
                    "orderbook_update_slow",
                    symbol=self.symbol,
                    latency_ms=latency_ms,
                )

        except Exception as e:
            logger.error(
                "orderbook_update_error",
                symbol=self.symbol,
                error=str(e),
                exc_info=True,
            )

    def get_snapshot(self) -> OrderBookSnapshot:
        """
        获取订单簿快照

        Returns:
            OrderBookSnapshot: 订单簿快照
        """
        mid_price = self.get_mid_price()

        return OrderBookSnapshot(
            symbol=self.symbol,
            timestamp=self._last_update_time,
            bids=self._bids.copy(),
            asks=self._asks.copy(),
            mid_price=mid_price,
        )

    def get_best_bid_ask(self) -> tuple[Level | None, Level | None]:
        """
        获取最优买卖价

        Returns:
            Tuple[Optional[Level], Optional[Level]]: (最优买价, 最优卖价)
        """
        best_bid = self._bids[0] if self._bids else None
        best_ask = self._asks[0] if self._asks else None

        return best_bid, best_ask

    def get_mid_price(self) -> Decimal:
        """
        获取中间价

        Returns:
            Decimal: 中间价，订单簿为空时返回 0
        """
        best_bid, best_ask = self.get_best_bid_ask()

        if best_bid and best_ask:
            return (best_bid.price + best_ask.price) / Decimal("2")

        return Decimal("0")

    def get_spread(self) -> Decimal:
        """
        获取买卖价差

        Returns:
            Decimal: 价差，订单簿为空时返回 0
        """
        best_bid, best_ask = self.get_best_bid_ask()

        if best_bid and best_ask:
            return best_ask.price - best_bid.price

        return Decimal("0")

    def get_spread_bps(self) -> float:
        """
        获取买卖价差（bps）

        Returns:
            float: 价差（基点）
        """
        spread = self.get_spread()
        mid_price = self.get_mid_price()

        if mid_price > 0:
            return float(spread / mid_price * Decimal("10000"))

        return 0.0

    def get_depth(self, levels: int = 5) -> dict[str, list[Level]]:
        """
        获取指定档位的订单簿深度

        Args:
            levels: 档位数量

        Returns:
            Dict[str, List[Level]]: {"bids": [...], "asks": [...]}
        """
        return {"bids": self._bids[:levels], "asks": self._asks[:levels]}

    def is_valid(self) -> bool:
        """
        检查订单簿是否有效

        Returns:
            bool: 订单簿是否有效（有买卖盘数据）
        """
        return len(self._bids) > 0 and len(self._asks) > 0

    @property
    def last_update_time(self) -> int:
        """最后更新时间（Unix 时间戳，毫秒）"""
        return self._last_update_time

    @property
    def update_count(self) -> int:
        """更新次数"""
        return self._update_count

    def __repr__(self) -> str:
        mid = self.get_mid_price()
        spread_bps = self.get_spread_bps()
        return (
            f"OrderBook(symbol={self.symbol}, mid={mid}, "
            f"spread={spread_bps:.2f}bps, updates={self._update_count})"
        )
