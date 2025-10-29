"""Hyperliquid API 客户端封装

封装 hyperliquid-python-sdk 的 Exchange 类，提供统一的 API 接口。
仅支持 mainnet。
"""

import os
from decimal import Decimal
from typing import Any, cast

import structlog
from hyperliquid.exchange import Exchange as HyperliquidExchange
from hyperliquid.utils import constants

from src.core.types import OrderSide, OrderType

logger = structlog.get_logger()


class HyperliquidAPIClient:
    """Hyperliquid API 客户端（仅 mainnet）"""

    def __init__(
        self,
        wallet_address: str,
        private_key: str,
    ):
        """
        初始化 API 客户端

        Args:
            wallet_address: 钱包地址
            private_key: 私钥
        """
        self.wallet_address = wallet_address

        # 固定使用 mainnet
        base_url = constants.MAINNET_API_URL
        logger.info("initialized_hyperliquid_client", network="mainnet")

        # 初始化 SDK Exchange 对象
        self.exchange = HyperliquidExchange(
            wallet=wallet_address,
            secret_key=private_key,
            base_url=base_url,
        )

        self._order_count = 0

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        size: Decimal,
        price: Decimal | None = None,
        order_type: OrderType = OrderType.IOC,
    ) -> dict[str, Any]:
        """
        提交订单

        Args:
            symbol: 交易对（如 "BTC"）
            side: 订单方向
            size: 数量
            price: 价格（None 表示市价单）
            order_type: 订单类型（默认 IOC）

        Returns:
            dict: 订单响应

        Raises:
            Exception: 订单提交失败
        """
        # 转换参数
        is_buy = side == OrderSide.BUY

        # 构造订单类型参数
        if order_type == OrderType.IOC:
            order_type_dict = {"limit": {"tif": "Ioc"}}
        elif order_type == OrderType.LIMIT:
            order_type_dict = {"limit": {"tif": "Gtc"}}
        else:
            raise ValueError(f"Unsupported order type: {order_type}")

        logger.info(
            "placing_order",
            symbol=symbol,
            side=side.value,
            size=float(size),
            price=float(price) if price else None,
            order_type=order_type.value,
        )

        try:
            # 调用 SDK 提交订单
            result = self.exchange.order(
                coin=symbol,
                is_buy=is_buy,
                sz=float(size),
                limit_px=float(price) if price else None,
                order_type=order_type_dict,
            )

            # 检查响应状态
            if result.get("status") != "ok":
                logger.error("order_submission_failed", result=result)
                raise Exception(f"Order submission failed: {result}")

            self._order_count += 1

            logger.info(
                "order_submitted_successfully",
                order_id=result.get("response", {})
                .get("data", {})
                .get("statuses", [{}])[0]
                .get("resting", {})
                .get("oid"),
                result=result,
            )

            return cast(dict[str, Any], result)

        except Exception as e:
            logger.error("order_submission_error", error=str(e), exc_info=True)
            raise

    async def cancel_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        """
        取消订单

        Args:
            symbol: 交易对
            order_id: 订单 ID

        Returns:
            dict: 取消响应
        """
        logger.info("cancelling_order", symbol=symbol, order_id=order_id)

        try:
            result = self.exchange.cancel(coin=symbol, oid=order_id)

            logger.info("order_cancelled", order_id=order_id, result=result)

            return cast(dict[str, Any], result)

        except Exception as e:
            logger.error("order_cancellation_error", order_id=order_id, error=str(e))
            raise

    async def get_order_status(self, order_id: int) -> dict[str, Any] | None:
        """
        查询订单状态

        Args:
            order_id: 订单 ID

        Returns:
            dict: 订单状态，未找到返回 None
        """
        try:
            # SDK 通过 user_state 查询订单
            user_state = self.exchange.info.user_state(self.wallet_address)

            # 从 open_orders 中查找
            open_orders = user_state.get("assetPositions", [])
            for position in open_orders:
                orders = position.get("position", {}).get("openOrders", [])
                for order in orders:
                    if order.get("oid") == order_id:
                        return cast(dict[str, Any], order)

            return None

        except Exception as e:
            logger.error("get_order_status_error", order_id=order_id, error=str(e))
            return None

    async def get_account_state(self) -> dict[str, Any]:
        """
        获取账户状态

        Returns:
            dict: 账户状态（余额、持仓等）
        """
        try:
            user_state = self.exchange.info.user_state(self.wallet_address)
            return cast(dict[str, Any], user_state)

        except Exception as e:
            logger.error("get_account_state_error", error=str(e))
            raise

    def get_api_health(self) -> bool:
        """
        检查 API 健康度

        Returns:
            bool: API 是否健康
        """
        try:
            # 尝试获取账户状态
            self.exchange.info.user_state(self.wallet_address)
            return True
        except Exception as e:
            logger.error("api_health_check_failed", error=str(e))
            return False

    @property
    def order_count(self) -> int:
        """获取已提交的订单数量"""
        return self._order_count


# 工厂函数
def create_api_client_from_env() -> HyperliquidAPIClient:
    """
    从环境变量创建 API 客户端（仅 mainnet）

    环境变量：
        HYPERLIQUID_WALLET_ADDRESS: 钱包地址
        HYPERLIQUID_PRIVATE_KEY: 私钥

    Returns:
        HyperliquidAPIClient: API 客户端实例
    """
    wallet_address = os.getenv("HYPERLIQUID_WALLET_ADDRESS")
    private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY")

    if not wallet_address:
        raise ValueError("HYPERLIQUID_WALLET_ADDRESS not set")
    if not private_key:
        raise ValueError("HYPERLIQUID_PRIVATE_KEY not set")

    return HyperliquidAPIClient(
        wallet_address=wallet_address,
        private_key=private_key,
    )
