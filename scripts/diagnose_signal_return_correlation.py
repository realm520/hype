#!/usr/bin/env python3
"""信号-收益相关性诊断工具

从日志中提取信号值和未来收益,分析相关性模式,
找出 IC 为负的根本原因。
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
from scipy import stats

# 可选的绘图功能
try:
    import matplotlib.pyplot as plt
    import numpy as np

    PLOTTING_AVAILABLE = True
except ImportError:
    PLOTTING_AVAILABLE = False
    print("⚠️  matplotlib 未安装,跳过绘图功能")

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class SignalReturnDiagnostic:
    """信号-收益诊断器"""

    def __init__(self, log_file: Path):
        """初始化

        Args:
            log_file: 日志文件路径
        """
        self.log_file = log_file
        self.signals: Dict[int, dict] = {}  # signal_id -> signal_data
        self.returns: Dict[int, float] = {}  # signal_id -> future_return

    def parse_log(self) -> None:
        """解析日志文件"""
        print(f"📖 解析日志: {self.log_file}")

        with open(self.log_file) as f:
            for line in f:
                try:
                    log = json.loads(line.strip())
                    event = log.get("event")

                    # 提取信号记录
                    if event == "signal_recorded":
                        signal_id = log.get("signal_id")
                        if signal_id is not None:
                            self.signals[signal_id] = {
                                "timestamp": log.get("timestamp"),
                                "symbol": log.get("symbol"),
                                "signal_value": log.get("signal_value"),
                                "confidence": log.get("confidence"),
                                "price": log.get("price"),
                            }

                    # 提取未来收益
                    elif event == "signal_return_updated":
                        signal_id = log.get("signal_id")
                        future_return = log.get("return_pct")
                        if signal_id is not None and future_return is not None:
                            self.returns[signal_id] = future_return / 100.0  # 转为小数

                except (json.JSONDecodeError, KeyError):
                    continue

        print(f"✅ 提取信号数: {len(self.signals)}")
        print(f"✅ 提取收益数: {len(self.returns)}")

    def create_paired_dataset(self) -> pd.DataFrame:
        """创建配对的信号-收益数据集

        Returns:
            DataFrame with columns: signal_id, symbol, signal_value, future_return
        """
        paired_data = []

        for signal_id, signal_data in self.signals.items():
            if signal_id in self.returns:
                paired_data.append(
                    {
                        "signal_id": signal_id,
                        "symbol": signal_data["symbol"],
                        "signal_value": signal_data["signal_value"],
                        "future_return": self.returns[signal_id],
                        "confidence": signal_data["confidence"],
                    }
                )

        df = pd.DataFrame(paired_data)
        print(f"\n📊 配对数据集大小: {len(df)}")
        return df

    def calculate_ic(self, df: pd.DataFrame) -> Dict[str, float]:
        """计算 IC 指标

        Args:
            df: 配对数据集

        Returns:
            IC 指标字典
        """
        if len(df) < 30:
            print("⚠️  样本量不足（<30）,IC 计算不可靠")
            return {}

        # 总体 IC
        ic, p_value = stats.spearmanr(df["signal_value"], df["future_return"])

        # 按币种分组 IC
        ic_by_symbol = {}
        for symbol in df["symbol"].unique():
            symbol_df = df[df["symbol"] == symbol]
            if len(symbol_df) >= 10:
                sym_ic, sym_p = stats.spearmanr(
                    symbol_df["signal_value"], symbol_df["future_return"]
                )
                ic_by_symbol[symbol] = {"ic": sym_ic, "p_value": sym_p}

        return {
            "overall_ic": ic,
            "overall_p_value": p_value,
            "sample_count": len(df),
            "by_symbol": ic_by_symbol,
        }

    def calculate_quantile_returns(self, df: pd.DataFrame, n_quantiles: int = 5) -> Dict:
        """计算分层收益

        Args:
            df: 配对数据集
            n_quantiles: 分层数量（默认 5）

        Returns:
            分层统计结果
        """
        # 按信号值分层
        df["quantile"] = pd.qcut(
            df["signal_value"], q=n_quantiles, labels=False, duplicates="drop"
        )

        quantile_stats = []
        for q in range(n_quantiles):
            q_df = df[df["quantile"] == q]
            if len(q_df) > 0:
                quantile_stats.append(
                    {
                        "quantile": q + 1,  # 1-based
                        "mean_signal": q_df["signal_value"].mean(),
                        "mean_return": q_df["future_return"].mean(),
                        "median_return": q_df["future_return"].median(),
                        "count": len(q_df),
                    }
                )

        stats_df = pd.DataFrame(quantile_stats)

        # 计算 Top-Bottom 差异
        if len(stats_df) >= 2:
            top_return = stats_df.iloc[-1]["mean_return"]
            bottom_return = stats_df.iloc[0]["mean_return"]
            spread = top_return - bottom_return
        else:
            spread = None

        return {"quantile_stats": stats_df, "top_bottom_spread": spread}

    def plot_scatter(self, df: pd.DataFrame, output_path: Path) -> None:
        """绘制信号-收益散点图

        Args:
            df: 配对数据集
            output_path: 输出图片路径
        """
        if not PLOTTING_AVAILABLE:
            print("⚠️  跳过散点图生成（matplotlib 不可用）")
            return

        plt.figure(figsize=(12, 8))

        # 按币种分组绘制
        symbols = df["symbol"].unique()
        colors = plt.cm.tab10(range(len(symbols)))

        for symbol, color in zip(symbols, colors):
            symbol_df = df[df["symbol"] == symbol]
            plt.scatter(
                symbol_df["signal_value"],
                symbol_df["future_return"],
                alpha=0.5,
                label=symbol,
                color=color,
                s=50,
            )

        # 添加趋势线
        z = np.polyfit(df["signal_value"], df["future_return"], 1)
        p = np.poly1d(z)
        x_line = np.linspace(df["signal_value"].min(), df["signal_value"].max(), 100)
        plt.plot(x_line, p(x_line), "r--", linewidth=2, label=f"趋势线 (slope={z[0]:.4f})")

        # 添加零线
        plt.axhline(y=0, color="gray", linestyle="--", alpha=0.3)
        plt.axvline(x=0, color="gray", linestyle="--", alpha=0.3)

        plt.xlabel("Signal Value", fontsize=12)
        plt.ylabel("Future Return", fontsize=12)
        plt.title("Signal-Return Scatter Plot", fontsize=14, fontweight="bold")
        plt.legend(loc="best", fontsize=10)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_path, dpi=150)
        print(f"\n📊 散点图已保存: {output_path}")

    def plot_quantile_returns(
        self, quantile_stats: pd.DataFrame, output_path: Path
    ) -> None:
        """绘制分层收益柱状图

        Args:
            quantile_stats: 分层统计 DataFrame
            output_path: 输出图片路径
        """
        if not PLOTTING_AVAILABLE:
            print("⚠️  跳过分层收益图生成（matplotlib 不可用）")
            return

        plt.figure(figsize=(10, 6))

        x = quantile_stats["quantile"]
        y = quantile_stats["mean_return"] * 100  # 转为百分比

        # 根据正负设置颜色
        colors = ["red" if v < 0 else "green" for v in y]
        plt.bar(x, y, color=colors, alpha=0.7, edgecolor="black")

        plt.xlabel("Signal Quantile (1=Bottom, 5=Top)", fontsize=12)
        plt.ylabel("Mean Future Return (%)", fontsize=12)
        plt.title("Quantile Returns", fontsize=14, fontweight="bold")
        plt.axhline(y=0, color="black", linestyle="-", linewidth=0.8)
        plt.grid(True, alpha=0.3, axis="y")
        plt.tight_layout()
        plt.savefig(output_path, dpi=150)
        print(f"📊 分层收益图已保存: {output_path}")

    def generate_report(self, output_dir: Path) -> None:
        """生成完整诊断报告

        Args:
            output_dir: 输出目录
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. 解析日志
        self.parse_log()

        # 2. 创建配对数据集
        df = self.create_paired_dataset()
        if df.empty:
            print("❌ 没有配对的信号-收益数据,无法生成报告")
            return

        # 保存原始数据
        data_file = output_dir / "signal_return_pairs.csv"
        df.to_csv(data_file, index=False)
        print(f"\n💾 原始数据已保存: {data_file}")

        # 3. 计算 IC
        ic_metrics = self.calculate_ic(df)
        print("\n" + "=" * 60)
        print("📈 IC 分析结果")
        print("=" * 60)
        print(f"总体 IC: {ic_metrics.get('overall_ic', 'N/A'):.4f}")
        print(f"P-value: {ic_metrics.get('overall_p_value', 'N/A'):.4e}")
        print(f"样本量: {ic_metrics.get('sample_count', 0)}")

        if "by_symbol" in ic_metrics:
            print("\n按币种分组 IC:")
            for symbol, metrics in ic_metrics["by_symbol"].items():
                print(f"  {symbol}: IC={metrics['ic']:.4f}, p={metrics['p_value']:.4e}")

        # 4. 分层收益
        quantile_results = self.calculate_quantile_returns(df)
        print("\n" + "=" * 60)
        print("📊 分层收益分析")
        print("=" * 60)
        print(quantile_results["quantile_stats"].to_string(index=False))
        if quantile_results["top_bottom_spread"] is not None:
            print(
                f"\nTop-Bottom Spread: {quantile_results['top_bottom_spread']*100:.2f}%"
            )

        # 5. 生成可视化
        scatter_plot = output_dir / "signal_return_scatter.png"
        self.plot_scatter(df, scatter_plot)

        quantile_plot = output_dir / "quantile_returns.png"
        self.plot_quantile_returns(quantile_results["quantile_stats"], quantile_plot)

        # 6. 保存 JSON 报告
        report = {
            "ic_metrics": ic_metrics,
            "quantile_stats": quantile_results["quantile_stats"].to_dict("records"),
            "top_bottom_spread": quantile_results["top_bottom_spread"],
            "sample_statistics": {
                "total_signals": len(self.signals),
                "total_returns": len(self.returns),
                "paired_samples": len(df),
                "symbols": df["symbol"].unique().tolist(),
            },
        }

        report_file = output_dir / "diagnostic_report.json"
        with open(report_file, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\n📄 诊断报告已保存: {report_file}")

        # 7. 关键发现
        print("\n" + "=" * 60)
        print("🔍 关键发现")
        print("=" * 60)

        overall_ic = ic_metrics.get("overall_ic", 0)
        p_value = ic_metrics.get("overall_p_value", 1)

        if overall_ic < -0.3:
            print("🚨 严重问题: IC 强负相关（<-0.3）")
            if p_value < 0.05:
                print("   → 统计显著,信号可能方向完全反了!")
                print("   → 建议: 检查信号定义和未来收益计算公式")
        elif overall_ic < -0.1:
            print("⚠️  中度问题: IC 负相关（-0.1 ~ -0.3）")
            print("   → 信号质量差,需要重新设计")
        elif overall_ic < 0.03:
            print("⚠️  轻度问题: IC 不达标（<0.03）")
            print("   → 信号预测能力弱,需要优化参数")
        else:
            print("✅ IC 达标（≥0.03）")

        # 检查 Top-Bottom spread
        spread = quantile_results.get("top_bottom_spread")
        if spread is not None:
            if spread < 0:
                print(f"\n🚨 异常: Top-Bottom Spread 为负（{spread*100:.2f}%）")
                print("   → 信号排序完全反向,强烈建议检查信号符号!")
            elif abs(spread) < 0.0008:  # 8 bps
                print(f"\n⚠️  问题: Spread 过小（{spread*100:.2f}% < 8 bps）")
                print("   → 信号区分度不够,无法覆盖交易成本")

        print("=" * 60)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="信号-收益相关性诊断")
    parser.add_argument(
        "--log-file",
        type=Path,
        default=Path("logs/trading.log"),
        help="日志文件路径",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/signal_diagnosis"),
        help="输出目录",
    )

    args = parser.parse_args()

    # 检查日志文件
    if not args.log_file.exists():
        print(f"❌ 日志文件不存在: {args.log_file}")
        sys.exit(1)

    # 运行诊断
    diagnostic = SignalReturnDiagnostic(args.log_file)
    diagnostic.generate_report(args.output_dir)

    print("\n✅ 诊断完成!")
    print(f"📁 结果保存在: {args.output_dir}")


if __name__ == "__main__":
    main()
