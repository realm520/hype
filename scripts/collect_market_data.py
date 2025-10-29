"""市场数据采集器

采集 Hyperliquid 实时市场数据并保存到 Parquet 文件，用于后续回测。

特性：
- L2 订单簿快照（10档）
- 成交数据（trades）
- 高压缩比存储（zstd）
- 实时进度显示
- 数据质量统计

用法：
    # 采集 10 分钟数据
    python scripts/collect_market_data.py --duration 600 --output data/market_data/test_10min.parquet

    # 采集 1 小时数据
    python scripts/collect_market_data.py --duration 3600 --output data/market_data/test_1hour.parquet

    # 采集 24 小时数据
    python scripts/collect_market_data.py --duration 86400 --output data/market_data/test_24hour.parquet
"""

import argparse
import asyncio
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl
import structlog

from src.core.data_feed import MarketDataManager
from src.core.incremental_saver import IncrementalSaver
from src.core.logging import setup_logging
from src.core.types import MarketData
from src.hyperliquid.websocket_client import HyperliquidWebSocket

logger = structlog.get_logger()


class MarketDataCollector:
    """市场数据采集器"""

    def __init__(
        self,
        symbols: list[str],
        duration: int,
        output_file: str,
    ):
        """
        初始化数据采集器

        Args:
            symbols: 交易对列表
            duration: 采集时长（秒）
            output_file: 输出文件路径
        """
        self.symbols = symbols
        self.duration = duration
        self.output_file = Path(output_file)

        # 使用 MarketDataManager 管理数据
        self.ws_client = HyperliquidWebSocket()
        self.data_manager = MarketDataManager(self.ws_client)

        # 增量保存器
        self.saver = IncrementalSaver(
            output_path=str(output_file),
            max_records=1000,  # 每 1000 条记录触发保存
            max_interval_seconds=60,  # 每 60 秒触发保存
        )

        # 数据缓冲区（保留用于统计和最终保存）
        self.l2_snapshots: list[dict[str, Any]] = []
        self.trades: list[dict[str, Any]] = []

        # 统计信息
        self.stats = {symbol: {"l2_updates": 0, "trades": 0} for symbol in symbols}
        self.start_time = 0.0
        self.stop_requested = False

        logger.info(
            "collector_initialized",
            symbols=symbols,
            duration=duration,
            output=str(output_file),
        )

    def _handle_signal(self, signum, frame):
        """处理中断信号"""
        logger.warning("interrupt_received", signal=signum)
        self.stop_requested = True

    async def collect(self):
        """采集数据"""
        # 注册信号处理器
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        logger.info("starting_collection")
        self.start_time = time.time()

        try:
            # 启动数据管理器（自动连接和订阅）
            await self.data_manager.start(self.symbols)
            logger.info("subscriptions_active", symbols=self.symbols)

            # 采集循环
            last_stats_time = time.time()
            last_save_time = time.time()
            save_interval = 60  # 每分钟保存一次

            while not self.stop_requested:
                elapsed = time.time() - self.start_time

                # 检查是否超时
                if elapsed >= self.duration:
                    logger.info("duration_reached", elapsed=elapsed)
                    break

                # 获取市场数据
                for symbol in self.symbols:
                    market_data = self.data_manager.get_market_data(symbol)
                    if market_data:
                        self._process_market_data(market_data)

                # 定期打印统计
                if time.time() - last_stats_time >= 10:
                    self._print_stats(elapsed)
                    last_stats_time = time.time()

                # 检查是否需要增量保存
                if await self.saver.save_if_needed():
                    buffer_size = self.saver.get_buffer_size()
                    logger.debug("incremental_save_triggered", buffer_size=buffer_size)

                await asyncio.sleep(0.1)  # 100ms 采集间隔

        except Exception as e:
            logger.error("collection_error", error=str(e), exc_info=True)
            raise
        finally:
            await self.ws_client.close()
            logger.info("websocket_closed")

        # 最终保存（使用增量保存器）
        await self._save_final()

    def _process_market_data(self, market_data: MarketData):
        """处理市场数据"""
        # L2 订单簿快照
        l2_snapshot = {
            "timestamp": market_data.timestamp,
            "symbol": market_data.symbol,
            "mid_price": float(market_data.mid_price),
            # 保存前 10 档
            "bids": [
                {"price": float(level.price), "size": float(level.size)}
                for level in market_data.bids[:10]
            ],
            "asks": [
                {"price": float(level.price), "size": float(level.size)}
                for level in market_data.asks[:10]
            ],
        }
        self.l2_snapshots.append(l2_snapshot)
        self.saver.add_l2_snapshot(l2_snapshot)  # 添加到增量保存器
        self.stats[market_data.symbol]["l2_updates"] += 1

        # 成交数据
        trades_data = []
        for trade in market_data.trades:
            trade_data = {
                "timestamp": trade.timestamp,
                "symbol": market_data.symbol,
                "side": trade.side.name,
                "price": float(trade.price),
                "size": float(trade.size),
            }
            self.trades.append(trade_data)
            trades_data.append(trade_data)
            self.stats[market_data.symbol]["trades"] += 1

        if trades_data:
            self.saver.add_trades(trades_data)  # 添加到增量保存器

    def _print_stats(self, elapsed: float):
        """打印统计信息"""
        total_l2 = sum(s["l2_updates"] for s in self.stats.values())
        total_trades = sum(s["trades"] for s in self.stats.values())
        progress = (elapsed / self.duration) * 100

        logger.info(
            "collection_progress",
            elapsed=f"{elapsed:.1f}s",
            progress=f"{progress:.1f}%",
            l2_snapshots=total_l2,
            trades=total_trades,
            memory_mb=len(self.l2_snapshots) * 0.001,  # 粗略估算
        )

        # 详细统计
        for symbol, stat in self.stats.items():
            logger.debug(
                "symbol_stats",
                symbol=symbol,
                l2_updates=stat["l2_updates"],
                trades=stat["trades"],
            )

    async def _save_incremental(self):
        """增量保存数据（现在由 IncrementalSaver 处理）"""
        # 此方法已被 IncrementalSaver 替代
        # 保留用于兼容性，实际保存由 saver.save_if_needed() 触发
        pass

    async def _save_final(self):
        """保存最终数据（使用增量保存器）"""
        logger.info("saving_final_data", output=str(self.output_file))

        # 创建输出目录
        self.output_file.parent.mkdir(parents=True, exist_ok=True)

        # 使用增量保存器最终化（保存剩余数据）
        saver_stats = await self.saver.finalize()

        # 保存元数据
        total_l2 = sum(s["l2_updates"] for s in self.stats.values())
        total_trades = sum(s["trades"] for s in self.stats.values())

        metadata = {
            "symbols": self.symbols,
            "duration_seconds": self.duration,
            "actual_duration_seconds": time.time() - self.start_time,
            "start_timestamp": int(self.start_time * 1000),
            "end_timestamp": int(time.time() * 1000),
            "stats": self.stats,
            "total_l2_snapshots": total_l2,
            "total_trades": total_trades,
            "saver_stats": saver_stats,
        }

        metadata_output = self.output_file.with_name(
            self.output_file.stem + "_metadata.json"
        )
        import json

        with open(metadata_output, "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info("metadata_saved", file=str(metadata_output))

        # 打印摘要
        logger.info(
            "collection_complete",
            total_l2_snapshots=saver_stats["total_l2_saved"],
            total_trades=saver_stats["total_trades_saved"],
            duration=f"{time.time() - self.start_time:.1f}s",
        )


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="采集 Hyperliquid 市场数据")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["BTC", "ETH"],
        help="交易对列表（默认: BTC ETH）",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=600,
        help="采集时长（秒，默认: 600 = 10分钟）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/market_data/test.parquet",
        help="输出文件路径（默认: data/market_data/test.parquet）",
    )

    args = parser.parse_args()

    # 设置日志
    setup_logging()

    logger.info(
        "starting_data_collection",
        symbols=args.symbols,
        duration=args.duration,
        output=args.output,
    )

    # 创建采集器
    collector = MarketDataCollector(
        symbols=args.symbols,
        duration=args.duration,
        output_file=args.output,
    )

    # 运行采集
    try:
        asyncio.run(collector.collect())
        logger.info("collection_finished_successfully")
        # 强制退出（因为 hyperliquid SDK 有非 daemon 线程）
        os._exit(0)
    except KeyboardInterrupt:
        logger.info("collection_interrupted_by_user")
        os._exit(0)
    except Exception as e:
        logger.error("collection_failed", error=str(e), exc_info=True)
        os._exit(1)


if __name__ == "__main__":
    main()
