"""Hyperliquid WebSocket 客户端测试

测试 WebSocket 客户端的核心功能、订阅管理和异常处理。
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from hyperliquid.utils import constants

from src.hyperliquid.websocket_client import HyperliquidWebSocket, create_websocket_from_env

# ==================== Fixtures ====================


@pytest.fixture
def mock_info(mocker):
    """Mock hyperliquid Info 对象"""
    mock = mocker.MagicMock()
    mock.subscribe = mocker.MagicMock()
    return mock


@pytest.fixture
def ws_client_mainnet(mock_info, mocker):
    """WebSocket 客户端实例（固定 mainnet）"""
    with patch("src.hyperliquid.websocket_client.Info", return_value=mock_info):
        client = HyperliquidWebSocket()
        return client




@pytest.fixture
def sample_l2_data():
    """示例 L2 订单簿数据"""
    return {
        "coin": "BTC",
        "levels": [
            [{"px": "50000.0", "sz": "1.5", "n": 3}],  # bids
            [{"px": "50001.0", "sz": "2.0", "n": 2}],  # asks
        ],
        "time": 1700000000000,
    }


@pytest.fixture
def sample_trades_data():
    """示例成交数据"""
    return {
        "coin": "BTC",
        "time": 1700000000000,
        "trades": [
            {
                "px": "50000.0",
                "sz": "0.5",
                "side": "B",
                "time": 1700000000001,
                "hash": "0xabc123",
            }
        ],
    }


@pytest.fixture
def sample_mids_data():
    """示例中间价数据"""
    return {"mids": {"BTC": "50000.5", "ETH": "3000.2", "SOL": "100.5"}}


# ==================== 基础功能测试 ====================


class TestWebSocketBasics:
    """测试 WebSocket 基础功能"""

    def test_initialization_mainnet(self, mock_info, mocker):
        """测试初始化（固定 mainnet）"""
        with patch("src.hyperliquid.websocket_client.Info", return_value=mock_info) as mock_info_cls:
            client = HyperliquidWebSocket()

            assert client.info is mock_info
            assert client._connected is False
            assert client._subscriptions == {}

            # 验证使用了正确的 API URL（固定 mainnet）
            mock_info_cls.assert_called_once_with(
                base_url=constants.MAINNET_API_URL, skip_ws=False
            )


    @pytest.mark.asyncio
    async def test_connect(self, ws_client_mainnet):
        """测试连接"""
        assert ws_client_mainnet.connected is False

        await ws_client_mainnet.connect()

        assert ws_client_mainnet.connected is True

    @pytest.mark.asyncio
    async def test_close(self, ws_client_mainnet):
        """测试关闭连接"""
        # 先连接
        await ws_client_mainnet.connect()
        assert ws_client_mainnet.connected is True

        # 添加一些订阅
        ws_client_mainnet._subscriptions["test1"] = {"subscription": {}, "callback": lambda x: None}
        ws_client_mainnet._subscriptions["test2"] = {"subscription": {}, "callback": lambda x: None}
        assert ws_client_mainnet.subscription_count == 2

        # 关闭
        await ws_client_mainnet.close()

        assert ws_client_mainnet.connected is False
        assert ws_client_mainnet.subscription_count == 0

    def test_connected_property(self, ws_client_mainnet):
        """测试 connected 属性"""
        assert ws_client_mainnet.connected is False

        ws_client_mainnet._connected = True
        assert ws_client_mainnet.connected is True

        ws_client_mainnet._connected = False
        assert ws_client_mainnet.connected is False

    def test_subscription_count_property(self, ws_client_mainnet):
        """测试 subscription_count 属性"""
        assert ws_client_mainnet.subscription_count == 0

        ws_client_mainnet._subscriptions["test1"] = {}
        assert ws_client_mainnet.subscription_count == 1

        ws_client_mainnet._subscriptions["test2"] = {}
        assert ws_client_mainnet.subscription_count == 2

        ws_client_mainnet._subscriptions["test3"] = {}
        assert ws_client_mainnet.subscription_count == 3


# ==================== 订阅功能测试 ====================


class TestWebSocketSubscriptions:
    """测试订阅功能"""

    @pytest.mark.asyncio
    async def test_subscribe_l2_book_success(self, ws_client_mainnet, sample_l2_data):
        """测试成功订阅 L2 订单簿"""
        callback_called = []

        def callback(data):
            callback_called.append(data)

        await ws_client_mainnet.subscribe_l2_book("BTC", callback)

        # 验证订阅调用
        ws_client_mainnet.info.subscribe.assert_called_once()
        call_args = ws_client_mainnet.info.subscribe.call_args
        subscription = call_args[0][0]
        wrapped_callback = call_args[0][1]

        assert subscription == {"type": "l2Book", "coin": "BTC"}

        # 验证包装的回调函数工作正常
        wrapped_callback(sample_l2_data)
        assert len(callback_called) == 1
        assert callback_called[0] == sample_l2_data

        # 验证订阅已记录
        assert "l2book_BTC" in ws_client_mainnet._subscriptions
        assert ws_client_mainnet._subscriptions["l2book_BTC"]["callback"] == callback

    @pytest.mark.asyncio
    async def test_subscribe_l2_book_callback_error(self, ws_client_mainnet, sample_l2_data, mocker):
        """测试 L2 订单簿回调函数出错"""
        mock_logger = mocker.patch("src.hyperliquid.websocket_client.logger")

        def callback(data):
            raise ValueError("Callback error")

        await ws_client_mainnet.subscribe_l2_book("BTC", callback)

        # 获取包装的回调函数
        wrapped_callback = ws_client_mainnet.info.subscribe.call_args[0][1]

        # 调用回调函数（应该捕获异常）
        wrapped_callback(sample_l2_data)

        # 验证错误日志
        mock_logger.error.assert_called_once()
        assert "l2_book_callback_error" in str(mock_logger.error.call_args)

    @pytest.mark.asyncio
    async def test_subscribe_trades_success(self, ws_client_mainnet, sample_trades_data):
        """测试成功订阅成交数据"""
        callback_called = []

        def callback(data):
            callback_called.append(data)

        await ws_client_mainnet.subscribe_trades("BTC", callback)

        # 验证订阅调用
        ws_client_mainnet.info.subscribe.assert_called_once()
        call_args = ws_client_mainnet.info.subscribe.call_args
        subscription = call_args[0][0]
        wrapped_callback = call_args[0][1]

        assert subscription == {"type": "trades", "coin": "BTC"}

        # 验证包装的回调函数工作正常
        wrapped_callback(sample_trades_data)
        assert len(callback_called) == 1
        assert callback_called[0] == sample_trades_data

        # 验证订阅已记录
        assert "trades_BTC" in ws_client_mainnet._subscriptions
        assert ws_client_mainnet._subscriptions["trades_BTC"]["callback"] == callback

    @pytest.mark.asyncio
    async def test_subscribe_trades_callback_error(self, ws_client_mainnet, sample_trades_data, mocker):
        """测试成交数据回调函数出错"""
        mock_logger = mocker.patch("src.hyperliquid.websocket_client.logger")

        def callback(data):
            raise ValueError("Callback error")

        await ws_client_mainnet.subscribe_trades("BTC", callback)

        # 获取包装的回调函数
        wrapped_callback = ws_client_mainnet.info.subscribe.call_args[0][1]

        # 调用回调函数（应该捕获异常）
        wrapped_callback(sample_trades_data)

        # 验证错误日志
        mock_logger.error.assert_called_once()
        assert "trades_callback_error" in str(mock_logger.error.call_args)

    @pytest.mark.asyncio
    async def test_subscribe_all_mids_success(self, ws_client_mainnet, sample_mids_data):
        """测试成功订阅所有中间价"""
        callback_called = []

        def callback(data):
            callback_called.append(data)

        await ws_client_mainnet.subscribe_all_mids(callback)

        # 验证订阅调用
        ws_client_mainnet.info.subscribe.assert_called_once()
        call_args = ws_client_mainnet.info.subscribe.call_args
        subscription = call_args[0][0]
        wrapped_callback = call_args[0][1]

        assert subscription == {"type": "allMids"}

        # 验证包装的回调函数工作正常
        wrapped_callback(sample_mids_data)
        assert len(callback_called) == 1
        assert callback_called[0] == sample_mids_data

        # 验证订阅已记录
        assert "all_mids" in ws_client_mainnet._subscriptions
        assert ws_client_mainnet._subscriptions["all_mids"]["callback"] == callback

    @pytest.mark.asyncio
    async def test_subscribe_all_mids_callback_error(self, ws_client_mainnet, sample_mids_data, mocker):
        """测试所有中间价回调函数出错"""
        mock_logger = mocker.patch("src.hyperliquid.websocket_client.logger")

        def callback(data):
            raise ValueError("Callback error")

        await ws_client_mainnet.subscribe_all_mids(callback)

        # 获取包装的回调函数
        wrapped_callback = ws_client_mainnet.info.subscribe.call_args[0][1]

        # 调用回调函数（应该捕获异常）
        wrapped_callback(sample_mids_data)

        # 验证错误日志
        mock_logger.error.assert_called_once()
        assert "all_mids_callback_error" in str(mock_logger.error.call_args)

    @pytest.mark.asyncio
    async def test_multiple_subscriptions(self, ws_client_mainnet):
        """测试多个订阅"""
        callback1 = MagicMock()
        callback2 = MagicMock()
        callback3 = MagicMock()

        await ws_client_mainnet.subscribe_l2_book("BTC", callback1)
        await ws_client_mainnet.subscribe_trades("ETH", callback2)
        await ws_client_mainnet.subscribe_all_mids(callback3)

        assert ws_client_mainnet.subscription_count == 3
        assert "l2book_BTC" in ws_client_mainnet._subscriptions
        assert "trades_ETH" in ws_client_mainnet._subscriptions
        assert "all_mids" in ws_client_mainnet._subscriptions


# ==================== 取消订阅测试 ====================


class TestWebSocketUnsubscribe:
    """测试取消订阅功能"""

    @pytest.mark.asyncio
    async def test_unsubscribe_existing(self, ws_client_mainnet):
        """测试取消已存在的订阅"""
        # 先添加订阅
        callback = MagicMock()
        await ws_client_mainnet.subscribe_l2_book("BTC", callback)

        assert "l2book_BTC" in ws_client_mainnet._subscriptions
        assert ws_client_mainnet.subscription_count == 1

        # 取消订阅
        await ws_client_mainnet.unsubscribe("l2book_BTC")

        assert "l2book_BTC" not in ws_client_mainnet._subscriptions
        assert ws_client_mainnet.subscription_count == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent(self, ws_client_mainnet, mocker):
        """测试取消不存在的订阅"""
        mock_logger = mocker.patch("src.hyperliquid.websocket_client.logger")

        await ws_client_mainnet.unsubscribe("nonexistent_subscription")

        # 验证警告日志
        mock_logger.warning.assert_called_once()
        assert "subscription_not_found" in str(mock_logger.warning.call_args)

    @pytest.mark.asyncio
    async def test_unsubscribe_multiple(self, ws_client_mainnet):
        """测试取消多个订阅"""
        # 添加多个订阅
        callback1 = MagicMock()
        callback2 = MagicMock()
        callback3 = MagicMock()

        await ws_client_mainnet.subscribe_l2_book("BTC", callback1)
        await ws_client_mainnet.subscribe_trades("ETH", callback2)
        await ws_client_mainnet.subscribe_all_mids(callback3)

        assert ws_client_mainnet.subscription_count == 3

        # 取消部分订阅
        await ws_client_mainnet.unsubscribe("l2book_BTC")
        await ws_client_mainnet.unsubscribe("trades_ETH")

        assert ws_client_mainnet.subscription_count == 1
        assert "all_mids" in ws_client_mainnet._subscriptions


# ==================== 异常处理测试 ====================


class TestWebSocketExceptionHandling:
    """测试异常处理"""

    @pytest.mark.asyncio
    async def test_subscribe_l2_book_sdk_error(self, ws_client_mainnet, mocker):
        """测试订阅 L2 时 SDK 抛出异常"""
        mock_logger = mocker.patch("src.hyperliquid.websocket_client.logger")

        # Mock subscribe 抛出异常
        ws_client_mainnet.info.subscribe.side_effect = Exception("SDK error")

        callback = MagicMock()

        with pytest.raises(Exception, match="SDK error"):
            await ws_client_mainnet.subscribe_l2_book("BTC", callback)

        # 验证错误日志
        mock_logger.error.assert_called()
        assert "l2_book_subscription_error" in str(mock_logger.error.call_args)

    @pytest.mark.asyncio
    async def test_subscribe_trades_sdk_error(self, ws_client_mainnet, mocker):
        """测试订阅成交数据时 SDK 抛出异常"""
        mock_logger = mocker.patch("src.hyperliquid.websocket_client.logger")

        # Mock subscribe 抛出异常
        ws_client_mainnet.info.subscribe.side_effect = Exception("SDK error")

        callback = MagicMock()

        with pytest.raises(Exception, match="SDK error"):
            await ws_client_mainnet.subscribe_trades("BTC", callback)

        # 验证错误日志
        mock_logger.error.assert_called()
        assert "trades_subscription_error" in str(mock_logger.error.call_args)

    @pytest.mark.asyncio
    async def test_subscribe_all_mids_sdk_error(self, ws_client_mainnet, mocker):
        """测试订阅所有中间价时 SDK 抛出异常"""
        mock_logger = mocker.patch("src.hyperliquid.websocket_client.logger")

        # Mock subscribe 抛出异常
        ws_client_mainnet.info.subscribe.side_effect = Exception("SDK error")

        callback = MagicMock()

        with pytest.raises(Exception, match="SDK error"):
            await ws_client_mainnet.subscribe_all_mids(callback)

        # 验证错误日志
        mock_logger.error.assert_called()
        assert "all_mids_subscription_error" in str(mock_logger.error.call_args)


# ==================== 工厂函数测试 ====================


class TestWebSocketFactory:
    """测试工厂函数"""

    def test_create_from_env_mainnet(self, mocker):
        """测试从环境变量创建 mainnet 客户端"""
        mock_info = mocker.MagicMock()

        with patch("src.hyperliquid.websocket_client.Info", return_value=mock_info):
            with patch.dict(os.environ, {"ENVIRONMENT": "mainnet"}):
                client = create_websocket_from_env()

                # 验证客户端创建成功（固定使用 mainnet）
                assert client is not None


    def test_create_from_env_default(self, mocker):
        """测试从环境变量创建客户端（固定 mainnet）"""
        mock_info = mocker.MagicMock()

        with patch("src.hyperliquid.websocket_client.Info", return_value=mock_info):
            with patch.dict(os.environ, {}, clear=True):
                client = create_websocket_from_env()

                # 验证客户端创建成功（固定使用 mainnet）
                assert client is not None



# ==================== 集成测试 ====================


class TestWebSocketIntegration:
    """测试集成场景"""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, ws_client_mainnet, sample_l2_data):
        """测试完整生命周期"""
        # 1. 连接
        await ws_client_mainnet.connect()
        assert ws_client_mainnet.connected is True

        # 2. 订阅
        callback_called = []

        def callback(data):
            callback_called.append(data)

        await ws_client_mainnet.subscribe_l2_book("BTC", callback)
        assert ws_client_mainnet.subscription_count == 1

        # 3. 模拟接收数据
        wrapped_callback = ws_client_mainnet.info.subscribe.call_args[0][1]
        wrapped_callback(sample_l2_data)
        assert len(callback_called) == 1

        # 4. 取消订阅
        await ws_client_mainnet.unsubscribe("l2book_BTC")
        assert ws_client_mainnet.subscription_count == 0

        # 5. 关闭连接
        await ws_client_mainnet.close()
        assert ws_client_mainnet.connected is False

    @pytest.mark.asyncio
    async def test_multiple_symbols_lifecycle(self, ws_client_mainnet):
        """测试多个交易对的完整生命周期"""
        # 连接
        await ws_client_mainnet.connect()

        # 订阅多个交易对
        btc_callback = MagicMock()
        eth_callback = MagicMock()
        sol_callback = MagicMock()

        await ws_client_mainnet.subscribe_l2_book("BTC", btc_callback)
        await ws_client_mainnet.subscribe_l2_book("ETH", eth_callback)
        await ws_client_mainnet.subscribe_trades("SOL", sol_callback)

        assert ws_client_mainnet.subscription_count == 3

        # 取消部分订阅
        await ws_client_mainnet.unsubscribe("l2book_BTC")
        assert ws_client_mainnet.subscription_count == 2

        # 关闭连接（应该取消所有剩余订阅）
        await ws_client_mainnet.close()
        assert ws_client_mainnet.subscription_count == 0
        assert ws_client_mainnet.connected is False
