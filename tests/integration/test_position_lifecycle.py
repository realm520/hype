"""持仓生命周期集成测试（简化版）

Week 2 Phase 2 端到端测试：验证 TP/SL 和超时平仓的完整流程
"""

import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.types import (
    MarketData,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)
from src.execution.ioc_executor import IOCExecutor
from src.execution.position_closer import PositionCloser
from src.risk.tp_sl_manager import TPSLManager


# ==================== 测试夹具 ====================


@pytest.fixture
def mock_position_manager():
    """Mock 持仓管理器"""
    mock = MagicMock()
    mock._positions = {}
    
    def get_position(symbol):
        return mock._positions.get(symbol)
    
    def is_stale(symbol, max_age):
        pos = mock._positions.get(symbol)
        if not pos or not pos.open_timestamp:
            return False
        age_ms = int(time.time() * 1000) - pos.open_timestamp
        return age_ms / 1000 > max_age
    
    def get_age(symbol):
        pos = mock._positions.get(symbol)
        if not pos or not pos.open_timestamp:
            return 0.0
        age_ms = int(time.time() * 1000) - pos.open_timestamp
        return age_ms / 1000
    
    mock.get_position = get_position
    mock.is_position_stale = is_stale
    mock.get_position_age_seconds = get_age
    
    return mock


@pytest.fixture
def tp_sl_manager():
    """TP/SL 管理器"""
    return TPSLManager(take_profit_pct=0.02, stop_loss_pct=0.01)


@pytest.fixture
def mock_ioc_executor():
    """Mock IOC 执行器"""
    mock_api = AsyncMock()
    return IOCExecutor(
        api_client=mock_api,
        default_size=Decimal("0.01"),
        price_adjustment_bps=10.0,
    )


@pytest.fixture
def position_closer(tp_sl_manager, mock_position_manager, mock_ioc_executor):
    """平仓协调器"""
    return PositionCloser(
        tp_sl_manager=tp_sl_manager,
        position_manager=mock_position_manager,
        ioc_executor=mock_ioc_executor,
        max_position_age_seconds=1800.0,
    )


@pytest.fixture
def market_data():
    """市场数据工厂"""
    from src.core.types import Level
    
    def _create(symbol="ETH", mid_price=1500.0):
        spread = Decimal(str(mid_price * 0.0003))
        best_bid = Decimal(str(mid_price)) - spread / 2
        best_ask = Decimal(str(mid_price)) + spread / 2
        
        return MarketData(
            symbol=symbol,
            timestamp=int(time.time() * 1000),
            bids=[Level(price=best_bid, size=Decimal("50.0"))],
            asks=[Level(price=best_ask, size=Decimal("50.0"))],
            mid_price=Decimal(str(mid_price)),
        )
    
    return _create


# ==================== 测试用例 ====================


class TestPositionLifecycle:
    """持仓生命周期集成测试"""
    
    @pytest.mark.asyncio
    async def test_long_take_profit_flow(
        self, mock_position_manager, position_closer, market_data
    ):
        """测试多头止盈流程"""
        # 1. 创建多头持仓
        position = Position(
            symbol="ETH",
            size=Decimal("1.0"),
            entry_price=Decimal("1500.0"),
            unrealized_pnl=Decimal("0.0"),
            open_timestamp=int(time.time() * 1000),
        )
        mock_position_manager._positions["ETH"] = position
        
        # 2. Mock 平仓订单
        close_order = Order(
            id="close_001",
            symbol="ETH",
            side=OrderSide.SELL,
            order_type=OrderType.IOC,
            price=Decimal("1530.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=int(time.time() * 1000),
        )
        
        position_closer.ioc_executor.execute = AsyncMock(return_value=close_order)
        
        # 3. 价格上涨触发止盈
        md = market_data(symbol="ETH", mid_price=1530.0)
        closed = await position_closer.check_and_close_positions({"ETH": md})
        
        # 4. 验证
        assert len(closed) == 1
        assert position_closer.get_stats()["tp_triggers"] == 1
    
    @pytest.mark.asyncio
    async def test_timeout_closing_flow(
        self, mock_position_manager, position_closer, market_data
    ):
        """测试超时平仓流程"""
        # 1. 创建过期持仓
        old_time = int(time.time() * 1000) - int(1900 * 1000)  # 31.67 分钟前
        position = Position(
            symbol="ETH",
            size=Decimal("1.0"),
            entry_price=Decimal("1500.0"),
            unrealized_pnl=Decimal("0.0"),
            open_timestamp=old_time,
        )
        mock_position_manager._positions["ETH"] = position
        
        # 2. Mock 平仓订单
        close_order = Order(
            id="timeout_001",
            symbol="ETH",
            side=OrderSide.SELL,
            order_type=OrderType.IOC,
            price=Decimal("1500.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=int(time.time() * 1000),
        )
        
        position_closer.ioc_executor.execute = AsyncMock(return_value=close_order)
        
        # 3. 执行平仓检查
        md = market_data(symbol="ETH", mid_price=1500.0)
        closed = await position_closer.check_and_close_positions({"ETH": md})
        
        # 4. 验证
        assert len(closed) == 1
        assert position_closer.get_stats()["timeout_triggers"] == 1
    
    @pytest.mark.asyncio
    async def test_mixed_triggers(
        self, mock_position_manager, position_closer, market_data
    ):
        """测试混合触发场景"""
        # 1. 创建多个持仓
        eth_pos = Position(
            symbol="ETH",
            size=Decimal("1.0"),
            entry_price=Decimal("1500.0"),
            unrealized_pnl=Decimal("0.0"),
            open_timestamp=int(time.time() * 1000),
        )
        
        btc_pos = Position(
            symbol="BTC",
            size=Decimal("-0.5"),
            entry_price=Decimal("30000.0"),
            unrealized_pnl=Decimal("0.0"),
            open_timestamp=int(time.time() * 1000),
        )
        
        mock_position_manager._positions["ETH"] = eth_pos
        mock_position_manager._positions["BTC"] = btc_pos
        
        # 2. Mock 平仓订单
        async def mock_execute(signal_score, market_data, size=None):
            if market_data.symbol == "ETH":
                return Order(
                    id="eth_close",
                    symbol="ETH",
                    side=OrderSide.SELL,
                    order_type=OrderType.IOC,
                    price=Decimal("1530.0"),
                    size=Decimal("1.0"),
                    filled_size=Decimal("1.0"),
                    status=OrderStatus.FILLED,
                    created_at=int(time.time() * 1000),
                )
            else:
                return Order(
                    id="btc_close",
                    symbol="BTC",
                    side=OrderSide.BUY,
                    order_type=OrderType.IOC,
                    price=Decimal("30300.0"),
                    size=Decimal("0.5"),
                    filled_size=Decimal("0.5"),
                    status=OrderStatus.FILLED,
                    created_at=int(time.time() * 1000),
                )
        
        position_closer.ioc_executor.execute = AsyncMock(side_effect=mock_execute)
        
        # 3. 执行平仓检查
        market_dict = {
            "ETH": market_data(symbol="ETH", mid_price=1530.0),  # +2% TP
            "BTC": market_data(symbol="BTC", mid_price=30300.0),  # +1% SL
        }
        
        closed = await position_closer.check_and_close_positions(market_dict)
        
        # 4. 验证
        assert len(closed) == 2
        stats = position_closer.get_stats()
        assert stats["tp_triggers"] == 1
        assert stats["sl_triggers"] == 1
