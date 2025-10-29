"""统一数据源接口

提供抽象数据源接口，支持实时数据和回放数据，策略代码无需修改。
"""

from abc import ABC, abstractmethod

import structlog

from src.core.data_feed import MarketDataManager
from src.core.data_replay import DataReplayEngine
from src.core.types import MarketData
from src.hyperliquid.websocket_client import HyperliquidWebSocket

logger = structlog.get_logger()


class DataSource(ABC):
    """数据源抽象接口"""

    @abstractmethod
    async def connect(self):
        """连接数据源"""
        pass

    @abstractmethod
    async def close(self):
        """关闭数据源"""
        pass

    @abstractmethod
    async def subscribe(self, symbols: list[str]):
        """
        订阅交易对

        Args:
            symbols: 交易对列表
        """
        pass

    @abstractmethod
    def get_market_data(self, symbol: str) -> MarketData | None:
        """
        获取市场数据

        Args:
            symbol: 交易对

        Returns:
            MarketData: 市场数据，如果没有则返回 None
        """
        pass

    @abstractmethod
    async def update(self):
        """更新数据（用于回放引擎的时间推进）"""
        pass


class LiveDataSource(DataSource):
    """实时数据源（WebSocket）"""

    def __init__(self):
        """初始化实时数据源"""
        self.ws_client = HyperliquidWebSocket()
        self.data_manager = MarketDataManager(self.ws_client)
        self._subscribed_symbols: list[str] = []
        logger.info("live_data_source_initialized")

    async def connect(self):
        """连接 WebSocket（但不订阅，等待 subscribe 调用）"""
        # 不在这里连接，等待 subscribe 时统一处理
        logger.info("live_data_source_ready_to_connect")

    async def close(self):
        """关闭 WebSocket"""
        await self.ws_client.close()
        logger.info("live_data_source_closed")

    async def subscribe(self, symbols: list[str]):
        """订阅交易对（使用 MarketDataManager.start 批量订阅）"""
        self._subscribed_symbols = symbols
        # 使用 start() 方法批量订阅所有交易对
        await self.data_manager.start(symbols)
        logger.info("subscribed_to_symbols", symbols=symbols)

    def get_market_data(self, symbol: str) -> MarketData | None:
        """获取市场数据"""
        return self.data_manager.get_market_data(symbol)

    async def update(self):
        """实时数据源不需要主动更新"""
        pass


class ReplayDataSource(DataSource):
    """回放数据源（Parquet 文件）"""

    def __init__(self, data_path: str, replay_speed: float = 1.0):
        """
        初始化回放数据源

        Args:
            data_path: 数据文件路径（不含 _l2/_trades 后缀）
            replay_speed: 回放速度倍数
        """
        self.replay_engine = DataReplayEngine(data_path, replay_speed)
        logger.info(
            "replay_data_source_initialized",
            data_path=data_path,
            replay_speed=replay_speed,
        )

    async def connect(self):
        """加载数据文件"""
        self.replay_engine.load_data()
        self.replay_engine.start_replay()
        logger.info("replay_data_source_connected")

    async def close(self):
        """回放数据源无需关闭"""
        logger.info("replay_data_source_closed")

    async def subscribe(self, symbols: list[str]):
        """回放数据源不需要订阅"""
        logger.info("replay_subscribed", symbols=symbols)

    def get_market_data(self, symbol: str) -> MarketData | None:
        """获取市场数据"""
        return self.replay_engine.get_market_data(symbol)

    async def update(self):
        """更新回放状态"""
        self.replay_engine.update()

    def is_finished(self) -> bool:
        """检查回放是否结束"""
        return self.replay_engine.is_finished()

    def get_progress(self) -> float:
        """获取回放进度"""
        return self.replay_engine.get_progress()


def create_data_source(
    mode: str,
    replay_path: str | None = None,
    replay_speed: float = 1.0,
) -> DataSource:
    """
    创建数据源

    Args:
        mode: 数据源模式（"live" | "replay"）
        replay_path: 回放数据路径（mode="replay" 时必需）
        replay_speed: 回放速度倍数

    Returns:
        DataSource: 数据源实例
    """
    if mode == "live":
        return LiveDataSource()
    elif mode == "replay":
        if not replay_path:
            raise ValueError("replay_path is required for replay mode")
        return ReplayDataSource(replay_path, replay_speed)
    else:
        raise ValueError(f"Unknown data source mode: {mode}")
