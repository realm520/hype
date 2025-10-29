"""增量数据保存器

支持定时和定量两种触发条件的增量保存，防止内存溢出和数据丢失。

特性：
- 双重触发条件：记录数量 OR 时间间隔
- 追加模式写入 Parquet（高效）
- 线程安全
- 自动内存清理
"""

import time
from pathlib import Path
from typing import Any

import polars as pl
import structlog

logger = structlog.get_logger()


class IncrementalSaver:
    """增量数据保存器"""

    def __init__(
        self,
        output_path: str,
        max_records: int = 1000,
        max_interval_seconds: int = 60,
    ):
        """
        初始化增量保存器

        Args:
            output_path: 输出文件路径（不含扩展名）
            max_records: 最大记录数（达到后触发保存）
            max_interval_seconds: 最大时间间隔（达到后触发保存）
        """
        self.output_path = Path(output_path)
        self.max_records = max_records
        self.max_interval_seconds = max_interval_seconds

        # 数据缓冲区
        self.l2_buffer: list[dict[str, Any]] = []
        self.trades_buffer: list[dict[str, Any]] = []

        # 时间追踪
        self.last_save_time = time.time()

        # 统计
        self.total_l2_saved = 0
        self.total_trades_saved = 0
        self.save_count = 0

        logger.info(
            "incremental_saver_initialized",
            output_path=str(output_path),
            max_records=max_records,
            max_interval_seconds=max_interval_seconds,
        )

    def add_l2_snapshot(self, snapshot: dict[str, Any]) -> None:
        """
        添加 L2 快照到缓冲区

        Args:
            snapshot: L2 快照数据
        """
        self.l2_buffer.append(snapshot)

    def add_trades(self, trades: list[dict[str, Any]]) -> None:
        """
        添加成交数据到缓冲区

        Args:
            trades: 成交数据列表
        """
        self.trades_buffer.extend(trades)

    def should_save(self) -> bool:
        """
        检查是否应该触发保存

        Returns:
            bool: 是否应该保存
        """
        # 检查记录数量
        if len(self.l2_buffer) >= self.max_records:
            logger.debug("save_triggered_by_record_count", count=len(self.l2_buffer))
            return True

        # 检查时间间隔
        elapsed = time.time() - self.last_save_time
        if elapsed >= self.max_interval_seconds:
            logger.debug("save_triggered_by_time_interval", elapsed=elapsed)
            return True

        return False

    async def save_if_needed(self) -> bool:
        """
        如果满足条件，执行保存

        Returns:
            bool: 是否执行了保存
        """
        if self.should_save():
            await self.save()
            return True
        return False

    async def save(self) -> None:
        """执行增量保存"""
        if not self.l2_buffer and not self.trades_buffer:
            logger.debug("no_data_to_save")
            return

        save_start = time.time()

        # 保存 L2 数据
        if self.l2_buffer:
            await self._save_l2()

        # 保存成交数据
        if self.trades_buffer:
            await self._save_trades()

        # 更新状态
        self.last_save_time = time.time()
        self.save_count += 1

        save_duration = time.time() - save_start
        logger.info(
            "incremental_save_completed",
            save_count=self.save_count,
            l2_saved=len(self.l2_buffer),
            trades_saved=len(self.trades_buffer),
            total_l2=self.total_l2_saved,
            total_trades=self.total_trades_saved,
            duration_ms=round(save_duration * 1000, 2),
        )

        # 清空缓冲区
        self.l2_buffer.clear()
        self.trades_buffer.clear()

    async def _save_l2(self) -> None:
        """保存 L2 数据"""
        l2_file = self.output_path.with_name(f"{self.output_path.stem}_l2.parquet")

        # 转换为 DataFrame
        df = pl.DataFrame(self.l2_buffer)

        # 追加模式写入
        if l2_file.exists():
            # 读取现有数据并追加
            existing_df = pl.read_parquet(l2_file)
            df = pl.concat([existing_df, df])

        # 保存
        df.write_parquet(l2_file, compression="zstd")

        self.total_l2_saved += len(self.l2_buffer)
        logger.debug("l2_data_saved", file=str(l2_file), rows=len(self.l2_buffer))

    async def _save_trades(self) -> None:
        """保存成交数据"""
        trades_file = self.output_path.with_name(
            f"{self.output_path.stem}_trades.parquet"
        )

        # 转换为 DataFrame
        df = pl.DataFrame(self.trades_buffer)

        # 追加模式写入
        if trades_file.exists():
            # 读取现有数据并追加
            existing_df = pl.read_parquet(trades_file)
            df = pl.concat([existing_df, df])

        # 保存
        df.write_parquet(trades_file, compression="zstd")

        self.total_trades_saved += len(self.trades_buffer)
        logger.debug(
            "trades_data_saved", file=str(trades_file), rows=len(self.trades_buffer)
        )

    async def finalize(self) -> dict[str, Any]:
        """
        最终保存（程序退出前调用）

        Returns:
            dict: 最终统计信息
        """
        logger.info("finalizing_incremental_saver")

        # 保存剩余数据
        if self.l2_buffer or self.trades_buffer:
            await self.save()

        stats = {
            "total_l2_saved": self.total_l2_saved,
            "total_trades_saved": self.total_trades_saved,
            "save_count": self.save_count,
        }

        logger.info("incremental_saver_finalized", stats=stats)
        return stats

    def get_buffer_size(self) -> dict[str, int]:
        """
        获取当前缓冲区大小

        Returns:
            dict: 缓冲区大小信息
        """
        return {
            "l2_buffer": len(self.l2_buffer),
            "trades_buffer": len(self.trades_buffer),
        }

    def get_stats(self) -> dict[str, Any]:
        """
        获取统计信息

        Returns:
            dict: 统计信息
        """
        return {
            "total_l2_saved": self.total_l2_saved,
            "total_trades_saved": self.total_trades_saved,
            "save_count": self.save_count,
            "buffer_size": self.get_buffer_size(),
            "time_since_last_save": time.time() - self.last_save_time,
        }
