"""Hyperliquid WebSocket 客户端封装

封装 hyperliquid-python-sdk 的 WebSocket 功能，提供订单簿和成交数据订阅。
仅支持 mainnet。
"""

from collections.abc import Callable
from typing import Any

import structlog
from hyperliquid.info import Info
from hyperliquid.utils import constants

logger = structlog.get_logger()


class HyperliquidWebSocket:
    """Hyperliquid WebSocket 客户端（仅 mainnet）"""

    def __init__(self):
        """初始化 WebSocket 客户端"""
        # 固定使用 mainnet
        base_url = constants.MAINNET_API_URL
        logger.info("initialized_websocket_client", network="mainnet")

        # 初始化 SDK Info 对象（包含 WebSocket 功能）
        self.info = Info(base_url=base_url, skip_ws=False)

        self._subscriptions: dict[str, Any] = {}
        self._connected = False

    async def connect(self) -> None:
        """
        建立 WebSocket 连接

        注意：SDK 自动管理连接，无需显式连接
        """
        logger.info("websocket_ready")
        self._connected = True

    async def subscribe_l2_book(
        self, symbol: str, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        """
        订阅 L2 订单簿数据

        Args:
            symbol: 交易对（如 "BTC"）
            callback: 数据回调函数

        订单簿数据格式：
        {
            "coin": "BTC",
            "levels": [
                [{"px": "50000.0", "sz": "1.5", "n": 3}],  # bids
                [{"px": "50001.0", "sz": "2.0", "n": 2}]   # asks
            ],
            "time": 1234567890
        }
        """
        logger.info("subscribing_l2_book", symbol=symbol)

        try:
            subscription = {"type": "l2Book", "coin": symbol}

            # 包装回调函数以添加日志
            def wrapped_callback(data: dict[str, Any]) -> None:
                try:
                    callback(data)
                except Exception as e:
                    logger.error(
                        "l2_book_callback_error", symbol=symbol, error=str(e), exc_info=True
                    )

            # 订阅
            self.info.subscribe(subscription, wrapped_callback)

            self._subscriptions[f"l2book_{symbol}"] = {
                "subscription": subscription,
                "callback": callback,
            }

            logger.info("l2_book_subscribed", symbol=symbol)

        except Exception as e:
            logger.error("l2_book_subscription_error", symbol=symbol, error=str(e))
            raise

    async def subscribe_trades(
        self, symbol: str, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        """
        订阅成交数据

        Args:
            symbol: 交易对（如 "BTC"）
            callback: 数据回调函数

        成交数据格式：
        {
            "coin": "BTC",
            "time": 1234567890,
            "trades": [
                {
                    "px": "50000.0",
                    "sz": "0.5",
                    "side": "B",  # B=买入，A=卖出
                    "time": 1234567890,
                    "hash": "0x..."
                }
            ]
        }
        """
        logger.info("subscribing_trades", symbol=symbol)

        try:
            subscription = {"type": "trades", "coin": symbol}

            # 包装回调函数以添加日志
            def wrapped_callback(data: dict[str, Any]) -> None:
                try:
                    callback(data)
                except Exception as e:
                    logger.error(
                        "trades_callback_error", symbol=symbol, error=str(e), exc_info=True
                    )

            # 订阅
            self.info.subscribe(subscription, wrapped_callback)

            self._subscriptions[f"trades_{symbol}"] = {
                "subscription": subscription,
                "callback": callback,
            }

            logger.info("trades_subscribed", symbol=symbol)

        except Exception as e:
            logger.error("trades_subscription_error", symbol=symbol, error=str(e))
            raise

    async def subscribe_all_mids(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """
        订阅所有交易对的中间价

        Args:
            callback: 数据回调函数

        数据格式：
        {
            "mids": {
                "BTC": "50000.5",
                "ETH": "3000.2",
                ...
            }
        }
        """
        logger.info("subscribing_all_mids")

        try:
            subscription = {"type": "allMids"}

            def wrapped_callback(data: dict[str, Any]) -> None:
                try:
                    callback(data)
                except Exception as e:
                    logger.error("all_mids_callback_error", error=str(e), exc_info=True)

            self.info.subscribe(subscription, wrapped_callback)

            self._subscriptions["all_mids"] = {
                "subscription": subscription,
                "callback": callback,
            }

            logger.info("all_mids_subscribed")

        except Exception as e:
            logger.error("all_mids_subscription_error", error=str(e))
            raise

    async def unsubscribe(self, subscription_key: str) -> None:
        """
        取消订阅

        Args:
            subscription_key: 订阅键（如 "l2book_BTC"）
        """
        if subscription_key in self._subscriptions:
            logger.info("unsubscribing", key=subscription_key)
            # SDK 会自动清理订阅
            del self._subscriptions[subscription_key]
            logger.info("unsubscribed", key=subscription_key)
        else:
            logger.warning("subscription_not_found", key=subscription_key)

    async def close(self) -> None:
        """关闭 WebSocket 连接"""
        logger.info("closing_websocket")

        # 取消所有订阅
        for key in list(self._subscriptions.keys()):
            await self.unsubscribe(key)

        # 关闭底层 WebSocket 连接
        try:
            if hasattr(self.info, 'ws') and self.info.ws:
                await self.info.ws.close()
        except Exception as e:
            logger.warning("websocket_close_warning", error=str(e))

        self._connected = False
        logger.info("websocket_closed")

    @property
    def connected(self) -> bool:
        """WebSocket 是否已连接"""
        return self._connected

    @property
    def subscription_count(self) -> int:
        """当前订阅数量"""
        return len(self._subscriptions)


# 工厂函数
def create_websocket_from_env() -> HyperliquidWebSocket:
    """
    从环境变量创建 WebSocket 客户端（仅 mainnet）

    Returns:
        HyperliquidWebSocket: WebSocket 客户端实例
    """
    return HyperliquidWebSocket()
