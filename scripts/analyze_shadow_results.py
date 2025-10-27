"""影子交易结果分析脚本

从保存的执行记录中生成详细的分析报告。
可以在影子交易运行期间或结束后运行。

用法：
    # 分析最新的checkpoint
    python scripts/analyze_shadow_results.py

    # 分析指定的记录文件
    python scripts/analyze_shadow_results.py --file data/shadow_trading/final_records_20250125_120000.parquet

    # 生成 HTML 报告
    python scripts/analyze_shadow_results.py --format html
"""

import argparse
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime
import pandas as pd
import structlog

logger = structlog.get_logger()


def find_latest_records(data_dir: Path) -> Path:
    """查找最新的执行记录文件"""
    parquet_files = list(data_dir.glob("*_records_*.parquet"))

    if not parquet_files:
        raise FileNotFoundError(f"未找到执行记录文件: {data_dir}")

    # 按修改时间排序
    latest_file = max(parquet_files, key=lambda p: p.stat().st_mtime)

    logger.info("found_latest_records", file=str(latest_file))

    return latest_file


def load_execution_records(file_path: Path) -> pd.DataFrame:
    """加载执行记录"""
    logger.info("loading_execution_records", file=str(file_path))

    df = pd.read_parquet(file_path)

    logger.info("records_loaded", count=len(df))

    return df


def analyze_signal_quality(df: pd.DataFrame) -> Dict[str, Any]:
    """分析信号质量"""
    logger.info("analyzing_signal_quality")

    # 过滤掉跳过的订单
    executed_df = df[~df["skipped"]].copy()

    if len(executed_df) == 0:
        return {
            "error": "没有执行的订单",
            "total_signals": len(df),
            "skipped_count": len(df),
        }

    # 计算执行率
    execution_rate = len(executed_df) / len(df) * 100

    # 按交易对分组
    by_symbol = executed_df.groupby("symbol").agg({
        "order_id": "count",
        "slippage_bps": ["mean", "std", "max"],
    })

    return {
        "total_signals": len(df),
        "executed_count": len(executed_df),
        "skipped_count": len(df) - len(executed_df),
        "execution_rate": execution_rate,
        "by_symbol": by_symbol.to_dict(),
    }


def analyze_execution_efficiency(df: pd.DataFrame) -> Dict[str, Any]:
    """分析执行效率"""
    logger.info("analyzing_execution_efficiency")

    executed_df = df[~df["skipped"]].copy()

    if len(executed_df) == 0:
        return {"error": "没有执行的订单"}

    # 延迟统计
    latency_stats = {
        "mean_ms": executed_df["total_latency_ms"].mean(),
        "median_ms": executed_df["total_latency_ms"].median(),
        "p95_ms": executed_df["total_latency_ms"].quantile(0.95),
        "p99_ms": executed_df["total_latency_ms"].quantile(0.99),
        "max_ms": executed_df["total_latency_ms"].max(),
    }

    # 成交率
    filled_df = executed_df[executed_df["status"].isin(["FILLED", "PARTIAL_FILLED"])]
    fill_rate = len(filled_df) / len(executed_df) * 100

    # 滑点统计
    slippage_stats = {
        "mean_bps": executed_df["slippage_bps"].mean(),
        "median_bps": executed_df["slippage_bps"].median(),
        "p95_bps": executed_df["slippage_bps"].quantile(0.95),
        "p99_bps": executed_df["slippage_bps"].quantile(0.99),
        "max_bps": executed_df["slippage_bps"].max(),
    }

    return {
        "total_executions": len(executed_df),
        "fill_rate": fill_rate,
        "latency": latency_stats,
        "slippage": slippage_stats,
    }


def analyze_trade_distribution(df: pd.DataFrame) -> Dict[str, Any]:
    """分析交易分布"""
    logger.info("analyzing_trade_distribution")

    executed_df = df[~df["skipped"]].copy()

    if len(executed_df) == 0:
        return {"error": "没有执行的订单"}

    # 按方向分组
    by_side = executed_df.groupby("side").agg({
        "order_id": "count",
        "size": "sum",
        "slippage_bps": "mean",
    })

    # 按状态分组
    by_status = executed_df["status"].value_counts()

    # 时间分布（按小时）
    executed_df["hour"] = pd.to_datetime(
        executed_df["execution_timestamp"], unit="ms"
    ).dt.hour
    by_hour = executed_df.groupby("hour").size()

    return {
        "by_side": by_side.to_dict(),
        "by_status": by_status.to_dict(),
        "by_hour": by_hour.to_dict(),
    }


def generate_markdown_report(
    records_file: Path,
    signal_quality: Dict[str, Any],
    execution_efficiency: Dict[str, Any],
    trade_distribution: Dict[str, Any],
) -> str:
    """生成 Markdown 格式报告"""

    lines = []
    lines.append("# 影子交易结果分析\n")
    lines.append(f"**分析时间**: {datetime.now().isoformat()}\n")
    lines.append(f"**数据文件**: {records_file.name}\n")
    lines.append("\n---\n")

    # 信号质量
    lines.append("\n## 1. 信号质量\n")
    if "error" not in signal_quality:
        lines.append(f"- **总信号数**: {signal_quality['total_signals']}\n")
        lines.append(f"- **执行数量**: {signal_quality['executed_count']}\n")
        lines.append(f"- **跳过数量**: {signal_quality['skipped_count']}\n")
        lines.append(f"- **执行率**: {signal_quality['execution_rate']:.1f}%\n")
    else:
        lines.append(f"⚠️ {signal_quality['error']}\n")

    # 执行效率
    lines.append("\n## 2. 执行效率\n")
    if "error" not in execution_efficiency:
        lines.append(f"- **总执行次数**: {execution_efficiency['total_executions']}\n")
        lines.append(f"- **成交率**: {execution_efficiency['fill_rate']:.1f}%\n")

        lines.append("\n### 延迟分布\n")
        for metric, value in execution_efficiency["latency"].items():
            lines.append(f"- **{metric}**: {value:.1f} ms\n")

        lines.append("\n### 滑点分布\n")
        for metric, value in execution_efficiency["slippage"].items():
            lines.append(f"- **{metric}**: {value:.2f} bps\n")
    else:
        lines.append(f"⚠️ {execution_efficiency['error']}\n")

    # 交易分布
    lines.append("\n## 3. 交易分布\n")
    if "error" not in trade_distribution:
        lines.append("\n### 按方向\n")
        if "by_side" in trade_distribution:
            for side, stats in trade_distribution["by_side"].get(
                "order_id", {}
            ).items():
                lines.append(f"- **{side}**: {stats} 笔\n")

        lines.append("\n### 按状态\n")
        if "by_status" in trade_distribution:
            for status, count in trade_distribution["by_status"].items():
                lines.append(f"- **{status}**: {count} 笔\n")

    return "".join(lines)


def generate_html_report(
    records_file: Path,
    signal_quality: Dict[str, Any],
    execution_efficiency: Dict[str, Any],
    trade_distribution: Dict[str, Any],
) -> str:
    """生成 HTML 格式报告（带图表）"""

    # 简化版本，实际可以用 plotly 等库生成交互式图表
    html_lines = []
    html_lines.append("<!DOCTYPE html>")
    html_lines.append("<html lang='zh-CN'>")
    html_lines.append("<head>")
    html_lines.append("<meta charset='UTF-8'>")
    html_lines.append("<title>影子交易结果分析</title>")
    html_lines.append("<style>")
    html_lines.append("body { font-family: Arial, sans-serif; margin: 20px; }")
    html_lines.append("h1, h2, h3 { color: #333; }")
    html_lines.append("table { border-collapse: collapse; width: 100%; margin: 20px 0; }")
    html_lines.append(
        "th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }"
    )
    html_lines.append("th { background-color: #4CAF50; color: white; }")
    html_lines.append(".metric { margin: 10px 0; }")
    html_lines.append(".value { font-weight: bold; color: #2196F3; }")
    html_lines.append("</style>")
    html_lines.append("</head>")
    html_lines.append("<body>")

    html_lines.append("<h1>影子交易结果分析</h1>")
    html_lines.append(f"<p><strong>分析时间</strong>: {datetime.now().isoformat()}</p>")
    html_lines.append(f"<p><strong>数据文件</strong>: {records_file.name}</p>")

    # 信号质量
    html_lines.append("<h2>1. 信号质量</h2>")
    if "error" not in signal_quality:
        html_lines.append("<div class='metric'>")
        html_lines.append(
            f"<p>总信号数: <span class='value'>{signal_quality['total_signals']}</span></p>"
        )
        html_lines.append(
            f"<p>执行数量: <span class='value'>{signal_quality['executed_count']}</span></p>"
        )
        html_lines.append(
            f"<p>跳过数量: <span class='value'>{signal_quality['skipped_count']}</span></p>"
        )
        html_lines.append(
            f"<p>执行率: <span class='value'>{signal_quality['execution_rate']:.1f}%</span></p>"
        )
        html_lines.append("</div>")

    # 执行效率
    html_lines.append("<h2>2. 执行效率</h2>")
    if "error" not in execution_efficiency:
        html_lines.append("<h3>延迟分布</h3>")
        html_lines.append("<table>")
        html_lines.append("<tr><th>指标</th><th>值 (ms)</th></tr>")
        for metric, value in execution_efficiency["latency"].items():
            html_lines.append(f"<tr><td>{metric}</td><td>{value:.1f}</td></tr>")
        html_lines.append("</table>")

        html_lines.append("<h3>滑点分布</h3>")
        html_lines.append("<table>")
        html_lines.append("<tr><th>指标</th><th>值 (bps)</th></tr>")
        for metric, value in execution_efficiency["slippage"].items():
            html_lines.append(f"<tr><td>{metric}</td><td>{value:.2f}</td></tr>")
        html_lines.append("</table>")

    html_lines.append("</body>")
    html_lines.append("</html>")

    return "\n".join(html_lines)


def main() -> None:
    """主函数"""
    parser = argparse.ArgumentParser(description="分析影子交易结果")
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="执行记录文件路径（不指定则使用最新的）",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data/shadow_trading",
        help="数据目录",
    )
    parser.add_argument(
        "--format",
        type=str,
        default="markdown",
        choices=["markdown", "html", "both"],
        help="报告格式",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出文件路径（不指定则打印到终端）",
    )
    args = parser.parse_args()

    # 配置日志
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )

    try:
        # 查找或加载记录文件
        if args.file:
            records_file = Path(args.file)
        else:
            data_dir = Path(args.data_dir)
            records_file = find_latest_records(data_dir)

        # 加载数据
        df = load_execution_records(records_file)

        # 分析
        signal_quality = analyze_signal_quality(df)
        execution_efficiency = analyze_execution_efficiency(df)
        trade_distribution = analyze_trade_distribution(df)

        # 生成报告
        if args.format in ["markdown", "both"]:
            report_md = generate_markdown_report(
                records_file,
                signal_quality,
                execution_efficiency,
                trade_distribution,
            )

            if args.output:
                output_file = Path(args.output).with_suffix(".md")
                with open(output_file, "w") as f:
                    f.write(report_md)
                logger.info("markdown_report_saved", file=str(output_file))
            else:
                print(report_md)

        if args.format in ["html", "both"]:
            report_html = generate_html_report(
                records_file,
                signal_quality,
                execution_efficiency,
                trade_distribution,
            )

            output_file = (
                Path(args.output).with_suffix(".html")
                if args.output
                else Path("shadow_trading_analysis.html")
            )
            with open(output_file, "w") as f:
                f.write(report_html)
            logger.info("html_report_saved", file=str(output_file))

    except Exception as e:
        logger.error("analysis_error", error=str(e), exc_info=True)
        raise


if __name__ == "__main__":
    main()
