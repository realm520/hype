"""市场数据管理器

统一管理订单簿和成交数据，提供给信号引擎使用。
"""

from collections import deque
from collections.abc import Callable
from decimal import Decimal

import structlog

from src.core.orderbook import OrderBook
from src.core.types import MarketData, OrderSide, Trade
from src.hyperliquid.websocket_client import HyperliquidWebSocket

logger = structlog.get_logger()


class MarketDataManager:
    """市场数据管理器"""

    def __init__(
        self, ws_client: HyperliquidWebSocket, max_trades_history: int = 1000
    ):
        """
        初始化市场数据管理器

        Args:
            ws_client: WebSocket 客户端
            max_trades_history: 最大成交历史记录数
        """
        self.ws_client = ws_client
        self.max_trades_history = max_trades_history

        self._orderbooks: dict[str, OrderBook] = {}
        self._trades: dict[str, deque] = {}  # symbol -> deque of trades
        self._started = False

        logger.info("market_data_manager_initialized")

    async def start(self, symbols: list[str], orderbook_levels: int = 10) -> None:
        """
        启动数据管理器，订阅指定交易对

        Args:
            symbols: 交易对列表（如 ["BTC", "ETH"]）
            orderbook_levels: 订单簿档位数
        """
        logger.info("starting_market_data_manager", symbols=symbols)

        # 连接 WebSocket
        await self.ws_client.connect()

        # 为每个交易对创建订单簿和订阅
        for symbol in symbols:
            # 创建订单簿
            self._orderbooks[symbol] = OrderBook(symbol, levels=orderbook_levels)
            self._trades[symbol] = deque(maxlen=self.max_trades_history)

            # 订阅 L2 订单簿
            await self.ws_client.subscribe_l2_book(
                symbol, self._create_l2_callback(symbol)
            )

            # 订阅成交数据
            await self.ws_client.subscribe_trades(
                symbol, self._create_trades_callback(symbol)
            )

            logger.info("subscribed_to_market_data", symbol=symbol)

        self._started = True
        logger.info("market_data_manager_started", symbols=symbols)

    def _create_l2_callback(self, symbol: str) -> Callable[[dict], None]:
        """创建 L2 订单簿回调函数"""

        def callback(data: dict) -> None:
            if symbol in self._orderbooks:
                # 提取 data 字段（WebSocket 消息格式：{channel, data}）
                l2_data = data.get("data", {})
                self._orderbooks[symbol].update(l2_data)

        return callback

    def _create_trades_callback(self, symbol: str) -> Callable[[dict], None]:
        """创建成交数据回调函数"""

        def callback(data: dict) -> None:
            if symbol not in self._trades:
                return

            # Hyperliquid SDK 的 trades 回调直接传递列表，而不是 {data: [...]}
            # 兼容处理：如果 data 是列表则直接使用，否则提取 data 字段
            if isinstance(data, list):
                trades_list = data
            else:
                trades_list = data.get("data", [])

            for trade_data in trades_list:
                trade = Trade(
                    symbol=symbol,
                    timestamp=trade_data.get("time", 0),
                    price=Decimal(str(trade_data.get("px"))),
                    size=Decimal(str(trade_data.get("sz"))),
                    side=OrderSide.BUY if trade_data.get("side") == "B" else OrderSide.SELL,
                )
                self._trades[symbol].append(trade)

        return callback

    def get_market_data(self, symbol: str) -> MarketData | None:
        """
        获取市场数据（订单簿 + 最近成交）

        Args:
            symbol: 交易对

        Returns:
            Optional[MarketData]: 市场数据，未找到返回 None
        """
        if symbol not in self._orderbooks:
            logger.warning("symbol_not_found", symbol=symbol)
            return None

        orderbook = self._orderbooks[symbol]
        if not orderbook.is_valid():
            logger.warning("orderbook_invalid", symbol=symbol)
            return None

        snapshot = orderbook.get_snapshot()

        # 获取最近 100 笔成交
        recent_trades = list(self._trades.get(symbol, []))[-100:]

        return MarketData(
            symbol=symbol,
            timestamp=snapshot.timestamp,
            bids=snapshot.bids,
            asks=snapshot.asks,
            mid_price=snapshot.mid_price,
            trades=recent_trades,
        )

    def get_orderbook(self, symbol: str) -> OrderBook | None:
        """
        获取订单簿

        Args:
            symbol: 交易对

        Returns:
            Optional[OrderBook]: 订单簿，未找到返回 None
        """
        return self._orderbooks.get(symbol)

    def get_recent_trades(self, symbol: str, n: int = 100) -> list[Trade]:
        """
        获取最近 n 笔成交

        Args:
            symbol: 交易对
            n: 成交数量

        Returns:
            List[Trade]: 成交列表
        """
        if symbol not in self._trades:
            return []

        return list(self._trades[symbol])[-n:]

    async def stop(self) -> None:
        """停止数据管理器"""
        logger.info("stopping_market_data_manager")

        await self.ws_client.close()

        self._started = False
        logger.info("market_data_manager_stopped")

    @property
    def started(self) -> bool:
        """数据管理器是否已启动"""
        return self._started

    @property
    def symbols(self) -> list[str]:
        """已订阅的交易对列表"""
        return list(self._orderbooks.keys())
