#!/usr/bin/env python3
"""
数据质量分析工具

分析收集的市场数据质量，生成详细报告：
- 时间戳连续性检查
- 价格异常检测
- 数据量统计
- 订单簿健康度评估
"""

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

import polars as pl
import structlog

# 设置日志
logger = structlog.get_logger(__name__)


class DataQualityAnalyzer:
    """数据质量分析器"""

    def __init__(self, data_prefix: str):
        """
        初始化分析器

        Args:
            data_prefix: 数据文件前缀（不含扩展名）
        """
        self.data_prefix = Path(data_prefix)
        self.l2_file = self.data_prefix.with_name(f"{self.data_prefix.stem}_l2.parquet")
        self.trades_file = self.data_prefix.with_name(
            f"{self.data_prefix.stem}_trades.parquet"
        )
        self.metadata_file = self.data_prefix.with_name(
            f"{self.data_prefix.stem}_metadata.json"
        )

        self.l2_data: pl.DataFrame | None = None
        self.trades_data: pl.DataFrame | None = None
        self.metadata: dict | None = None

    def load_data(self) -> None:
        """加载数据文件"""
        logger.info("loading_data_files", prefix=str(self.data_prefix))

        # 加载 L2 数据
        if self.l2_file.exists():
            self.l2_data = pl.read_parquet(self.l2_file)
            logger.info("l2_data_loaded", rows=len(self.l2_data))
        else:
            logger.warning("l2_file_not_found", file=str(self.l2_file))

        # 加载交易数据
        if self.trades_file.exists():
            self.trades_data = pl.read_parquet(self.trades_file)
            logger.info("trades_data_loaded", rows=len(self.trades_data))
        else:
            logger.warning("trades_file_not_found", file=str(self.trades_file))

        # 加载元数据
        if self.metadata_file.exists():
            with open(self.metadata_file) as f:
                self.metadata = json.load(f)
            logger.info("metadata_loaded", symbols=self.metadata.get("symbols"))
        else:
            logger.warning("metadata_file_not_found", file=str(self.metadata_file))

    def analyze_timestamp_continuity(self) -> Dict:
        """分析时间戳连续性"""
        if self.l2_data is None or len(self.l2_data) == 0:
            return {"error": "No L2 data available"}

        # 按 symbol 分组分析
        results = {}
        for symbol in self.l2_data["symbol"].unique():
            symbol_data = self.l2_data.filter(pl.col("symbol") == symbol).sort(
                "timestamp"
            )

            if len(symbol_data) < 2:
                continue

            # 计算时间戳间隔（毫秒）
            timestamps = symbol_data["timestamp"].to_list()
            gaps = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]

            # 统计
            avg_gap = sum(gaps) / len(gaps) if gaps else 0
            max_gap = max(gaps) if gaps else 0
            min_gap = min(gaps) if gaps else 0

            # 检测异常跳跃（> 5 秒）
            abnormal_gaps = [g for g in gaps if g > 5000]

            results[symbol] = {
                "total_snapshots": len(symbol_data),
                "avg_gap_ms": round(avg_gap, 2),
                "max_gap_ms": max_gap,
                "min_gap_ms": min_gap,
                "abnormal_gaps_count": len(abnormal_gaps),
                "abnormal_gaps": abnormal_gaps[:10],  # 最多显示 10 个
            }

        return results

    def analyze_price_anomalies(self) -> Dict:
        """分析价格异常"""
        if self.l2_data is None or len(self.l2_data) == 0:
            return {"error": "No L2 data available"}

        results = {}
        for symbol in self.l2_data["symbol"].unique():
            symbol_data = self.l2_data.filter(pl.col("symbol") == symbol).sort(
                "timestamp"
            )

            if len(symbol_data) < 2:
                continue

            # 提取中价
            mid_prices = symbol_data["mid_price"].to_list()

            # 计算价格变动百分比
            price_changes = []
            for i in range(len(mid_prices) - 1):
                if mid_prices[i] > 0:
                    change_pct = (
                        (mid_prices[i + 1] - mid_prices[i]) / mid_prices[i] * 100
                    )
                    price_changes.append(change_pct)

            # 统计
            if price_changes:
                avg_change = sum(price_changes) / len(price_changes)
                max_change = max(price_changes)
                min_change = min(price_changes)
                volatility = (
                    sum((x - avg_change) ** 2 for x in price_changes)
                    / len(price_changes)
                ) ** 0.5

                # 检测异常波动（> 1%）
                abnormal_changes = [c for c in price_changes if abs(c) > 1.0]
            else:
                avg_change = max_change = min_change = volatility = 0
                abnormal_changes = []

            results[symbol] = {
                "avg_price": round(sum(mid_prices) / len(mid_prices), 2),
                "max_price": round(max(mid_prices), 2),
                "min_price": round(min(mid_prices), 2),
                "avg_change_pct": round(avg_change, 4),
                "max_change_pct": round(max_change, 4),
                "min_change_pct": round(min_change, 4),
                "volatility_pct": round(volatility, 4),
                "abnormal_changes_count": len(abnormal_changes),
            }

        return results

    def analyze_orderbook_health(self) -> Dict:
        """分析订单簿健康度"""
        if self.l2_data is None or len(self.l2_data) == 0:
            return {"error": "No L2 data available"}

        results = {}
        for symbol in self.l2_data["symbol"].unique():
            symbol_data = self.l2_data.filter(pl.col("symbol") == symbol)

            # 检查 bid/ask spread
            spreads = []
            bid_ask_inversions = 0

            for row in symbol_data.iter_rows(named=True):
                bids = row.get("bids", [])
                asks = row.get("asks", [])

                if bids and asks:
                    best_bid = bids[0]["price"]
                    best_ask = asks[0]["price"]

                    spread = best_ask - best_bid
                    spreads.append(spread)

                    # 检测 bid/ask 倒挂
                    if best_bid >= best_ask:
                        bid_ask_inversions += 1

            # 统计
            if spreads:
                avg_spread = sum(spreads) / len(spreads)
                max_spread = max(spreads)
                min_spread = min(spreads)
            else:
                avg_spread = max_spread = min_spread = 0

            results[symbol] = {
                "total_snapshots": len(symbol_data),
                "avg_spread": round(avg_spread, 4),
                "max_spread": round(max_spread, 4),
                "min_spread": round(min_spread, 4),
                "bid_ask_inversions": bid_ask_inversions,
            }

        return results

    def analyze_trade_data(self) -> Dict:
        """分析交易数据"""
        if self.trades_data is None or len(self.trades_data) == 0:
            return {"error": "No trade data available"}

        results = {}
        for symbol in self.trades_data["symbol"].unique():
            symbol_trades = self.trades_data.filter(pl.col("symbol") == symbol).sort(
                "timestamp"
            )

            # 统计买卖方向
            buy_trades = symbol_trades.filter(pl.col("side") == "BUY")
            sell_trades = symbol_trades.filter(pl.col("side") == "SELL")

            # 计算交易密度（每秒交易数）
            if len(symbol_trades) > 0:
                timestamps = symbol_trades["timestamp"].to_list()
                duration_ms = timestamps[-1] - timestamps[0]
                duration_s = duration_ms / 1000 if duration_ms > 0 else 1
                trades_per_second = len(symbol_trades) / duration_s
            else:
                trades_per_second = 0

            # 统计交易量
            total_volume = symbol_trades["size"].sum()
            buy_volume = buy_trades["size"].sum() if len(buy_trades) > 0 else 0
            sell_volume = sell_trades["size"].sum() if len(sell_trades) > 0 else 0

            results[symbol] = {
                "total_trades": len(symbol_trades),
                "buy_trades": len(buy_trades),
                "sell_trades": len(sell_trades),
                "buy_sell_ratio": (
                    round(len(buy_trades) / len(sell_trades), 2)
                    if len(sell_trades) > 0
                    else 0
                ),
                "trades_per_second": round(trades_per_second, 2),
                "total_volume": round(float(total_volume), 4),
                "buy_volume": round(float(buy_volume), 4),
                "sell_volume": round(float(sell_volume), 4),
            }

        return results

    def generate_report(self) -> Dict:
        """生成完整的数据质量报告"""
        logger.info("generating_quality_report")

        report = {
            "metadata": self.metadata,
            "timestamp_continuity": self.analyze_timestamp_continuity(),
            "price_anomalies": self.analyze_price_anomalies(),
            "orderbook_health": self.analyze_orderbook_health(),
            "trade_analysis": self.analyze_trade_data(),
        }

        # 计算总体质量评分（0-100）
        quality_score = self._calculate_quality_score(report)
        report["overall_quality_score"] = quality_score

        logger.info("quality_report_generated", quality_score=quality_score)
        return report

    def _calculate_quality_score(self, report: Dict) -> float:
        """
        计算数据质量评分

        评分标准：
        - 时间戳连续性（30 分）：异常跳跃少
        - 价格合理性（30 分）：异常波动少
        - 订单簿健康度（20 分）：无 bid/ask 倒挂
        - 数据完整性（20 分）：有足够的数据量
        """
        score = 100.0

        # 时间戳连续性评分
        timestamp_data = report.get("timestamp_continuity", {})
        for symbol_data in timestamp_data.values():
            if isinstance(symbol_data, dict):
                abnormal_gaps = symbol_data.get("abnormal_gaps_count", 0)
                total_snapshots = symbol_data.get("total_snapshots", 1)
                if total_snapshots > 0:
                    gap_penalty = min(30, (abnormal_gaps / total_snapshots) * 100)
                    score -= gap_penalty

        # 价格异常评分
        price_data = report.get("price_anomalies", {})
        for symbol_data in price_data.values():
            if isinstance(symbol_data, dict):
                abnormal_changes = symbol_data.get("abnormal_changes_count", 0)
                # 每个异常扣 1 分，最多扣 30 分
                score -= min(30, abnormal_changes)

        # 订单簿健康评分
        orderbook_data = report.get("orderbook_health", {})
        for symbol_data in orderbook_data.values():
            if isinstance(symbol_data, dict):
                inversions = symbol_data.get("bid_ask_inversions", 0)
                # 任何 bid/ask 倒挂都扣 20 分
                if inversions > 0:
                    score -= 20

        # 数据完整性评分
        if self.metadata:
            expected_duration = self.metadata.get("duration_seconds", 60)
            actual_duration = self.metadata.get("actual_duration_seconds", 0)
            if expected_duration > 0:
                completeness = actual_duration / expected_duration
                if completeness < 0.95:
                    score -= (1 - completeness) * 20

        return max(0.0, min(100.0, score))


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="分析市场数据质量并生成报告",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--data",
        required=True,
        help="数据文件前缀（例如：data/market_data/test_1min）",
    )
    parser.add_argument(
        "--output",
        help="输出报告文件路径（JSON 格式）",
    )

    args = parser.parse_args()

    # 创建分析器
    analyzer = DataQualityAnalyzer(args.data)

    # 加载数据
    analyzer.load_data()

    # 生成报告
    report = analyzer.generate_report()

    # 输出报告
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)

        logger.info("report_saved", file=str(output_path))
    else:
        # 打印到控制台
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
