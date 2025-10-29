"""数据回放引擎

从 Parquet 文件读取历史市场数据，按时间顺序回放，模拟实时数据流。

特性：
- 时间控制（加速、暂停、跳转）
- 内存高效（分块加载）
- 事件流生成（与实时数据接口一致）
"""

import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
import structlog

from src.core.types import Level, MarketData, Side, Trade

logger = structlog.get_logger()


class DataReplayEngine:
    """数据回放引擎"""

    def __init__(
        self,
        data_dir: str,
        replay_speed: float = 1.0,
    ):
        """
        初始化回放引擎

        Args:
            data_dir: 数据目录或文件前缀（不含 _l2/_trades 后缀）
            replay_speed: 回放速度倍数（1.0 = 实时，100.0 = 100倍加速）
        """
        self.data_path = Path(data_dir)
        self.replay_speed = replay_speed

        # 加载数据
        self.l2_df: pl.DataFrame | None = None
        self.trades_df: pl.DataFrame | None = None
        self.metadata: dict[str, Any] = {}

        # 回放状态
        self.current_index = 0
        self.start_timestamp = 0
        self.replay_start_time = 0.0
        self.is_paused = False

        # 当前市场数据缓存
        self._market_data_cache: dict[str, MarketData] = {}

        logger.info(
            "replay_engine_initialized",
            data_path=str(data_dir),
            replay_speed=replay_speed,
        )

    def load_data(self):
        """加载数据文件"""
        # 确定文件路径
        if self.data_path.is_dir():
            # 目录：查找最新的数据文件
            l2_files = sorted(self.data_path.glob("*_l2.parquet"))
            trades_files = sorted(self.data_path.glob("*_trades.parquet"))
            metadata_files = sorted(self.data_path.glob("*_metadata.json"))

            if not l2_files:
                raise FileNotFoundError(
                    f"No L2 data files found in {self.data_path}"
                )

            l2_path = l2_files[-1]
            trades_path = trades_files[-1] if trades_files else None
            metadata_path = metadata_files[-1] if metadata_files else None
        else:
            # 文件前缀
            l2_path = Path(str(self.data_path) + "_l2.parquet")
            trades_path = Path(str(self.data_path) + "_trades.parquet")
            metadata_path = Path(str(self.data_path) + "_metadata.json")

        # 加载 L2 数据
        if not l2_path.exists():
            raise FileNotFoundError(f"L2 data file not found: {l2_path}")

        logger.info("loading_l2_data", file=str(l2_path))
        self.l2_df = pl.read_parquet(l2_path)

        # 加载 Trades 数据
        if trades_path and trades_path.exists():
            logger.info("loading_trades_data", file=str(trades_path))
            self.trades_df = pl.read_parquet(trades_path)
        else:
            logger.warning("no_trades_data_found")

        # 加载元数据
        if metadata_path and metadata_path.exists():
            import json

            with open(metadata_path) as f:
                self.metadata = json.load(f)
            logger.info("metadata_loaded", metadata=self.metadata)

        # 按时间戳排序
        self.l2_df = self.l2_df.sort("timestamp")
        if self.trades_df is not None:
            self.trades_df = self.trades_df.sort("timestamp")

        # 设置起始时间戳
        self.start_timestamp = self.l2_df["timestamp"][0]

        logger.info(
            "data_loaded",
            l2_rows=len(self.l2_df),
            trades_rows=len(self.trades_df) if self.trades_df is not None else 0,
            start_timestamp=self.start_timestamp,
            duration_seconds=(
                self.l2_df["timestamp"][-1] - self.start_timestamp
            )
            / 1000,
        )

    def start_replay(self):
        """开始回放"""
        if self.l2_df is None:
            raise RuntimeError("Data not loaded. Call load_data() first.")

        self.replay_start_time = time.time()
        self.current_index = 0
        logger.info("replay_started", replay_speed=self.replay_speed)

    def update(self) -> list[MarketData]:
        """
        更新回放状态，返回当前时间点的市场数据

        Returns:
            List[MarketData]: 当前时间点的市场数据列表
        """
        if self.is_paused or self.l2_df is None:
            return []

        # 计算当前回放时间戳
        elapsed_real_time = (time.time() - self.replay_start_time) * 1000  # 毫秒
        elapsed_replay_time = elapsed_real_time * self.replay_speed
        current_timestamp = self.start_timestamp + int(elapsed_replay_time)

        # 收集当前时间戳之前的所有数据
        new_data: list[MarketData] = []

        while self.current_index < len(self.l2_df):
            row = self.l2_df.row(self.current_index, named=True)
            timestamp = row["timestamp"]

            if timestamp > current_timestamp:
                break

            # 解析 L2 数据
            market_data = self._parse_l2_snapshot(row)

            # 添加对应的 trades
            if self.trades_df is not None:
                trades = self._get_trades_at_timestamp(timestamp, row["symbol"])
                market_data.trades = trades

            new_data.append(market_data)
            self._market_data_cache[market_data.symbol] = market_data

            self.current_index += 1

        return new_data

    def get_market_data(self, symbol: str) -> MarketData | None:
        """
        获取指定交易对的最新市场数据

        Args:
            symbol: 交易对

        Returns:
            MarketData: 市场数据，如果没有则返回 None
        """
        return self._market_data_cache.get(symbol)

    def _parse_l2_snapshot(self, row: dict[str, Any]) -> MarketData:
        """解析 L2 快照"""
        # 解析 bids
        bids = []
        for bid in row["bids"]:
            bids.append(
                Level(
                    price=Decimal(str(bid["price"])),
                    size=Decimal(str(bid["size"])),
                )
            )

        # 解析 asks
        asks = []
        for ask in row["asks"]:
            asks.append(
                Level(
                    price=Decimal(str(ask["price"])),
                    size=Decimal(str(ask["size"])),
                )
            )

        return MarketData(
            symbol=row["symbol"],
            timestamp=row["timestamp"],
            bids=bids,
            asks=asks,
            mid_price=Decimal(str(row["mid_price"])),
            trades=[],
        )

    def _get_trades_at_timestamp(
        self, timestamp: int, symbol: str
    ) -> list[Trade]:
        """获取指定时间戳的成交数据"""
        if self.trades_df is None:
            return []

        # 使用 Polars 过滤（高效）
        trades_filtered = self.trades_df.filter(
            (pl.col("timestamp") == timestamp) & (pl.col("symbol") == symbol)
        )

        trades = []
        for row in trades_filtered.iter_rows(named=True):
            trades.append(
                Trade(
                    timestamp=row["timestamp"],
                    side=Side[row["side"]],
                    price=Decimal(str(row["price"])),
                    size=Decimal(str(row["size"])),
                )
            )

        return trades

    def is_finished(self) -> bool:
        """检查回放是否结束"""
        return self.current_index >= len(self.l2_df) if self.l2_df else True

    def get_progress(self) -> float:
        """获取回放进度（0.0 - 1.0）"""
        if self.l2_df is None or len(self.l2_df) == 0:
            return 1.0
        return self.current_index / len(self.l2_df)

    def pause(self):
        """暂停回放"""
        self.is_paused = True
        logger.info("replay_paused")

    def resume(self):
        """恢复回放"""
        self.is_paused = False
        # 调整起始时间以补偿暂停时间
        self.replay_start_time = time.time() - (
            (self.current_index / len(self.l2_df))
            * (self.l2_df["timestamp"][-1] - self.start_timestamp)
            / 1000
            / self.replay_speed
        )
        logger.info("replay_resumed")

    def get_stats(self) -> dict[str, Any]:
        """获取回放统计信息"""
        if self.l2_df is None:
            return {}

        return {
            "current_index": self.current_index,
            "total_rows": len(self.l2_df),
            "progress": self.get_progress(),
            "is_finished": self.is_finished(),
            "is_paused": self.is_paused,
            "replay_speed": self.replay_speed,
        }
