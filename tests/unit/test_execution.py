"""执行层单元测试

测试 IOC 执行器、订单管理器、滑点估算器等核心执行逻辑。
"""

import time
from decimal import Decimal

import pytest

from src.core.types import (
    MarketData,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)
from src.execution.ioc_executor import IOCExecutor
from src.execution.order_manager import OrderManager
from src.execution.slippage_estimator import SlippageEstimator

# ==================== IOCExecutor 测试 ====================


class TestIOCExecutor:
    """测试 IOC 执行器"""

    @pytest.fixture
    def mock_api_client(self, mocker):
        """Mock API 客户端"""
        client = mocker.AsyncMock()
        # 默认成功响应
        client.place_order.return_value = {
            "status": "success",
            "id": "order_123",
            "response": {
                "data": {
                    "statuses": [
                        {
                            "filled": "1.0",  # filled 字段应该是字符串，可转换为 Decimal
                        }
                    ]
                }
            },
        }
        return client

    @pytest.fixture
    def ioc_executor(self, mock_api_client):
        """IOC 执行器实例"""
        return IOCExecutor(
            api_client=mock_api_client,
            default_size=Decimal("1.0"),
            price_adjustment_bps=10.0,
        )

    def test_initialization(self, ioc_executor):
        """测试初始化"""
        assert ioc_executor.default_size == Decimal("1.0")
        assert ioc_executor.price_adjustment_bps == 10.0

    def test_should_execute_high_confidence(
        self, ioc_executor, high_confidence_buy_signal
    ):
        """测试高置信度信号应该执行"""
        assert ioc_executor.should_execute(high_confidence_buy_signal) is True

    def test_should_execute_medium_confidence(
        self, ioc_executor, medium_confidence_signal
    ):
        """测试中等置信度信号不执行（Week 1）"""
        assert ioc_executor.should_execute(medium_confidence_signal) is False

    def test_should_execute_low_confidence(self, ioc_executor, low_confidence_signal):
        """测试低置信度信号不执行"""
        assert ioc_executor.should_execute(low_confidence_signal) is False

    @pytest.mark.asyncio
    async def test_execute_buy_order_success(
        self, ioc_executor, high_confidence_buy_signal, sample_market_data
    ):
        """测试成功执行买入订单"""
        order = await ioc_executor.execute(
            high_confidence_buy_signal, sample_market_data, size=Decimal("1.0")
        )

        assert order is not None
        assert order.symbol == "ETH"
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.IOC
        assert order.size == Decimal("1.0")
        # 买入价格应该稍高（+10 bps 提高成交概率）
        expected_price = sample_market_data.asks[0].price * Decimal("1.001")
        assert abs(order.price - expected_price) < Decimal("0.01")

    @pytest.mark.asyncio
    async def test_execute_sell_order_success(
        self, ioc_executor, high_confidence_sell_signal, sample_market_data
    ):
        """测试成功执行卖出订单"""
        order = await ioc_executor.execute(
            high_confidence_sell_signal, sample_market_data, size=Decimal("1.0")
        )

        assert order is not None
        assert order.symbol == "ETH"
        assert order.side == OrderSide.SELL
        assert order.order_type == OrderType.IOC
        # 卖出价格应该稍低（-10 bps 提高成交概率）
        expected_price = sample_market_data.bids[0].price * Decimal("0.999")
        assert abs(order.price - expected_price) < Decimal("0.01")

    @pytest.mark.asyncio
    async def test_execute_skip_low_confidence(
        self, ioc_executor, low_confidence_signal, sample_market_data
    ):
        """测试低置信度信号被跳过"""
        order = await ioc_executor.execute(
            low_confidence_signal, sample_market_data, size=Decimal("1.0")
        )

        assert order is None
        # 验证没有调用 API
        ioc_executor.api_client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_api_failure(
        self, ioc_executor, high_confidence_buy_signal, sample_market_data
    ):
        """测试 API 调用失败"""
        # 模拟 API 失败
        ioc_executor.api_client.place_order.return_value = {
            "status": "error",
            "error": "Insufficient funds",
        }

        order = await ioc_executor.execute(
            high_confidence_buy_signal, sample_market_data
        )

        # API 失败会返回 REJECTED 状态的订单
        assert order is not None
        assert order.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_execute_api_exception(
        self, ioc_executor, high_confidence_buy_signal, sample_market_data
    ):
        """测试 API 抛出异常"""
        # 模拟网络异常
        ioc_executor.api_client.place_order.side_effect = Exception("Network timeout")

        order = await ioc_executor.execute(
            high_confidence_buy_signal, sample_market_data
        )

        assert order is None

    @pytest.mark.asyncio
    async def test_execute_default_size(
        self, ioc_executor, high_confidence_buy_signal, sample_market_data
    ):
        """测试使用默认订单大小"""
        order = await ioc_executor.execute(
            high_confidence_buy_signal, sample_market_data  # 不指定 size
        )

        assert order is not None
        assert order.size == ioc_executor.default_size

    @pytest.mark.asyncio
    async def test_price_adjustment_buy(
        self, ioc_executor, high_confidence_buy_signal, create_market_data
    ):
        """测试买入价格调整逻辑"""
        market_data = create_market_data(mid_price=1000.0, spread_bps=5.0)

        order = await ioc_executor.execute(
            high_confidence_buy_signal, market_data, size=Decimal("1.0")
        )

        # 买入应该以稍高于卖一价下单（+10 bps）
        ask_price = market_data.asks[0].price
        expected_price = ask_price * (Decimal("1") + Decimal("0.001"))  # +10 bps
        assert order.price >= ask_price
        assert abs(order.price - expected_price) < Decimal("0.01")

    @pytest.mark.asyncio
    async def test_price_adjustment_sell(
        self, ioc_executor, high_confidence_sell_signal, create_market_data
    ):
        """测试卖出价格调整逻辑"""
        market_data = create_market_data(mid_price=1000.0, spread_bps=5.0)

        order = await ioc_executor.execute(
            high_confidence_sell_signal, market_data, size=Decimal("1.0")
        )

        # 卖出应该以稍低于买一价下单（-10 bps）
        bid_price = market_data.bids[0].price
        expected_price = bid_price * (Decimal("1") - Decimal("0.001"))  # -10 bps
        assert order.price <= bid_price
        assert abs(order.price - expected_price) < Decimal("0.01")


# ==================== OrderManager 测试 ====================


class TestOrderManager:
    """测试订单管理器"""

    @pytest.fixture
    def mock_executor(self, mocker):
        """Mock IOC 执行器"""
        executor = mocker.MagicMock()
        # should_execute 是同步方法
        executor.should_execute = mocker.MagicMock(return_value=True)
        executor.default_size = Decimal("1.0")

        # 模拟成功订单
        mock_order = Order(
            id="test_001",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("1500.5"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=int(time.time() * 1000),
        )
        # execute 是异步方法
        executor.execute = mocker.AsyncMock(return_value=mock_order)
        return executor

    @pytest.fixture
    def mock_slippage_estimator(self, mocker):
        """Mock 滑点估算器"""
        estimator = mocker.MagicMock()
        estimator.max_slippage_bps = 20.0
        estimator.estimate.return_value = {
            "estimated_price": Decimal("1500.5"),
            "slippage_bps": 5.0,
            "is_acceptable": True,
        }
        return estimator

    @pytest.fixture
    def order_manager(self, mock_executor, mock_slippage_estimator):
        """订单管理器实例"""
        return OrderManager(
            executor=mock_executor,
            slippage_estimator=mock_slippage_estimator,
            max_order_history=1000,
        )

    def test_initialization(self, order_manager):
        """测试初始化"""
        assert order_manager.max_order_history == 1000
        assert len(order_manager._order_history) == 0
        assert len(order_manager._active_orders) == 0

    @pytest.mark.asyncio
    async def test_execute_signal_success(
        self, order_manager, high_confidence_buy_signal, sample_market_data
    ):
        """测试成功执行信号"""
        order = await order_manager.execute_signal(
            high_confidence_buy_signal, sample_market_data, size=Decimal("1.0")
        )

        assert order is not None
        assert order.symbol == "ETH"
        assert order.side == OrderSide.BUY

        # 验证调用链
        order_manager.executor.should_execute.assert_called_once_with(
            high_confidence_buy_signal
        )
        order_manager.slippage_estimator.estimate.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_signal_skip_low_confidence(
        self, order_manager, low_confidence_signal, sample_market_data
    ):
        """测试低置信度信号被跳过"""
        order_manager.executor.should_execute.return_value = False

        order = await order_manager.execute_signal(
            low_confidence_signal, sample_market_data
        )

        assert order is None
        # 验证没有调用执行器
        order_manager.executor.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_signal_reject_high_slippage(
        self, order_manager, high_confidence_buy_signal, sample_market_data
    ):
        """测试拒绝高滑点订单"""
        # 模拟高滑点
        order_manager.slippage_estimator.estimate.return_value = {
            "estimated_price": Decimal("1505.0"),
            "slippage_bps": 25.0,  # 超过 20 bps 限制
            "is_acceptable": False,
        }

        order = await order_manager.execute_signal(
            high_confidence_buy_signal, sample_market_data
        )

        assert order is None
        # 验证没有调用执行器
        order_manager.executor.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_order_recording(
        self, order_manager, high_confidence_buy_signal, sample_market_data
    ):
        """测试订单记录功能"""
        order = await order_manager.execute_signal(
            high_confidence_buy_signal, sample_market_data
        )

        # 验证订单被记录
        assert len(order_manager._order_history) == 1
        assert order_manager._order_history[0] == order

        # 已完成订单不应在活跃列表中
        assert order.id not in order_manager._active_orders

    @pytest.mark.asyncio
    async def test_active_orders_tracking(
        self, order_manager, high_confidence_buy_signal, sample_market_data
    ):
        """测试活跃订单追踪"""
        # 模拟部分成交订单
        partial_order = Order(
            id="test_partial",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("1500.5"),
            size=Decimal("10.0"),
            filled_size=Decimal("5.0"),
            status=OrderStatus.PARTIALLY_FILLED,
            created_at=int(time.time() * 1000),
        )
        order_manager.executor.execute.return_value = partial_order

        await order_manager.execute_signal(
            high_confidence_buy_signal, sample_market_data
        )

        # 部分成交订单应该在活跃列表中
        assert partial_order.id in order_manager._active_orders
        assert order_manager._active_orders[partial_order.id] == partial_order

    def test_get_order_history(self, order_manager):
        """测试获取订单历史"""
        # 添加一些测试订单
        for i in range(5):
            order = Order(
                id=f"test_{i}",
                symbol="ETH",
                side=OrderSide.BUY,
                order_type=OrderType.IOC,
                price=Decimal("1500.0"),
                size=Decimal("1.0"),
                filled_size=Decimal("1.0"),
                status=OrderStatus.FILLED,
                created_at=int(time.time() * 1000) + i,
            )
            order_manager._order_history.append(order)

        history = order_manager.get_order_history(limit=3)

        assert len(history) == 3
        # 应该按时间倒序（最新在前）
        assert history[0].id == "test_4"

    def test_get_order_history_filter_by_symbol(self, order_manager):
        """测试按交易对过滤订单历史"""
        # 添加不同交易对的订单
        for symbol in ["ETH", "BTC", "ETH", "SOL"]:
            order = Order(
                id=f"test_{symbol}",
                symbol=symbol,
                side=OrderSide.BUY,
                order_type=OrderType.IOC,
                price=Decimal("1000.0"),
                size=Decimal("1.0"),
                filled_size=Decimal("1.0"),
                status=OrderStatus.FILLED,
                created_at=int(time.time() * 1000),
            )
            order_manager._order_history.append(order)

        eth_history = order_manager.get_order_history(symbol="ETH")

        assert len(eth_history) == 2
        assert all(order.symbol == "ETH" for order in eth_history)

    def test_get_active_orders(self, order_manager):
        """测试获取活跃订单"""
        # 添加活跃订单
        order1 = Order(
            id="active_1",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("1500.0"),
            size=Decimal("10.0"),
            filled_size=Decimal("5.0"),
            status=OrderStatus.PARTIALLY_FILLED,
            created_at=int(time.time() * 1000),
        )
        order_manager._active_orders[order1.id] = order1

        active_orders = order_manager.get_active_orders()

        assert len(active_orders) == 1
        assert active_orders[0].id == "active_1"

    def test_get_order_by_id(self, order_manager):
        """测试根据 ID 获取订单"""
        order = Order(
            id="test_123",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("1500.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=int(time.time() * 1000),
        )
        order_manager._order_history.append(order)

        found_order = order_manager.get_order_by_id("test_123")

        assert found_order is not None
        assert found_order.id == "test_123"

    def test_get_order_by_id_not_found(self, order_manager):
        """测试获取不存在的订单"""
        found_order = order_manager.get_order_by_id("nonexistent")

        assert found_order is None

    def test_get_statistics(self, order_manager):
        """测试获取统计信息"""
        # 添加不同状态的订单
        statuses = [
            OrderStatus.FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.PARTIALLY_FILLED,
        ]

        for i, status in enumerate(statuses):
            order = Order(
                id=f"test_{i}",
                symbol="ETH",
                side=OrderSide.BUY,
                order_type=OrderType.IOC,
                price=Decimal("1500.0"),
                size=Decimal("1.0"),
                filled_size=Decimal("1.0"),
                status=status,
                created_at=int(time.time() * 1000),
            )
            order_manager._order_history.append(order)

        stats = order_manager.get_statistics()

        assert stats["total_orders"] == 4
        assert stats["status_counts"]["FILLED"] == 2
        assert stats["status_counts"]["CANCELLED"] == 1
        assert stats["status_counts"]["PARTIAL_FILLED"] == 1


# ==================== SlippageEstimator 测试 ====================


class TestSlippageEstimator:
    """测试滑点估算器"""

    @pytest.fixture
    def slippage_estimator(self):
        """滑点估算器实例"""
        return SlippageEstimator(max_slippage_bps=20.0)

    def test_initialization(self, slippage_estimator):
        """测试初始化"""
        assert slippage_estimator.max_slippage_bps == 20.0

    def test_estimate_buy_small_size(self, slippage_estimator, sample_market_data):
        """测试小额买入订单滑点估算"""
        result = slippage_estimator.estimate(
            market_data=sample_market_data,
            side=OrderSide.BUY,
            size=Decimal("1.0"),
        )

        assert result["is_acceptable"] is True
        assert result["slippage_bps"] < 20.0
        # 小额订单应该能在卖一价成交
        assert result["estimated_price"] == sample_market_data.asks[0].price

    def test_estimate_sell_small_size(self, slippage_estimator, sample_market_data):
        """测试小额卖出订单滑点估算"""
        result = slippage_estimator.estimate(
            market_data=sample_market_data,
            side=OrderSide.SELL,
            size=Decimal("1.0"),
        )

        assert result["is_acceptable"] is True
        assert result["slippage_bps"] < 20.0
        # 小额订单应该能在买一价成交
        assert result["estimated_price"] == sample_market_data.bids[0].price

    def test_estimate_buy_large_size(self, slippage_estimator, sample_market_data):
        """测试大额买入订单滑点估算（需要穿透多个档位）"""
        result = slippage_estimator.estimate(
            market_data=sample_market_data,
            side=OrderSide.BUY,
            size=Decimal("50.0"),  # 超过卖一档位数量
        )

        # 大额订单平均成交价应该高于卖一价
        assert result["estimated_price"] > sample_market_data.asks[0].price
        assert result["slippage_bps"] > 0

    def test_estimate_wide_spread_market(
        self, slippage_estimator, wide_spread_market_data
    ):
        """测试宽点差市场的滑点估算"""
        result = slippage_estimator.estimate(
            market_data=wide_spread_market_data,
            side=OrderSide.BUY,
            size=Decimal("1.0"),
        )

        # 小订单在卖一价成交，滑点应该接近0（因为参考价就是卖一价）
        assert result["slippage_bps"] >= 0
        # 检查是否可接受
        assert result["is_acceptable"] == (result["slippage_bps"] <= 20.0)

    def test_estimate_insufficient_liquidity(self, slippage_estimator):
        """测试流动性不足场景"""
        # 创建流动性很差的市场数据
        from src.core.types import Level

        thin_market = MarketData(
            symbol="ETH",
            timestamp=int(time.time() * 1000),
            bids=[Level(price=Decimal("1500.0"), size=Decimal("0.1"))],
            asks=[
                Level(price=Decimal("1501.0"), size=Decimal("0.1")),
                Level(price=Decimal("1600.0"), size=Decimal("1.0")),  # 大价差
            ],
            mid_price=Decimal("1500.5"),
        )

        result = slippage_estimator.estimate(
            market_data=thin_market,
            side=OrderSide.BUY,
            size=Decimal("10.0"),  # 远超第一档流动性
        )

        # 大订单会消耗多个档位，平均成交价会很高，滑点应该超标
        assert result["levels_consumed"] > 1
        assert result["slippage_bps"] > 20.0
        assert result["is_acceptable"] is False

    def test_calculate_actual_slippage_buy(self, slippage_estimator):
        """测试计算买入订单实际滑点"""
        execution_price = Decimal("1501.0")
        reference_price = Decimal("1500.0")

        slippage_bps = slippage_estimator.calculate_actual_slippage(
            execution_price=execution_price,
            reference_price=reference_price,
            side=OrderSide.BUY,
        )

        # 买入：(execution - ref) / ref * 10000
        expected_bps = float((execution_price - reference_price) / reference_price * 10000)
        assert abs(slippage_bps - expected_bps) < 0.01

    def test_calculate_actual_slippage_sell(self, slippage_estimator):
        """测试计算卖出订单实际滑点"""
        execution_price = Decimal("1499.0")
        reference_price = Decimal("1500.0")

        slippage_bps = slippage_estimator.calculate_actual_slippage(
            execution_price=execution_price,
            reference_price=reference_price,
            side=OrderSide.SELL,
        )

        # 卖出：(ref - execution) / ref * 10000
        expected_bps = float((reference_price - execution_price) / reference_price * 10000)
        assert abs(slippage_bps - expected_bps) < 0.01

    def test_calculate_actual_slippage_zero(self, slippage_estimator):
        """测试零滑点情况"""
        reference_price = Decimal("1500.0")

        slippage_bps = slippage_estimator.calculate_actual_slippage(
            execution_price=reference_price,
            reference_price=reference_price,
            side=OrderSide.BUY,
        )

        assert slippage_bps == 0.0
