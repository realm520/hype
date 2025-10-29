"""TradingEngine 核心逻辑测试（简化版）

专注于可快速验证的关键路径，提升覆盖率到 75%
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.main import TradingEngine


@pytest.fixture
def mock_api_client():
    """Mock Hyperliquid API 客户端"""
    mock = MagicMock()
    mock.exchange = MagicMock()
    return mock


class TestTradingEngineInit:
    """引擎初始化测试（P0）"""

    def test_engine_initializes_successfully(self, test_config, mock_api_client):
        """验证引擎成功初始化所有组件"""
        with patch("src.main.HyperliquidAPIClient", return_value=mock_api_client):
            engine = TradingEngine(test_config)

            # 验证：所有核心组件已初始化
            assert engine.data_feed is not None
            assert engine.market_data_manager is not None
            assert engine.signal_aggregator is not None
            assert engine.api_client is not None
            assert engine.executor is not None
            assert engine.order_manager is not None
            assert engine.hard_limits is not None
            assert engine.position_manager is not None
            assert engine.pnl_attribution is not None
            assert engine.metrics_collector is not None


class TestEngineStartStop:
    """引擎启动/停止测试（P1）"""

    @pytest.mark.asyncio
    async def test_start_sets_running_flag(self, test_config, mock_api_client):
        """验证 start() 设置运行标志"""
        with patch("src.main.HyperliquidAPIClient", return_value=mock_api_client):
            engine = TradingEngine(test_config)

            # Mock 数据流启动
            with patch.object(engine.data_feed, "start", new_callable=AsyncMock):
                await engine.start()

                # 验证：运行标志已设置
                assert engine._running is True

    @pytest.mark.asyncio
    async def test_stop_clears_running_flag(self, test_config, mock_api_client):
        """验证 stop() 清除运行标志"""
        with patch("src.main.HyperliquidAPIClient", return_value=mock_api_client):
            engine = TradingEngine(test_config)

            # 先启动
            with patch.object(engine.data_feed, "start", new_callable=AsyncMock):
                await engine.start()

            # 停止
            with patch.object(engine.data_feed, "close", new_callable=AsyncMock):
                await engine.stop()

                # 验证：运行标志已清除
                assert engine._running is False

    @pytest.mark.asyncio
    async def test_stop_closes_data_feed(self, test_config, mock_api_client):
        """验证 stop() 关闭数据流"""
        with patch("src.main.HyperliquidAPIClient", return_value=mock_api_client):
            engine = TradingEngine(test_config)

            # 先启动
            with patch.object(engine.data_feed, "start", new_callable=AsyncMock):
                await engine.start()

            # Mock 数据流关闭
            with patch.object(
                engine.data_feed, "close", new_callable=AsyncMock
            ) as mock_close:
                await engine.stop()

                # 验证：数据流已关闭
                mock_close.assert_called_once()
