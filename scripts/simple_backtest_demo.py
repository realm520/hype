#!/usr/bin/env python3
"""
简化版回测演示脚本

使用 DataReplayEngine 回放 8 小时历史数据，展示数据质量和回放功能。
"""

import sys
from pathlib import Path
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.data_replay import DataReplayEngine
from src.core.logging import setup_logging
import structlog

logger = structlog.get_logger(__name__)


def main():
    """主函数"""
    setup_logging()

    logger.info("simple_backtest_demo_starting")

    # 初始化数据回放引擎
    engine = DataReplayEngine(
        data_dir="data/market_data/test_8hour",
        replay_speed=100.0,  # 100倍速回放
        load_trades=False,  # 跳过trades数据以加快演示速度
    )

    # 加载数据
    logger.info("loading_historical_data")
    engine.load_data()

    # 开始回放
    logger.info("starting_replay")
    engine.start_replay()

    # 统计信息
    update_count = 0
    btc_count = 0
    eth_count = 0
    last_report_count = 0  # 记录上次报告的更新数，避免重复打印

    # 回放循环
    while not engine.is_finished():
        # 获取新的市场数据
        new_data = engine.update()

        if new_data:
            update_count += len(new_data)

            for market_data in new_data:
                if market_data.symbol == "BTC":
                    btc_count += 1
                    if btc_count % 10000 == 0:
                        logger.info(
                            "btc_snapshot",
                            timestamp=market_data.timestamp,
                            mid_price=float(market_data.mid_price),
                            spread_bps=float(
                                (market_data.asks[0].price - market_data.bids[0].price)
                                / market_data.mid_price * 10000
                            ) if market_data.asks and market_data.bids else 0,
                        )
                elif market_data.symbol == "ETH":
                    eth_count += 1

        # 每处理 50000 个更新打印进度（使用 >= 且只报告一次）
        if update_count >= last_report_count + 50000:
            last_report_count = update_count
            progress = engine.get_progress()
            logger.info(
                "replay_progress",
                updates_processed=update_count,
                progress_pct=f"{progress * 100:.1f}%",
            )

    # 最终统计
    logger.info(
        "replay_completed",
        total_updates=update_count,
        btc_snapshots=btc_count,
        eth_snapshots=eth_count,
    )

    print("\n" + "=" * 80)
    print("📊 8小时历史数据回放完成")
    print("=" * 80)
    print(f"\n总更新数: {update_count:,}")
    print(f"BTC 快照数: {btc_count:,}")
    print(f"ETH 快照数: {eth_count:,}")
    print("\n✅ 数据回放引擎工作正常！")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
