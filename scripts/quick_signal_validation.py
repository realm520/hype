#!/usr/bin/env python3
"""快速信号质量验证

基于采集的市场数据，计算信号的 IC（信息系数）和方向性预测能力。
"""

import argparse
import sys
from pathlib import Path
from decimal import Decimal

import polars as pl
import structlog

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.logging import setup_logging
from src.core.orderbook import OrderBook
from src.core.types import Level, OrderBookSnapshot
from src.signals.obi import OBISignal
from src.signals.microprice import MicropriceSignal
from src.signals.impact import ImpactSignal

logger = structlog.get_logger(__name__)


def load_data(data_prefix: str) -> tuple[pl.DataFrame, pl.DataFrame]:
    """加载市场数据"""
    l2_file = f"{data_prefix}_l2.parquet"
    trades_file = f"{data_prefix}_trades.parquet"

    logger.info("loading_data", l2_file=l2_file, trades_file=trades_file)

    l2_df = pl.read_parquet(l2_file)
    trades_df = pl.read_parquet(trades_file)

    logger.info(
        "data_loaded",
        l2_rows=len(l2_df),
        trades_rows=len(trades_df),
        symbols=l2_df["symbol"].unique().to_list(),
    )

    return l2_df, trades_df


def reconstruct_orderbook(row: dict) -> OrderBookSnapshot:
    """从数据行重建订单簿快照"""
    bids = []
    asks = []

    # 解析 bids（已是结构化数据）
    if 'bids' in row and row['bids'] is not None:
        for level in row['bids']:
            if level and 'price' in level and 'size' in level:
                price = level['price']
                size = level['size']
                if price is not None and size is not None and price > 0 and size > 0:
                    bids.append(Level(price=Decimal(str(price)), size=Decimal(str(size))))

    # 解析 asks（已是结构化数据）
    if 'asks' in row and row['asks'] is not None:
        for level in row['asks']:
            if level and 'price' in level and 'size' in level:
                price = level['price']
                size = level['size']
                if price is not None and size is not None and price > 0 and size > 0:
                    asks.append(Level(price=Decimal(str(price)), size=Decimal(str(size))))

    if not bids or not asks:
        return None

    mid_price = (bids[0].price + asks[0].price) / Decimal("2")

    return OrderBookSnapshot(
        symbol=row["symbol"],
        timestamp=row["timestamp"],
        bids=bids,
        asks=asks,
        mid_price=mid_price,
    )


def calculate_future_returns(
    l2_df: pl.DataFrame, symbol: str, window_minutes: list[int] = [1, 5, 10, 15]
) -> pl.DataFrame:
    """计算未来收益率（支持多窗口）

    Args:
        l2_df: L2 数据
        symbol: 交易对
        window_minutes: 窗口大小列表（分钟），默认 [1, 5, 10, 15]

    Returns:
        包含多窗口未来收益率的 DataFrame
    """
    # 筛选指定交易对
    symbol_df = l2_df.filter(pl.col("symbol") == symbol).sort("timestamp")

    # 数据已包含 mid_price，无需重新计算
    
    # 为每个窗口计算未来收益率
    for window in window_minutes:
        window_ms = window * 60 * 1000
        
        # 简化实现：使用 shift(-N) 近似未来价格
        # N = window_minutes (假设 1 快照/100ms ≈ 600 快照/分钟)
        shift_steps = max(1, int(window * 600 * 0.1))  # 保守估计，取 10% 的理论快照数
        
        symbol_df = symbol_df.with_columns(
            [
                pl.col("mid_price")
                .shift(-shift_steps)
                .alias(f"future_price_{window}m"),
            ]
        )
        
        # 计算收益率（bps）
        symbol_df = symbol_df.with_columns(
            [
                (
                    (pl.col(f"future_price_{window}m") - pl.col("mid_price"))
                    / pl.col("mid_price")
                    * 10000  # 转换为 bps
                ).alias(f"future_return_{window}m_bps"),
            ]
        )

    return symbol_df


def calculate_signal_ic(
    signal_values: list[float], future_returns: list[float]
) -> dict:
    """计算信号的 IC（Spearman 相关系数）"""
    import numpy as np
    from scipy.stats import spearmanr

    # 过滤 NaN/None 值（强制转换为 float）
    valid_pairs = []
    for s, r in zip(signal_values, future_returns):
        try:
            s_float = float(s) if s is not None else float('nan')
            r_float = float(r) if r is not None else float('nan')
            if not (np.isnan(s_float) or np.isnan(r_float) or np.isinf(s_float) or np.isinf(r_float)):
                valid_pairs.append((s_float, r_float))
        except (TypeError, ValueError):
            continue

    if len(valid_pairs) < 10:
        return {
            "ic": 0.0,
            "p_value": 1.0,
            "valid_samples": len(valid_pairs),
            "total_samples": len(signal_values),
        }

    signals, returns = zip(*valid_pairs)

    ic, p_value = spearmanr(signals, returns)

    return {
        "ic": float(ic) if not np.isnan(ic) else 0.0,
        "p_value": float(p_value) if not np.isnan(p_value) else 1.0,
        "valid_samples": len(valid_pairs),
        "total_samples": len(signal_values),
    }


def validate_signals(l2_df: pl.DataFrame, symbol: str, windows: list[int] = [1, 5, 10, 15]) -> dict:
    """验证信号质量（支持多窗口）"""
    logger.info("validating_signals", symbol=symbol, windows=windows)

    # 计算多窗口未来收益率
    data_with_returns = calculate_future_returns(l2_df, symbol, window_minutes=windows)

    # 初始化信号
    obi_signal = OBISignal(levels=5, weight=0.4)
    microprice_signal = MicropriceSignal(weight=0.3)
    impact_signal = ImpactSignal(window_ms=100, weight=0.3)

    # 计算信号值
    signal_results = []

    for row in data_with_returns.iter_rows(named=True):
        # 重建订单簿
        orderbook = reconstruct_orderbook(row)
        if orderbook is None:
            continue

        # 计算信号
        try:
            obi_value = obi_signal.calculate(orderbook)
            microprice_value = microprice_signal.calculate(orderbook)
            # Impact 信号需要历史数据，暂时跳过

            result = {
                "timestamp": row["timestamp"],
                "obi": obi_value,
                "microprice": microprice_value,
            }
            
            # 添加各窗口的未来收益率
            for window in windows:
                result[f"future_return_{window}m_bps"] = row.get(f"future_return_{window}m_bps")
            
            signal_results.append(result)
        except Exception as e:
            logger.warning("signal_calculation_failed", error=str(e))
            continue

    # 转换为 DataFrame
    signals_df = pl.DataFrame(signal_results)

    # 计算每个信号在各窗口的 IC
    results = {}

    for signal_name in ["obi", "microprice"]:
        signal_values = signals_df[signal_name].to_list()
        results[signal_name] = {}
        
        for window in windows:
            future_returns = signals_df[f"future_return_{window}m_bps"].to_list()
            ic_results = calculate_signal_ic(signal_values, future_returns)
            results[signal_name][f"{window}m"] = ic_results

            logger.info(
                "signal_ic_calculated",
                signal=signal_name,
                window=f"{window}m",
                ic=ic_results["ic"],
                p_value=ic_results["p_value"],
                valid_samples=ic_results["valid_samples"],
            )

    return results


def main():
    parser = argparse.ArgumentParser(description="快速信号质量验证")
    parser.add_argument(
        "--data",
        required=True,
        help="数据文件前缀（例如：data/market_data/test_10min_20251029_1336）",
    )
    parser.add_argument("--output", help="输出报告路径")

    args = parser.parse_args()

    # 初始化日志
    setup_logging()

    logger.info("starting_signal_validation", data_prefix=args.data)

    # 加载数据
    l2_df, trades_df = load_data(args.data)

    # 获取所有交易对
    symbols = l2_df["symbol"].unique().to_list()

    # 验证每个交易对的信号
    all_results = {}
    for symbol in symbols:
        try:
            results = validate_signals(l2_df, symbol)
            all_results[symbol] = results
        except Exception as e:
            logger.error(
                "symbol_validation_failed", symbol=symbol, error=str(e), exc_info=True
            )

    # 输出结果摘要
    logger.info("=== 信号质量验证结果（多窗口）===")
    for symbol, results in all_results.items():
        logger.info(f"--- {symbol} ---")
        for signal_name, window_results in results.items():
            logger.info(f"  {signal_name}:")
            for window, ic_results in window_results.items():
                ic = ic_results["ic"]
                p_value = ic_results["p_value"]
                valid_samples = ic_results["valid_samples"]

                # 判断信号质量
                if ic >= 0.03 and p_value < 0.01:
                    quality = "✅ 优秀"
                elif ic >= 0.01 and p_value < 0.05:
                    quality = "✓ 良好"
                elif ic > 0:
                    quality = "⚠️ 需改进"
                else:
                    quality = "❌ 无效"

                logger.info(
                    f"    {window}: IC={ic:.4f}, p-value={p_value:.4f}, "
                    f"样本={valid_samples} {quality}"
                )

    # 保存结果
    if args.output:
        import json

        with open(args.output, "w") as f:
            json.dump(all_results, f, indent=2)
        logger.info("results_saved", file=args.output)

    logger.info("validation_complete")


if __name__ == "__main__":
    main()
