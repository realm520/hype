"""核心数据层测试

测试 OrderBook 和 MarketDataManager 的核心功能。
"""

from collections import deque
from decimal import Decimal

import pytest

from src.core.data_feed import MarketDataManager
from src.core.orderbook import OrderBook
from src.core.types import OrderSide, Trade

# ==================== OrderBook 测试 ====================


class TestOrderBook:
    """测试订单簿管理器"""

    @pytest.fixture
    def orderbook(self):
        """订单簿实例"""
        return OrderBook(symbol="ETH", levels=10)

    @pytest.fixture
    def sample_l2_data(self):
        """示例 L2 数据"""
        return {
            "coin": "ETH",
            "levels": [
                # Bids (买盘，价格从高到低)
                [
                    {"px": "3000.0", "sz": "10.0", "n": 5},
                    {"px": "2999.5", "sz": "15.0", "n": 3},
                    {"px": "2999.0", "sz": "20.0", "n": 4},
                ],
                # Asks (卖盘，价格从低到高)
                [
                    {"px": "3000.5", "sz": "12.0", "n": 6},
                    {"px": "3001.0", "sz": "18.0", "n": 2},
                    {"px": "3001.5", "sz": "25.0", "n": 3},
                ],
            ],
            "time": 1700000000000,
        }

    def test_initialization(self, orderbook):
        """测试初始化"""
        assert orderbook.symbol == "ETH"
        assert orderbook.levels == 10
        assert orderbook.update_count == 0
        assert orderbook.last_update_time == 0
        assert orderbook.is_valid() is False  # 初始为空

    def test_update_success(self, orderbook, sample_l2_data):
        """测试成功更新订单簿"""
        import time
        before_update = int(time.time() * 1000)
        orderbook.update(sample_l2_data)
        after_update = int(time.time() * 1000)

        assert orderbook.update_count == 1
        # 验证时间戳是实时的（在更新前后的时间范围内）
        assert before_update <= orderbook.last_update_time <= after_update
        assert orderbook.is_valid() is True

        # 验证 bids
        assert len(orderbook._bids) == 3
        assert orderbook._bids[0].price == Decimal("3000.0")
        assert orderbook._bids[0].size == Decimal("10.0")

        # 验证 asks
        assert len(orderbook._asks) == 3
        assert orderbook._asks[0].price == Decimal("3000.5")
        assert orderbook._asks[0].size == Decimal("12.0")

    def test_update_invalid_format(self, orderbook):
        """测试无效数据格式"""
        invalid_data = {
            "coin": "ETH",
            "levels": [[]],  # 缺少 asks
            "time": 1700000000000,
        }

        orderbook.update(invalid_data)

        # 应该不更新
        assert orderbook.update_count == 0
        assert orderbook.is_valid() is False

    def test_update_exception_handling(self, orderbook):
        """测试异常处理"""
        malformed_data = {
            "coin": "ETH",
            "levels": [
                [{"px": "invalid_price", "sz": "10.0"}],  # 无效价格
                [{"px": "3000.5", "sz": "12.0"}],
            ],
            "time": 1700000000000,
        }

        # 不应该抛出异常
        orderbook.update(malformed_data)

    def test_get_snapshot(self, orderbook, sample_l2_data):
        """测试获取订单簿快照"""
        import time
        before_update = int(time.time() * 1000)
        orderbook.update(sample_l2_data)
        after_update = int(time.time() * 1000)

        snapshot = orderbook.get_snapshot()

        assert snapshot.symbol == "ETH"
        # 验证时间戳是实时的（在更新前后的时间范围内）
        assert before_update <= snapshot.timestamp <= after_update
        assert len(snapshot.bids) == 3
        assert len(snapshot.asks) == 3
        assert snapshot.mid_price == Decimal("3000.25")  # (3000 + 3000.5) / 2

    def test_get_best_bid_ask(self, orderbook, sample_l2_data):
        """测试获取最优买卖价"""
        orderbook.update(sample_l2_data)

        best_bid, best_ask = orderbook.get_best_bid_ask()

        assert best_bid is not None
        assert best_bid.price == Decimal("3000.0")
        assert best_ask is not None
        assert best_ask.price == Decimal("3000.5")

    def test_get_best_bid_ask_empty(self, orderbook):
        """测试空订单簿的最优买卖价"""
        best_bid, best_ask = orderbook.get_best_bid_ask()

        assert best_bid is None
        assert best_ask is None

    def test_get_mid_price(self, orderbook, sample_l2_data):
        """测试获取中间价"""
        orderbook.update(sample_l2_data)

        mid_price = orderbook.get_mid_price()

        assert mid_price == Decimal("3000.25")

    def test_get_mid_price_empty(self, orderbook):
        """测试空订单簿的中间价"""
        mid_price = orderbook.get_mid_price()

        assert mid_price == Decimal("0")

    def test_get_spread(self, orderbook, sample_l2_data):
        """测试获取买卖价差"""
        orderbook.update(sample_l2_data)

        spread = orderbook.get_spread()

        assert spread == Decimal("0.5")  # 3000.5 - 3000.0

    def test_get_spread_empty(self, orderbook):
        """测试空订单簿的价差"""
        spread = orderbook.get_spread()

        assert spread == Decimal("0")

    def test_get_spread_bps(self, orderbook, sample_l2_data):
        """测试获取买卖价差（bps）"""
        orderbook.update(sample_l2_data)

        spread_bps = orderbook.get_spread_bps()

        # 0.5 / 3000.25 * 10000 ≈ 1.67 bps
        assert 1.6 < spread_bps < 1.7

    def test_get_spread_bps_empty(self, orderbook):
        """测试空订单簿的价差（bps）"""
        spread_bps = orderbook.get_spread_bps()

        assert spread_bps == 0.0

    def test_get_depth(self, orderbook, sample_l2_data):
        """测试获取订单簿深度"""
        orderbook.update(sample_l2_data)

        depth = orderbook.get_depth(levels=2)

        assert len(depth["bids"]) == 2
        assert len(depth["asks"]) == 2
        assert depth["bids"][0].price == Decimal("3000.0")
        assert depth["asks"][0].price == Decimal("3000.5")

    def test_is_valid(self, orderbook, sample_l2_data):
        """测试订单簿有效性检查"""
        # 初始为空，无效
        assert orderbook.is_valid() is False

        # 更新后有效
        orderbook.update(sample_l2_data)
        assert orderbook.is_valid() is True

    def test_update_count_property(self, orderbook, sample_l2_data):
        """测试更新次数属性"""
        assert orderbook.update_count == 0

        orderbook.update(sample_l2_data)
        assert orderbook.update_count == 1

        orderbook.update(sample_l2_data)
        assert orderbook.update_count == 2

    def test_last_update_time_property(self, orderbook, sample_l2_data):
        """测试最后更新时间属性"""
        import time
        assert orderbook.last_update_time == 0

        before_update = int(time.time() * 1000)
        orderbook.update(sample_l2_data)
        after_update = int(time.time() * 1000)

        # 验证时间戳是实时的（在更新前后的时间范围内）
        assert before_update <= orderbook.last_update_time <= after_update

    def test_repr(self, orderbook, sample_l2_data):
        """测试字符串表示"""
        orderbook.update(sample_l2_data)

        repr_str = repr(orderbook)

        assert "OrderBook" in repr_str
        assert "ETH" in repr_str
        assert "mid=3000.25" in repr_str
        assert "updates=1" in repr_str

    def test_levels_truncation(self, orderbook):
        """测试档位截断"""
        # 创建 15 档数据，但订单簿只保留 10 档
        large_l2_data = {
            "coin": "ETH",
            "levels": [
                [{"px": f"{3000 - i}", "sz": "10.0", "n": 1} for i in range(15)],
                [{"px": f"{3001 + i}", "sz": "10.0", "n": 1} for i in range(15)],
            ],
            "time": 1700000000000,
        }

        orderbook.update(large_l2_data)

        # 应该只保留前 10 档
        assert len(orderbook._bids) == 10
        assert len(orderbook._asks) == 10


# ==================== MarketDataManager 测试 ====================


class TestMarketDataManager:
    """测试市场数据管理器"""

    @pytest.fixture
    def mock_ws_client(self, mocker):
        """Mock WebSocket 客户端"""
        ws = mocker.MagicMock()
        ws.connect = mocker.AsyncMock()
        ws.subscribe_l2_book = mocker.AsyncMock()
        ws.subscribe_trades = mocker.AsyncMock()
        ws.close = mocker.AsyncMock()
        return ws

    @pytest.fixture
    def data_manager(self, mock_ws_client):
        """数据管理器实例"""
        return MarketDataManager(ws_client=mock_ws_client, max_trades_history=1000)

    def test_initialization(self, data_manager):
        """测试初始化"""
        assert data_manager.max_trades_history == 1000
        assert data_manager.started is False
        assert len(data_manager._orderbooks) == 0
        assert len(data_manager._trades) == 0

    @pytest.mark.asyncio
    async def test_start(self, data_manager, mock_ws_client):
        """测试启动数据管理器"""
        symbols = ["ETH", "BTC"]

        await data_manager.start(symbols, orderbook_levels=10)

        # 验证 WebSocket 连接
        mock_ws_client.connect.assert_called_once()

        # 验证订单簿创建
        assert "ETH" in data_manager._orderbooks
        assert "BTC" in data_manager._orderbooks
        assert data_manager._orderbooks["ETH"].levels == 10

        # 验证订阅
        assert mock_ws_client.subscribe_l2_book.call_count == 2
        assert mock_ws_client.subscribe_trades.call_count == 2

        # 验证成交历史初始化
        assert "ETH" in data_manager._trades
        assert "BTC" in data_manager._trades

        assert data_manager.started is True

    def test_create_l2_callback(self, data_manager):
        """测试创建 L2 回调函数"""
        # 先创建订单簿
        data_manager._orderbooks["ETH"] = OrderBook("ETH", levels=10)

        callback = data_manager._create_l2_callback("ETH")

        # 模拟 WebSocket 消息格式：{data: {...}}
        ws_message = {
            "data": {
                "coin": "ETH",
                "levels": [
                    [{"px": "3000.0", "sz": "10.0", "n": 1}],
                    [{"px": "3001.0", "sz": "12.0", "n": 1}],
                ],
                "time": 1700000000000,
            }
        }

        # 调用回调
        callback(ws_message)

        # 验证订单簿已更新
        assert data_manager._orderbooks["ETH"].update_count == 1
        # 验证时间戳使用了 L2 数据中的 time 字段
        assert data_manager._orderbooks["ETH"].last_update_time == 1700000000000

    def test_create_trades_callback(self, data_manager):
        """测试创建成交回调函数"""
        # 初始化成交队列
        data_manager._trades["ETH"] = deque(maxlen=1000)

        callback = data_manager._create_trades_callback("ETH")

        # 模拟 WebSocket 成交数据（格式：{data: [...]}）
        ws_message = {
            "data": [
                {"px": "3000.5", "sz": "1.5", "side": "B", "time": 1700000000001},
                {"px": "3000.6", "sz": "2.0", "side": "A", "time": 1700000000002},
            ]
        }

        # 调用回调
        callback(ws_message)

        # 验证成交已记录
        assert len(data_manager._trades["ETH"]) == 2
        assert data_manager._trades["ETH"][0].price == Decimal("3000.5")
        assert data_manager._trades["ETH"][0].side == OrderSide.BUY
        assert data_manager._trades["ETH"][1].side == OrderSide.SELL

    def test_get_market_data_success(self, data_manager):
        """测试成功获取市场数据"""
        # 设置订单簿（使用固定时间戳）
        orderbook = OrderBook("ETH", levels=10)
        orderbook.update(
            {
                "coin": "ETH",
                "levels": [
                    [{"px": "3000.0", "sz": "10.0", "n": 1}],
                    [{"px": "3001.0", "sz": "12.0", "n": 1}],
                ],
                "time": 1700000000000,
            },
            timestamp_override=1700000000000,  # 显式传递固定时间戳
        )
        data_manager._orderbooks["ETH"] = orderbook

        # 设置成交历史
        data_manager._trades["ETH"] = deque([
            Trade(symbol="ETH", timestamp=1700000000001, price=Decimal("3000.5"), size=Decimal("1.5"), side=OrderSide.BUY)
        ], maxlen=1000)

        market_data = data_manager.get_market_data("ETH")

        assert market_data is not None
        assert market_data.symbol == "ETH"
        assert market_data.timestamp == 1700000000000
        assert len(market_data.bids) == 1
        assert len(market_data.asks) == 1
        assert len(market_data.trades) == 1
        assert market_data.mid_price == Decimal("3000.5")

    def test_get_market_data_symbol_not_found(self, data_manager):
        """测试获取不存在的交易对"""
        market_data = data_manager.get_market_data("NONEXISTENT")

        assert market_data is None

    def test_get_market_data_orderbook_invalid(self, data_manager):
        """测试获取无效订单簿"""
        # 创建空订单簿（无效）
        data_manager._orderbooks["ETH"] = OrderBook("ETH", levels=10)

        market_data = data_manager.get_market_data("ETH")

        assert market_data is None

    def test_get_orderbook(self, data_manager):
        """测试获取订单簿"""
        orderbook = OrderBook("ETH", levels=10)
        data_manager._orderbooks["ETH"] = orderbook

        result = data_manager.get_orderbook("ETH")

        assert result is orderbook

    def test_get_orderbook_not_found(self, data_manager):
        """测试获取不存在的订单簿"""
        result = data_manager.get_orderbook("NONEXISTENT")

        assert result is None

    def test_get_recent_trades(self, data_manager):
        """测试获取最近成交"""
        trades = deque([
            Trade(symbol="ETH", timestamp=i, price="3000.0", size="1.0", side=OrderSide.BUY)
            for i in range(150)
        ], maxlen=1000)
        data_manager._trades["ETH"] = trades

        # 获取最近 100 笔
        recent = data_manager.get_recent_trades("ETH", n=100)

        assert len(recent) == 100
        # 应该是最后 100 笔
        assert recent[-1].timestamp == 149

    def test_get_recent_trades_symbol_not_found(self, data_manager):
        """测试获取不存在交易对的成交"""
        recent = data_manager.get_recent_trades("NONEXISTENT")

        assert recent == []

    @pytest.mark.asyncio
    async def test_stop(self, data_manager, mock_ws_client):
        """测试停止数据管理器"""
        data_manager._started = True

        await data_manager.stop()

        mock_ws_client.close.assert_called_once()
        assert data_manager.started is False

    def test_started_property(self, data_manager):
        """测试启动状态属性"""
        assert data_manager.started is False

        data_manager._started = True
        assert data_manager.started is True

    @pytest.mark.asyncio
    async def test_symbols_property(self, data_manager, mock_ws_client):
        """测试交易对列表属性"""
        await data_manager.start(["ETH", "BTC"])

        symbols = data_manager.symbols

        assert set(symbols) == {"ETH", "BTC"}

    def test_trades_history_limit(self, data_manager):
        """测试成交历史记录限制"""
        data_manager._trades["ETH"] = deque(maxlen=100)  # 设置较小的限制

        # 添加 150 笔成交
        for i in range(150):
            data_manager._trades["ETH"].append(
                Trade(symbol="ETH", timestamp=i, price="3000.0", size="1.0", side=OrderSide.BUY)
            )

        # 应该只保留最后 100 笔
        assert len(data_manager._trades["ETH"]) == 100
        assert data_manager._trades["ETH"][0].timestamp == 50  # 从 50 开始
