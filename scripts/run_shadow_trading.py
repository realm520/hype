"""影子交易 24 小时验证脚本

在 mainnet 真实市场数据上运行影子交易，不实际下单。
验证 Week 1 IOC 策略是否满足上线标准。

用法：
    python scripts/run_shadow_trading.py --config config/shadow_mainnet.yaml
"""

import asyncio
import time
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import structlog
import yaml

from src.analytics.future_return_tracker import FutureReturnTracker
from src.analytics.live_monitor import LiveMonitor
from src.analytics.shadow_analyzer import ShadowAnalyzer
from src.core.data_feed import MarketDataManager
from src.core.logging import get_audit_logger, setup_logging
from src.execution.fill_simulator import FillSimulator
from src.execution.shadow_executor import (
    ShadowExecutionRecord,
    ShadowIOCExecutor,
)
from src.execution.shadow_order_router import (
    ShadowLimitExecutor,
    ShadowOrderRouter,
)
from src.hyperliquid.websocket_client import HyperliquidWebSocket
from src.risk.shadow_position_manager import ShadowPositionManager
from src.signals.aggregator import create_aggregator_from_config

logger = structlog.get_logger()


class ShadowTradingEngine:
    """影子交易引擎

    架构：
        数据层 → 信号层 → 影子执行层 → 影子持仓 → 分析层 → 监控层

    主循环：
        1. 获取真实市场数据（mainnet）
        2. 计算聚合信号
        3. 影子执行（模拟 IOC 成交）
        4. 更新影子持仓
        5. 实时分析和监控
        6. 定期保存状态
    """

    def __init__(self, config_path: str):
        """
        初始化影子交易引擎

        Args:
            config_path: 配置文件路径
        """
        # 加载配置
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.symbols = self.config["hyperliquid"]["subscriptions"]["symbols"]
        self.duration_hours = self.config["shadow_mode"]["duration_hours"]
        self.initial_nav = Decimal(str(self.config["shadow_mode"]["initial_nav"]))

        self._running = False
        self._start_time: float | None = None
        self._end_time: float | None = None

        # 执行记录（用于最终分析）
        self.execution_records: list[ShadowExecutionRecord] = []

        # 状态保存配置
        self.save_interval = (
            self.config["data"]["persistence"]["save_interval_minutes"] * 60
        )
        self._last_save_time = 0.0
        self.output_dir = Path(self.config["data"]["persistence"]["output_dir"])
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "shadow_trading_engine_initializing",
            symbols=self.symbols,
            duration_hours=self.duration_hours,
            initial_nav=float(self.initial_nav),
        )

        # 1. 数据层（使用真实 mainnet 数据）
        use_mainnet = self.config["environment"] == "mainnet"
        self.ws_client = HyperliquidWebSocket(use_mainnet)
        self.data_manager = MarketDataManager(self.ws_client)

        # 2. 信号层
        signals_config = {
            "signals": self.config["signals"]["sources"],
            "thresholds": self.config["signals"]["thresholds"],
        }
        self.signal_aggregator = create_aggregator_from_config(signals_config)

        # 3. 影子执行层（Week 2 混合订单路由）
        max_slippage_bps = self.config["shadow_mode"]["fill_simulation"][
            "max_slippage_bps"
        ]
        self.fill_simulator = FillSimulator(max_slippage_bps=max_slippage_bps)

        # 读取订单配置（兼容 Week 1 格式）
        orders_config = self.config["shadow_mode"]["orders"]

        # Week 2 新格式：分 IOC 和 limit 配置
        if "ioc" in orders_config:
            ioc_config = orders_config["ioc"]
            limit_config = orders_config["limit"]
            routing_config = orders_config["routing"]

            # IOC 执行器
            ioc_default_size = Decimal(str(ioc_config["default_size"]))
            ioc_price_adjustment_bps = ioc_config["price_adjustment_bps"]
            ioc_executor = ShadowIOCExecutor(
                fill_simulator=self.fill_simulator,
                default_size=ioc_default_size,
                price_adjustment_bps=ioc_price_adjustment_bps,
            )

            # 限价单执行器
            limit_default_size = Decimal(str(limit_config["default_size"]))
            limit_timeout_seconds = limit_config["timeout_seconds"]
            limit_use_post_only = limit_config["use_post_only"]
            limit_executor = ShadowLimitExecutor(
                fill_simulator=self.fill_simulator,
                default_size=limit_default_size,
                timeout_seconds=limit_timeout_seconds,
                use_post_only=limit_use_post_only,
            )

            # 订单路由器
            enable_fallback = routing_config["enable_fallback"]
            self.shadow_executor = ShadowOrderRouter(
                fill_simulator=self.fill_simulator,
                ioc_executor=ioc_executor,
                limit_executor=limit_executor,
                enable_fallback=enable_fallback,
            )

            logger.info(
                "shadow_order_router_configured",
                mode="week2_hybrid",
                enable_fallback=enable_fallback,
            )
        else:
            # Week 1 兼容格式：只有 IOC
            default_size = Decimal(str(orders_config["default_size"]))
            price_adjustment_bps = orders_config["price_adjustment_bps"]
            self.shadow_executor = ShadowIOCExecutor(
                fill_simulator=self.fill_simulator,
                default_size=default_size,
                price_adjustment_bps=price_adjustment_bps,
            )

            logger.info(
                "shadow_ioc_executor_configured",
                mode="week1_ioc_only",
            )

        # 4. 影子持仓管理
        self.position_manager = ShadowPositionManager()

        # 5. 分析层
        ic_window_hours = self.config["analytics"]["ic_calculation"]["window_hours"]
        launch_criteria = self.config["analytics"]["launch_criteria"]
        self.analyzer = ShadowAnalyzer(
            position_manager=self.position_manager,
            initial_nav=self.initial_nav,
            ic_window_hours=ic_window_hours,
            launch_criteria=launch_criteria,
        )

        # 5.5 未来收益跟踪器（用于 IC 计算）
        future_return_window = self.config["analytics"]["future_return"][
            "window_minutes"
        ]
        self.future_return_tracker = FutureReturnTracker(
            window_minutes=future_return_window,
            update_callback=self.analyzer.update_signal_future_return,
        )
        self._last_return_update_time = 0.0
        self._return_update_interval = self.config["analytics"]["future_return"][
            "update_interval_seconds"
        ]

        # 6. 监控层
        monitor_config = self.config["monitoring"]["live_monitor"]
        self.monitor = LiveMonitor(
            analyzer=self.analyzer,
            update_interval_seconds=monitor_config["update_interval_seconds"],
            alert_thresholds=monitor_config["alert_thresholds"],
        )

        logger.info("shadow_trading_engine_initialized")

    async def start(self) -> None:
        """启动影子交易"""
        logger.info(
            "shadow_trading_starting",
            symbols=self.symbols,
            duration_hours=self.duration_hours,
        )

        try:
            # 启动数据订阅
            await self.data_manager.start(self.symbols)

            # 等待数据稳定
            logger.info("waiting_for_initial_data")
            await asyncio.sleep(5)

            # 设置运行时间
            self._start_time = time.time()
            self._end_time = self._start_time + (self.duration_hours * 3600)
            self._running = True

            logger.info(
                "shadow_trading_started",
                start_time=datetime.fromtimestamp(self._start_time).isoformat(),
                end_time=datetime.fromtimestamp(self._end_time).isoformat(),
            )

            # 启动主循环
            await self._main_loop()

        except Exception as e:
            logger.error("shadow_trading_start_error", error=str(e), exc_info=True)
            raise

    async def stop(self) -> None:
        """停止影子交易"""
        logger.info("shadow_trading_stopping")

        self._running = False

        # 停止数据管理器
        await self.data_manager.stop()

        # 保存最终状态
        await self._save_state(final=True)

        # 生成最终报告
        await self._generate_final_report()

        logger.info("shadow_trading_stopped")

    async def _main_loop(self) -> None:
        """主事件循环"""
        logger.info("main_loop_started")

        while self._running:
            try:
                # 检查是否超时
                if time.time() >= self._end_time:
                    logger.info("duration_completed", duration_hours=self.duration_hours)
                    break

                # 遍历所有交易对
                for symbol in self.symbols:
                    await self._process_symbol(symbol)

                # 实时监控更新
                await self.monitor.update()

                # 定期更新未来收益
                await self._periodic_return_update()

                # 定期保存状态
                await self._periodic_save()

                # 100ms 循环周期
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error("main_loop_error", error=str(e), exc_info=True)
                # 继续运行，但记录错误
                await asyncio.sleep(1)

        logger.info("main_loop_completed")

    async def _process_symbol(self, symbol: str) -> None:
        """
        处理单个交易对（影子模式）

        Args:
            symbol: 交易对
        """
        try:
            # 1. 获取真实市场数据
            market_data = self.data_manager.get_market_data(symbol)
            if not market_data:
                return

            # 2. 计算聚合信号
            signal_score = self.signal_aggregator.calculate(market_data)

            # 记录信号到分析器（用于 IC 计算）
            signal_id = self.analyzer.record_signal(
                signal=signal_score,
                symbol=symbol,  # 币种符号，用于分币种 IC 计算
                future_return=None,  # 将由 future_return_tracker 异步更新
            )

            # 记录到未来收益跟踪器（用于 T+n 收益计算）
            self.future_return_tracker.record_signal(
                signal_id=signal_id,
                signal_value=signal_score.value,
                symbol=symbol,
                price=market_data.mid_price,
            )

            # 3. 影子执行（Week 2: 自动路由 | Week 1: IOC only）
            # OrderRouter 会自动根据置信度选择执行策略，无需手动检查
            if hasattr(self.shadow_executor, "route_and_execute"):
                # Week 2: 混合订单路由
                execution_record = await self.shadow_executor.route_and_execute(
                    signal_score, market_data
                )
            else:
                # Week 1: IOC only（向后兼容）
                if not self.shadow_executor.should_execute(signal_score):
                    return

                execution_record = await self.shadow_executor.execute(
                    signal_score, market_data
                )

            # 保存执行记录
            self.execution_records.append(execution_record)

            # 5. 更新影子持仓
            if not execution_record.skipped:
                self.position_manager.update_from_execution_record(execution_record)

            # 6. 添加到分析器
            self.analyzer.record_execution(execution_record)

            # 7. 更新价格（用于未实现盈亏计算）
            prices = {symbol: market_data.mid_price}
            self.position_manager.update_prices(prices)

        except Exception as e:
            logger.error(
                "symbol_processing_error",
                symbol=symbol,
                error=str(e),
                exc_info=True,
            )

    async def _periodic_return_update(self) -> None:
        """定期更新未来收益"""
        now = time.time()

        if now - self._last_return_update_time < self._return_update_interval:
            return

        # 获取当前所有交易对的价格
        current_prices = {}
        for symbol in self.symbols:
            market_data = self.data_manager.get_market_data(symbol)
            if market_data:
                current_prices[symbol] = market_data.mid_price

        # 批量更新已到期信号的未来收益
        self.future_return_tracker.update_future_returns(current_prices)
        self._last_return_update_time = now

    async def _periodic_save(self) -> None:
        """定期保存状态"""
        now = time.time()

        if now - self._last_save_time < self.save_interval:
            return

        await self._save_state(final=False)
        self._last_save_time = now

    async def _save_state(self, final: bool = False) -> None:
        """
        保存状态

        Args:
            final: 是否是最终保存
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = "final" if final else "checkpoint"

            # 1. 保存执行记录
            if self.execution_records:
                records_data = []
                for record in self.execution_records:
                    records_data.append({
                        "order_id": record.order.id,
                        "symbol": record.order.symbol,
                        "side": record.order.side.name,
                        "size": float(record.order.size),
                        "price": float(record.order.price),
                        "filled_size": float(record.order.filled_size),
                        "avg_fill_price": (
                            float(record.order.avg_fill_price)
                            if record.order.avg_fill_price
                            else None
                        ),
                        "status": record.order.status.name,
                        "skipped": record.skipped,
                        "skip_reason": record.skip_reason,
                        "signal_timestamp": record.signal_timestamp,
                        "decision_timestamp": record.decision_timestamp,
                        "execution_timestamp": record.execution_timestamp,
                        "total_latency_ms": record.total_latency_ms,
                        "slippage_bps": (
                            record.fill_result.slippage_bps
                            if record.fill_result
                            else None
                        ),
                    })

                df = pd.DataFrame(records_data)
                output_file = self.output_dir / f"{prefix}_records_{timestamp}.parquet"
                df.to_parquet(output_file)

                logger.info(
                    "execution_records_saved",
                    file=str(output_file),
                    count=len(records_data),
                )

            # 2. 保存持仓统计
            position_stats = self.position_manager.get_statistics()
            stats_file = self.output_dir / f"{prefix}_position_stats_{timestamp}.json"

            import json
            with open(stats_file, "w") as f:
                json.dump(position_stats, f, indent=2)

            logger.info("position_stats_saved", file=str(stats_file))

        except Exception as e:
            logger.error("save_state_error", error=str(e), exc_info=True)

    async def _generate_final_report(self) -> None:
        """生成最终报告"""
        try:
            logger.info("generating_final_report")

            # 回填未来收益（用于多窗口 IC 验证）
            logger.info("backfilling_future_returns_for_ic_validation")

            # 根据测试时长动态选择回填窗口
            test_duration_minutes = self.config["shadow_mode"]["duration_hours"] * 60
            max_window = int(test_duration_minutes * 0.8)  # 留 20% 余量
            available_windows = [5, 10, 15, 30]
            backfill_windows = [w for w in available_windows if w <= max_window]

            logger.info(
                "backfill_windows_selected",
                test_duration_minutes=test_duration_minutes,
                max_window=max_window,
                available_windows=available_windows,
                selected_windows=backfill_windows,
            )

            if not backfill_windows:
                logger.warning(
                    "no_valid_backfill_windows",
                    test_duration_minutes=test_duration_minutes,
                    min_required=min(available_windows),
                )
                backfill_results = {}
            else:
                backfill_results = self.future_return_tracker.backfill_future_returns(
                    backfill_windows
                )

            # 计算并记录多窗口 IC
            if backfill_results:
                logger.info(
                    "backfill_multi_window_ic_summary",
                    total_signals=len(backfill_results),
                    windows=backfill_windows,
                )

                # 批量更新 analyzer 中的 future_return（修复 IC 计算）
                primary_window = backfill_windows[0]  # 使用第一个窗口作为主窗口
                updated_count = 0

                for signal_id, window_returns in backfill_results.items():
                    if primary_window in window_returns:
                        try:
                            self.analyzer.update_signal_future_return(
                                signal_id,
                                window_returns[primary_window]
                            )
                            updated_count += 1
                        except Exception as e:
                            logger.error(
                                "backfill_update_failed",
                                signal_id=signal_id,
                                error=str(e),
                            )

                logger.info(
                    "backfill_results_applied",
                    updated_signals=updated_count,
                    primary_window=primary_window,
                    total_backfilled=len(backfill_results),
                    success_rate=updated_count / len(backfill_results) if backfill_results else 0,
                )

            # 生成报告
            report = self.analyzer.generate_report()

            # 保存报告
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_dir = Path(self.config["reporting"]["final_report"]["output_dir"])
            report_dir.mkdir(parents=True, exist_ok=True)

            # JSON 格式
            import json
            json_file = report_dir / f"shadow_trading_report_{timestamp}.json"
            with open(json_file, "w") as f:
                json.dump(asdict(report), f, indent=2, default=str)

            # Markdown 格式
            md_file = report_dir / f"shadow_trading_report_{timestamp}.md"
            with open(md_file, "w") as f:
                f.write(self._format_report_markdown(report))

            logger.info(
                "final_report_generated",
                json_file=str(json_file),
                md_file=str(md_file),
                ready_for_launch=report.ready_for_launch,
                launch_score=report.launch_score,
            )

            # 输出关键结论
            print("\n" + "=" * 80)
            print("影子交易 24 小时验证完成")
            print("=" * 80)
            print(f"\n上线准备度评分: {report.launch_score:.1f}/100")
            print(f"是否满足上线标准: {'✅ 是' if report.ready_for_launch else '❌ 否'}")
            print(f"\n信号质量 IC: {report.signal_quality.ic:.4f}")
            print(f"Alpha 占比: {report.pnl_attribution.alpha_percentage:.1f}%")
            if report.pnl_attribution.win_rate is not None:
                print(f"胜率: {report.pnl_attribution.win_rate:.1f}%")
            else:
                print("胜率: N/A (需要完整持仓追踪)")
            print(f"总盈亏: ${float(report.pnl_attribution.total_pnl):,.2f}")
            print(f"\n详细报告: {md_file}")
            print("=" * 80 + "\n")

        except Exception as e:
            logger.error("generate_final_report_error", error=str(e), exc_info=True)

    def _format_report_markdown(
        self, report: "ShadowTradingReport"
    ) -> str:  # noqa: F821
        """格式化报告为 Markdown"""

        lines = []
        lines.append("# 影子交易验证报告\n")
        lines.append(f"**生成时间**: {datetime.now().isoformat()}\n")
        lines.append(f"**运行时长**: {report.runtime_hours:.1f} 小时\n")
        lines.append(
            f"**上线准备度**: {report.launch_score:.1f}/100 "
            f"{'✅' if report.ready_for_launch else '❌'}\n"
        )
        lines.append("\n---\n")

        # 信号质量
        lines.append("\n## 1. 信号质量\n")
        lines.append(f"- **IC**: {report.signal_quality.ic:.4f}\n")
        lines.append(f"- **IC p-value**: {report.signal_quality.ic_p_value:.4f}\n")
        lines.append(
            f"- **Top 20% 收益**: {report.signal_quality.top_quintile_return:.4f}\n"
        )
        lines.append(
            f"- **Bottom 20% 收益**: {report.signal_quality.bottom_quintile_return:.4f}\n"
        )
        lines.append(f"- **样本数**: {report.signal_quality.sample_size}\n")

        # 新增：各币种 IC 表格
        if report.per_symbol_ic:
            lines.append("\n### 1.1 各币种 IC 表现\n")
            lines.append("| 币种 | IC | P值 | 样本数 | Top 20% | Bottom 20% | 状态 |\n")
            lines.append("|------|-----|-----|--------|---------|-----------|------|\n")
            for symbol in sorted(report.per_symbol_ic.keys()):
                metrics = report.per_symbol_ic[symbol]
                # 状态判断
                if metrics.ic >= 0.03:
                    status = "✅"
                elif metrics.ic >= 0:
                    status = "⚠️"
                else:
                    status = "❌"
                lines.append(
                    f"| {symbol} | {metrics.ic:.4f} | {metrics.ic_p_value:.4f} | "
                    f"{metrics.sample_size} | {metrics.top_quintile_return:.4f} | "
                    f"{metrics.bottom_quintile_return:.4f} | {status} |\n"
                )
            lines.append("\n")

        # 执行效率
        lines.append("\n## 2. 执行效率\n")
        lines.append(
            f"- **平均延迟**: {report.execution_efficiency.avg_total_latency_ms:.1f} ms\n"
        )
        lines.append(
            f"- **P99 延迟**: {report.execution_efficiency.p99_total_latency_ms:.1f} ms\n"
        )
        lines.append(
            f"- **成交率**: {report.execution_efficiency.fill_rate:.1f}%\n"
        )
        lines.append(
            f"- **平均滑点**: {report.execution_efficiency.avg_slippage_bps:.2f} bps\n"
        )

        # PnL 归因
        lines.append("\n## 3. PnL 归因\n")
        lines.append(
            f"- **总盈亏**: ${float(report.pnl_attribution.total_pnl):,.2f}\n"
        )
        lines.append(
            f"- **Alpha**: ${float(report.pnl_attribution.alpha):,.2f} "
            f"({report.pnl_attribution.alpha_percentage:.1f}%)\n"
        )
        lines.append(
            f"- **手续费**: ${float(report.pnl_attribution.fee):,.2f}\n"
        )
        lines.append(
            f"- **滑点**: ${float(report.pnl_attribution.slippage):,.2f}\n"
        )
        lines.append(f"- **交易次数**: {report.pnl_attribution.num_trades}\n")
        if report.pnl_attribution.win_rate is not None:
            lines.append(f"- **胜率**: {report.pnl_attribution.win_rate:.1f}%\n")
        else:
            lines.append("- **胜率**: N/A (需要完整持仓追踪系统)\n")

        # 新增：各币种交易统计
        if report.per_symbol_trades:
            lines.append("\n### 3.1 各币种交易统计\n")
            lines.append("| 币种 | 交易次数 | 占比 |\n")
            lines.append("|------|----------|------|\n")
            total_trades = sum(report.per_symbol_trades.values())
            for symbol in sorted(report.per_symbol_trades.keys()):
                trades = report.per_symbol_trades[symbol]
                pct = (trades / total_trades * 100) if total_trades > 0 else 0
                lines.append(f"| {symbol} | {trades} | {pct:.1f}% |\n")
            lines.append("\n")

        # 风控表现
        lines.append("\n## 4. 风控表现\n")
        lines.append(
            f"- **最大回撤**: {report.risk_metrics.max_drawdown_pct:.2f}%\n"
        )
        lines.append(
            f"- **夏普比率**: {report.risk_metrics.sharpe_ratio:.2f}\n"
        )
        lines.append(
            f"- **连续亏损**: {report.risk_metrics.consecutive_losses}\n"
        )
        lines.append(f"- **在线率**: {report.system_uptime_pct:.2f}%\n")

        # 上线建议
        lines.append("\n## 5. 上线建议\n")
        if report.ready_for_launch:
            lines.append("✅ **满足所有上线标准，建议进入真实交易**\n")
        else:
            lines.append("❌ **未满足上线标准，需要改进**\n")
            lines.append("\n需要改进的指标:\n")
            for criterion, details in report.criteria_details.items():
                if not details["passed"]:
                    lines.append(
                        f"- {criterion}: {details['actual']:.2f} "
                        f"(要求: {details['required']:.2f})\n"
                    )

        return "".join(lines)


async def main() -> None:
    """主函数"""
    import argparse

    # 解析命令行参数
    parser = argparse.ArgumentParser(description="运行影子交易验证")
    parser.add_argument(
        "--config",
        type=str,
        default="config/shadow_mainnet.yaml",
        help="配置文件路径",
    )
    args = parser.parse_args()

    # 配置日志系统（使用统一的日志配置）
    setup_logging()

    logger = structlog.get_logger(__name__)
    audit_logger = get_audit_logger()

    logger.info(
        "shadow_trading_system_starting",
        config=args.config,
    )

    # 记录审计日志（系统启动）
    audit_logger.info(
        "shadow_system_started",
        config=args.config,
        mode="shadow_trading",
    )

    # 创建引擎
    engine = ShadowTradingEngine(args.config)

    # 移除自定义信号处理器（避免无限循环）
    # asyncio 默认会处理 KeyboardInterrupt

    try:
        # 启动引擎
        await engine.start()

    except KeyboardInterrupt:
        logger.info("keyboard_interrupt_received")

    except Exception as e:
        logger.error("system_error", error=str(e), exc_info=True)

    finally:
        await engine.stop()
        logger.info("system_shutdown_complete")


if __name__ == "__main__":
    asyncio.run(main())
