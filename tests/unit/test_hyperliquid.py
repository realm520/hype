"""Hyperliquid 集成测试

测试 HyperliquidAPIClient 和 HyperliquidWebSocket 的核心功能。
"""

import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from src.core.types import OrderSide, OrderType
from src.hyperliquid.api_client import HyperliquidAPIClient, create_api_client_from_env
from src.hyperliquid.websocket_client import HyperliquidWebSocket, create_websocket_from_env

# ==================== HyperliquidAPIClient 测试 ====================


class TestHyperliquidAPIClient:
    """测试 Hyperliquid API 客户端"""

    @pytest.fixture
    def mock_exchange(self, mocker):
        """Mock Hyperliquid Exchange SDK"""
        exchange = mocker.MagicMock()
        exchange.info = mocker.MagicMock()
        return exchange

    @pytest.fixture
    def api_client(self, mocker, mock_exchange):
        """API 客户端实例（固定 mainnet）"""
        with patch('src.hyperliquid.api_client.HyperliquidExchange', return_value=mock_exchange):
            client = HyperliquidAPIClient(
                wallet_address="0x1234567890abcdef",
                private_key="test_private_key",
            )
            client.exchange = mock_exchange
            return client

    def test_initialization_mainnet(self, mocker):
        """测试初始化（固定 mainnet）"""
        mock_exchange = mocker.MagicMock()

        with patch('src.hyperliquid.api_client.HyperliquidExchange', return_value=mock_exchange) as mock_cls:
            client = HyperliquidAPIClient(
                wallet_address="0xtest",
                private_key="key",
            )

            assert client.wallet_address == "0xtest"
            assert client.order_count == 0
            mock_cls.assert_called_once()


    @pytest.mark.asyncio
    async def test_place_order_ioc_success(self, api_client, mock_exchange):
        """测试成功提交 IOC 订单"""
        # Mock SDK 返回值
        mock_exchange.order.return_value = {
            "status": "ok",
            "response": {
                "data": {
                    "statuses": [
                        {
                            "resting": {"oid": 12345},
                        }
                    ]
                }
            },
        }

        result = await api_client.place_order(
            symbol="ETH",
            side=OrderSide.BUY,
            size=Decimal("1.5"),
            price=Decimal("3000.0"),
            order_type=OrderType.IOC,
        )

        assert result["status"] == "ok"
        assert api_client.order_count == 1

        # 验证调用参数
        mock_exchange.order.assert_called_once()
        call_kwargs = mock_exchange.order.call_args[1]
        assert call_kwargs["coin"] == "ETH"
        assert call_kwargs["is_buy"] is True
        assert call_kwargs["sz"] == 1.5
        assert call_kwargs["limit_px"] == 3000.0
        assert call_kwargs["order_type"] == {"limit": {"tif": "Ioc"}}

    @pytest.mark.asyncio
    async def test_place_order_limit(self, api_client, mock_exchange):
        """测试提交 LIMIT 订单"""
        mock_exchange.order.return_value = {
            "status": "ok",
            "response": {"data": {"statuses": [{}]}},
        }

        await api_client.place_order(
            symbol="BTC",
            side=OrderSide.SELL,
            size=Decimal("0.1"),
            price=Decimal("50000.0"),
            order_type=OrderType.LIMIT,
        )

        call_kwargs = mock_exchange.order.call_args[1]
        assert call_kwargs["order_type"] == {"limit": {"tif": "Gtc"}}

    @pytest.mark.asyncio
    async def test_place_order_unsupported_type(self, api_client):
        """测试不支持的订单类型"""

        # 创建一个新的枚举值来模拟不支持的类型
        with pytest.raises(ValueError, match="Unsupported order type"):
            await api_client.place_order(
                symbol="ETH",
                side=OrderSide.BUY,
                size=Decimal("1.0"),
                price=Decimal("3000.0"),
                order_type=OrderType.MARKET,  # 不支持
            )

    @pytest.mark.asyncio
    async def test_place_order_api_failure(self, api_client, mock_exchange):
        """测试 API 返回失败状态"""
        mock_exchange.order.return_value = {
            "status": "error",
            "error": "Insufficient funds",
        }

        with pytest.raises(Exception, match="Order submission failed"):
            await api_client.place_order(
                symbol="ETH",
                side=OrderSide.BUY,
                size=Decimal("1.0"),
                price=Decimal("3000.0"),
            )

    @pytest.mark.asyncio
    async def test_place_order_exception(self, api_client, mock_exchange):
        """测试 API 抛出异常"""
        mock_exchange.order.side_effect = Exception("Network error")

        with pytest.raises(Exception, match="Network error"):
            await api_client.place_order(
                symbol="ETH",
                side=OrderSide.BUY,
                size=Decimal("1.0"),
                price=Decimal("3000.0"),
            )

    @pytest.mark.asyncio
    async def test_cancel_order_success(self, api_client, mock_exchange):
        """测试成功取消订单"""
        mock_exchange.cancel.return_value = {
            "status": "ok",
        }

        result = await api_client.cancel_order("ETH", 12345)

        assert result["status"] == "ok"
        mock_exchange.cancel.assert_called_once_with(coin="ETH", oid=12345)

    @pytest.mark.asyncio
    async def test_cancel_order_exception(self, api_client, mock_exchange):
        """测试取消订单失败"""
        mock_exchange.cancel.side_effect = Exception("Order not found")

        with pytest.raises(Exception, match="Order not found"):
            await api_client.cancel_order("ETH", 99999)

    @pytest.mark.asyncio
    async def test_get_order_status_found(self, api_client, mock_exchange):
        """测试查询订单状态（找到）"""
        mock_exchange.info.user_state.return_value = {
            "assetPositions": [
                {
                    "position": {
                        "openOrders": [
                            {"oid": 12345, "status": "open", "size": "1.0"},
                            {"oid": 67890, "status": "filled", "size": "2.0"},
                        ]
                    }
                }
            ]
        }

        result = await api_client.get_order_status(12345)

        assert result is not None
        assert result["oid"] == 12345
        assert result["status"] == "open"

    @pytest.mark.asyncio
    async def test_get_order_status_not_found(self, api_client, mock_exchange):
        """测试查询订单状态（未找到）"""
        mock_exchange.info.user_state.return_value = {
            "assetPositions": []
        }

        result = await api_client.get_order_status(99999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_order_status_exception(self, api_client, mock_exchange):
        """测试查询订单状态异常"""
        mock_exchange.info.user_state.side_effect = Exception("API error")

        result = await api_client.get_order_status(12345)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_account_state_success(self, api_client, mock_exchange):
        """测试获取账户状态"""
        mock_state = {
            "marginSummary": {"accountValue": "10000.0"},
            "assetPositions": [],
        }
        mock_exchange.info.user_state.return_value = mock_state

        result = await api_client.get_account_state()

        assert result == mock_state
        mock_exchange.info.user_state.assert_called_once_with(api_client.wallet_address)

    @pytest.mark.asyncio
    async def test_get_account_state_exception(self, api_client, mock_exchange):
        """测试获取账户状态失败"""
        mock_exchange.info.user_state.side_effect = Exception("API error")

        with pytest.raises(Exception, match="API error"):
            await api_client.get_account_state()

    def test_get_api_health_healthy(self, api_client, mock_exchange):
        """测试 API 健康检查（健康）"""
        mock_exchange.info.user_state.return_value = {}

        is_healthy = api_client.get_api_health()

        assert is_healthy is True

    def test_get_api_health_unhealthy(self, api_client, mock_exchange):
        """测试 API 健康检查（不健康）"""
        mock_exchange.info.user_state.side_effect = Exception("Connection error")

        is_healthy = api_client.get_api_health()

        assert is_healthy is False

    def test_order_count_property(self, api_client, mock_exchange):
        """测试订单计数属性"""
        assert api_client.order_count == 0

        # 模拟提交两个订单
        api_client._order_count = 2

        assert api_client.order_count == 2

    def test_create_api_client_from_env_success(self, mocker):
        """测试从环境变量创建客户端"""
        mock_exchange = mocker.MagicMock()

        with patch.dict(os.environ, {
            'HYPERLIQUID_WALLET_ADDRESS': '0xtest_wallet',
            'HYPERLIQUID_PRIVATE_KEY': 'test_private_key',
            'ENVIRONMENT': 'mainnet',
        }):
            with patch('src.hyperliquid.api_client.HyperliquidExchange', return_value=mock_exchange):
                client = create_api_client_from_env()

                assert client.wallet_address == "0xtest_wallet"

    def test_create_api_client_from_env_missing_wallet(self):
        """测试环境变量缺失钱包地址"""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="HYPERLIQUID_WALLET_ADDRESS not set"):
                create_api_client_from_env()

    def test_create_api_client_from_env_missing_key(self):
        """测试环境变量缺失私钥"""
        with patch.dict(os.environ, {'HYPERLIQUID_WALLET_ADDRESS': '0xtest'}, clear=True):
            with pytest.raises(ValueError, match="HYPERLIQUID_PRIVATE_KEY not set"):
                create_api_client_from_env()


# ==================== HyperliquidWebSocket 测试 ====================


class TestHyperliquidWebSocket:
    """测试 Hyperliquid WebSocket 客户端"""

    @pytest.fixture
    def mock_info(self, mocker):
        """Mock Info SDK"""
        info = mocker.MagicMock()
        info.subscribe = mocker.MagicMock()
        return info

    @pytest.fixture
    def ws_client(self, mocker, mock_info):
        """WebSocket 客户端实例（固定 mainnet）"""
        with patch('src.hyperliquid.websocket_client.Info', return_value=mock_info):
            client = HyperliquidWebSocket()
            client.info = mock_info
            return client

    def test_initialization_mainnet(self, mocker):
        """测试初始化（固定 mainnet）"""
        mock_info = mocker.MagicMock()

        with patch('src.hyperliquid.websocket_client.Info', return_value=mock_info):
            client = HyperliquidWebSocket()

            assert client.connected is False
            assert client.subscription_count == 0


    @pytest.mark.asyncio
    async def test_connect(self, ws_client):
        """测试连接"""
        assert ws_client.connected is False

        await ws_client.connect()

        assert ws_client.connected is True

    @pytest.mark.asyncio
    async def test_subscribe_l2_book_success(self, ws_client, mock_info):
        """测试订阅 L2 订单簿"""
        callback = MagicMock()

        await ws_client.subscribe_l2_book("ETH", callback)

        assert ws_client.subscription_count == 1
        assert "l2book_ETH" in ws_client._subscriptions

        # 验证 SDK 订阅被调用
        mock_info.subscribe.assert_called_once()
        call_args = mock_info.subscribe.call_args[0]
        assert call_args[0] == {"type": "l2Book", "coin": "ETH"}

    @pytest.mark.asyncio
    async def test_subscribe_l2_book_callback_error(self, ws_client, mock_info):
        """测试订单簿回调函数异常"""
        def error_callback(data):
            raise ValueError("Callback error")

        await ws_client.subscribe_l2_book("ETH", error_callback)

        # 获取包装的回调函数
        wrapped_callback = mock_info.subscribe.call_args[0][1]

        # 调用包装的回调应该不会抛出异常
        wrapped_callback({"test": "data"})

    @pytest.mark.asyncio
    async def test_subscribe_trades_success(self, ws_client, mock_info):
        """测试订阅成交数据"""
        callback = MagicMock()

        await ws_client.subscribe_trades("BTC", callback)

        assert ws_client.subscription_count == 1
        assert "trades_BTC" in ws_client._subscriptions

        call_args = mock_info.subscribe.call_args[0]
        assert call_args[0] == {"type": "trades", "coin": "BTC"}

    @pytest.mark.asyncio
    async def test_subscribe_all_mids_success(self, ws_client, mock_info):
        """测试订阅所有中间价"""
        callback = MagicMock()

        await ws_client.subscribe_all_mids(callback)

        assert ws_client.subscription_count == 1
        assert "all_mids" in ws_client._subscriptions

        call_args = mock_info.subscribe.call_args[0]
        assert call_args[0] == {"type": "allMids"}

    @pytest.mark.asyncio
    async def test_unsubscribe_existing(self, ws_client, mock_info):
        """测试取消已存在的订阅"""
        callback = MagicMock()
        await ws_client.subscribe_l2_book("ETH", callback)

        assert ws_client.subscription_count == 1

        await ws_client.unsubscribe("l2book_ETH")

        assert ws_client.subscription_count == 0
        assert "l2book_ETH" not in ws_client._subscriptions

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent(self, ws_client):
        """测试取消不存在的订阅"""
        # 不应该抛出异常
        await ws_client.unsubscribe("nonexistent_subscription")

        assert ws_client.subscription_count == 0

    @pytest.mark.asyncio
    async def test_close(self, ws_client, mock_info):
        """测试关闭连接"""
        # 添加多个订阅
        await ws_client.subscribe_l2_book("ETH", MagicMock())
        await ws_client.subscribe_trades("BTC", MagicMock())

        await ws_client.connect()
        assert ws_client.connected is True
        assert ws_client.subscription_count == 2

        await ws_client.close()

        assert ws_client.connected is False
        assert ws_client.subscription_count == 0

    def test_connected_property(self, ws_client):
        """测试连接状态属性"""
        assert ws_client.connected is False

        ws_client._connected = True
        assert ws_client.connected is True

    def test_subscription_count_property(self, ws_client):
        """测试订阅数量属性"""
        assert ws_client.subscription_count == 0

        ws_client._subscriptions["test1"] = {}
        ws_client._subscriptions["test2"] = {}

        assert ws_client.subscription_count == 2

    def test_create_websocket_from_env_mainnet(self, mocker):
        """测试从环境变量创建 WebSocket（固定 mainnet）"""
        mock_info = mocker.MagicMock()

        with patch.dict(os.environ, {'ENVIRONMENT': 'mainnet'}):
            with patch('src.hyperliquid.websocket_client.Info', return_value=mock_info):
                client = create_websocket_from_env()

                # 验证客户端创建成功（固定使用 mainnet）
                assert client is not None


    def test_create_websocket_from_env_default(self, mocker):
        """测试从环境变量创建 WebSocket（固定 mainnet）"""
        mock_info = mocker.MagicMock()

        with patch.dict(os.environ, {}, clear=True):
            with patch('src.hyperliquid.websocket_client.Info', return_value=mock_info):
                client = create_websocket_from_env()

                # 验证客户端创建成功（固定使用 mainnet）
                assert client is not None
