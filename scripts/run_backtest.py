#!/usr/bin/env python3
"""
Week 1.5 Maker/Taker 混合策略回测脚本

功能：
1. 加载历史市场数据（L2 订单簿 + 成交数据）
2. 使用数据回放引擎模拟实时交易
3. 运行 Week 1.5 混合执行策略
4. 生成详细性能报告（PnL归因、信号质量、Maker成交率等）

使用方法：
    python scripts/run_backtest.py --data-dir data/market_data/test_8hour

示例：
    # 基础回测
    python scripts/run_backtest.py --data-dir data/market_data/test_8hour

    # 加速回测（10倍速）
    python scripts/run_backtest.py --data-dir data/market_data/test_8hour --speed 10.0

    # 指定交易对
    python scripts/run_backtest.py --data-dir data/market_data/test_8hour --symbols BTC ETH
"""

import argparse
import asyncio
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import structlog

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analytics.maker_fill_rate_monitor import MakerFillRateMonitor
from src.analytics.metrics import MetricsCollector
from src.analytics.pnl_attribution import PnLAttribution
from src.core.config import load_config
from src.core.data_replay import DataReplayEngine
from src.core.logging import setup_logging
from src.execution.hybrid_executor import HybridExecutor
from src.execution.ioc_executor import IOCExecutor
from src.execution.shallow_maker_executor import ShallowMakerExecutor
from src.execution.signal_classifier import SignalClassifier
from src.execution.slippage_estimator import SlippageEstimator
from src.hyperliquid.api_client import HyperliquidAPIClient
from src.risk.hard_limits import HardLimits
from src.risk.position_manager import PositionManager
from src.signals.aggregator import SignalAggregator
from src.core.types import SignalScore, ConfidenceLevel, OrderSide

logger = structlog.get_logger(__name__)


class BacktestEngine:
    """回测引擎"""

    def __init__(
        self,
        config_path: str = "config/paper_trading.yaml",
        data_dir: str = "data/market_data/test_8hour",
        speed: float = 1.0,
        symbols: list[str] | None = None,
    ):
        """
        初始化回测引擎

        Args:
            config_path: 配置文件路径
            data_dir: 数据目录路径
            speed: 回放速度倍数（1.0 = 实时，10.0 = 10倍速）
            symbols: 交易对列表（None = 使用配置文件中的）
        """
        self.config = load_config(config_path)
        self.data_dir = Path(data_dir)
        self.speed = speed
        self.symbols = symbols or self.config.hyperliquid.symbols

        # 初始化组件
        self._init_components()

        # 回测统计
        self.trades_count = 0
        self.signals_count = 0
        self.start_time = None
        self.end_time = None

    def _init_components(self):
        """初始化所有交易组件"""
        # 1. 数据回放引擎
        self.data_replay = DataReplayEngine(
            data_dir=str(self.data_dir / "test_8hour"),
            replay_speed=self.speed,
        )

        # 2. 信号引擎
        from src.signals.obi import OBISignal
        from src.signals.microprice import MicropriceSignal
        from src.signals.impact import ImpactSignal
        
        # 创建信号列表（使用默认参数）
        signals = [
            OBISignal(levels=5, weight=0.35),
            MicropriceSignal(weight=0.40),
            ImpactSignal(window_ms=5000, weight=0.25),
        ]
        
        self.signal_aggregator = SignalAggregator(
            signals=signals,
            theta_1=self.config.signals.thresholds.theta_1,
            theta_2=self.config.signals.thresholds.theta_2,
        )
        self.signal_classifier = SignalClassifier(
            theta_1=self.config.signals.thresholds.theta_1,
            theta_2=self.config.signals.thresholds.theta_2,
        )

        # 3. 执行引擎（使用 dry_run=True 模拟订单）
        self.api_client = HyperliquidAPIClient(
            wallet_address=self.config.hyperliquid.wallet_address,
            private_key=self.config.hyperliquid.private_key,
            dry_run=True,  # 回测模式使用模拟订单
        )

        # Maker 执行器（使用硬编码值，与 src/main.py 保持一致）
        self.maker_executor = ShallowMakerExecutor(
            api_client=self.api_client,
            default_size=Decimal("0.01"),  # Week 1.5 默认订单尺寸
            tick_offset=Decimal("0.1"),  # 盘口偏移量 +1 tick
            timeout_high=5.0,  # HIGH 置信度超时 5 秒
            timeout_medium=3.0,  # MEDIUM 置信度超时 3 秒
            use_post_only=True,  # 使用 Post-Only 订单
        )

        # IOC 执行器（使用硬编码值）
        self.ioc_executor = IOCExecutor(
            api_client=self.api_client,
            default_size=Decimal("0.01"),  # Week 1.5 默认订单尺寸
            price_adjustment_bps=10.0,  # 价格调整 10 bps 提高成交率
        )

        # 混合执行器（使用硬编码值）
        self.hybrid_executor = HybridExecutor(
            shallow_maker_executor=self.maker_executor,  # 正确的参数名
            ioc_executor=self.ioc_executor,
            enable_fallback=True,  # 启用 Maker → IOC 回退
            fallback_on_medium=True,  # MEDIUM 置信度也启用回退
        )

        # 4. 风控（使用硬编码值）
        self.hard_limits = HardLimits(
            initial_nav=Decimal("100000"),  # 初始资金 10万 USDC
            max_single_loss_pct=0.008,  # 单笔最大亏损 0.8%
            max_daily_drawdown_pct=0.05,  # 日最大回撤 5%
            max_position_size_usd=Decimal("10000"),  # 最大仓位 1万 USDC
        )
        self.position_manager = PositionManager()

        # 5. 分析（使用硬编码值，与 src/main.py 保持一致）
        self.pnl_attribution = PnLAttribution()  # 无参数初始化
        self.metrics_collector = MetricsCollector()
        self.fill_rate_monitor = MakerFillRateMonitor(
            window_size=100,  # 最近 100 次尝试
            alert_threshold_high=0.80,  # HIGH 置信度目标 80%
            alert_threshold_medium=0.75,  # MEDIUM 置信度目标 75%
        )

    async def run(self):
        """运行回测"""
        logger.info(
            "backtest_starting",
            data_dir=str(self.data_dir),
            speed=self.speed,
            symbols=self.symbols,
        )

        self.start_time = datetime.now()
        
        # 加载数据并开始回放
        self.data_replay.load_data()
        self.data_replay.start_replay()

        try:

            # 主回测循环
            while not self.data_replay.is_finished():
                # 更新回放状态，获取新的市场数据
                new_market_data = self.data_replay.update()
                
                # 处理每个新的市场数据快照
                for market_data in new_market_data:
                    symbol = market_data.symbol
                    
                    # 跳过不需要交易的交易对
                    if symbol not in self.symbols:
                        continue
                    
                    # 市场数据已由 DataReplayEngine 验证，无需再次检查
                    # 计算信号
                    signal_score = self.signal_aggregator.calculate(market_data)
                    self.signals_count += 1

                    # 信号分级
                    confidence_level = self.signal_classifier.classify(signal_score.value)
                    # 更新 signal_score 的置信度
                    from dataclasses import replace
                    signal_score = replace(signal_score, confidence=confidence_level)
                    confidence = signal_score.confidence

                    # 跳过低置信度信号
                    if confidence == ConfidenceLevel.LOW:
                        continue

                    # 风控检查
                    position = self.position_manager.get_position(symbol)
                    current_position_value = (
                        position.position_value_usd if position else Decimal("0")
                    )
                    
                    # 确定订单方向
                    from src.core.types import Order, OrderStatus, OrderType
                    
                    if signal_score.value > 0:
                        side = OrderSide.BUY
                    elif signal_score.value < 0:
                        side = OrderSide.SELL
                    else:
                        continue  # 零信号跳过
                    
                    # 创建模拟订单进行风控检查
                    test_order = Order(
                        id="test",
                        symbol=symbol,
                        side=side,
                        order_type=OrderType.LIMIT,
                        price=market_data.mid_price,
                        size=self.maker_executor.default_size,
                        filled_size=Decimal("0"),
                        status=OrderStatus.PENDING,
                        created_at=market_data.timestamp,
                    )
                    
                    is_allowed, reject_reason = self.hard_limits.check_order(
                        test_order, market_data.mid_price, current_position_value
                    )
                    
                    if not is_allowed:
                        logger.warning(
                            "order_rejected_by_risk_control",
                            symbol=symbol,
                            reason=reject_reason,
                            confidence=confidence.name,
                        )
                        continue

                    # 执行交易
                    order = await self.hybrid_executor.execute(signal_score, market_data)

                    if order and order.filled_size > 0:
                        self.trades_count += 1

                        # 更新仓位
                        self.position_manager.update_from_order(order, order.price)

                        # PnL 归因
                        attribution = self.pnl_attribution.attribute_trade(
                            order=order,
                            signal_value=signal_score.value,
                            reference_price=market_data.mid_price,
                            actual_fill_price=order.price,
                            best_price=market_data.bids[0].price
                            if order.side.name == "SELL"
                            else market_data.asks[0].price,
                        )

                        # 记录 Maker 成交率
                if order.order_type.name == "LIMIT":
                    self.fill_rate_monitor.record_maker_attempt(
                        order=order,
                        confidence=confidence,
                        filled=True,
                    )

                logger.info(
                            "trade_completed",
                            symbol=symbol,
                            order_id=order.id,
                            side=order.side.name,
                            size=float(order.filled_size),
                            order_type=order.order_type.name,
                            confidence=confidence.name,
                            pnl=float(attribution.total_pnl),
                            alpha_pct=float(attribution.alpha_percentage),
                        )

                # 短暂等待（避免过度消耗CPU）
                await asyncio.sleep(0.01)

        finally:
            self.end_time = datetime.now()
            logger.info("backtest_completed")

    def generate_report(self) -> dict:
        """生成回测报告"""
        duration = (self.end_time - self.start_time).total_seconds() if self.end_time else 0

        # PnL 统计
        pnl_stats = self.pnl_attribution.get_summary()

        # Maker 成交率统计
        fill_rate_stats = self.fill_rate_monitor.get_stats()

        report = {
            "overview": {
                "data_dir": str(self.data_dir),
                "symbols": self.symbols,
                "replay_speed": self.speed,
                "duration_seconds": duration,
                "trades_count": self.trades_count,
                "signals_count": self.signals_count,
            },
            "pnl": {
                "total": float(pnl_stats["total_pnl"]),
                "alpha": float(pnl_stats["alpha"]),
                "alpha_pct": float(pnl_stats["alpha_pct"] * 100),
                "fee": float(pnl_stats["fee"]),
                "slippage": float(pnl_stats["slippage"]),
                "impact": float(pnl_stats["impact"]),
                "trades": pnl_stats["trades_count"],
            },
            "execution": {
                "maker_fill_rate_high": float(fill_rate_stats["high_fill_rate"]),
                "maker_fill_rate_medium": float(fill_rate_stats["medium_fill_rate"]),
                "overall_fill_rate": float(fill_rate_stats["overall_fill_rate"]),
                "maker_executions": fill_rate_stats["maker_fills"],
                "ioc_executions": self.trades_count - fill_rate_stats["maker_fills"],
            },
            "health": {
                "alpha_healthy": pnl_stats["alpha_pct"] >= self.config.analytics.pnl_attribution.health_check.min_alpha_pct,
                "maker_fill_rate_healthy": fill_rate_stats["high_fill_rate"] >= self.config.validation.execution.min_maker_fill_rate_high,
            },
        }

        return report

    def print_report(self, report: dict):
        """打印回测报告"""
        print("\n" + "=" * 80)
        print("📊 Week 1.5 Maker/Taker 混合策略回测报告")
        print("=" * 80)

        # 概览
        print("\n【回测概览】")
        print(f"  数据目录: {report['overview']['data_dir']}")
        print(f"  交易对: {', '.join(report['overview']['symbols'])}")
        print(f"  回放速度: {report['overview']['replay_speed']}x")
        print(f"  执行时长: {report['overview']['duration_seconds']:.1f} 秒")
        print(f"  信号数量: {report['overview']['signals_count']:,}")
        print(f"  交易数量: {report['overview']['trades_count']:,}")

        # PnL
        print("\n【PnL 归因】")
        print(f"  总 PnL: ${report['pnl']['total']:.2f}")
        print(f"  Alpha: ${report['pnl']['alpha']:.2f} ({report['pnl']['alpha_pct']:.1f}%)")
        print(f"  手续费: ${report['pnl']['fee']:.2f}")
        print(f"  滑点: ${report['pnl']['slippage']:.2f}")
        print(f"  冲击: ${report['pnl']['impact']:.2f}")
        print(f"  平均每笔: ${report['pnl']['total'] / max(report['pnl']['trades'], 1):.4f}")

        # 执行
        print("\n【执行统计】")
        print(f"  Maker 成交率 (HIGH): {report['execution']['maker_fill_rate_high']:.1%}")
        print(f"  Maker 成交率 (MEDIUM): {report['execution']['maker_fill_rate_medium']:.1%}")
        print(f"  总体成交率: {report['execution']['overall_fill_rate']:.1%}")
        print(f"  Maker 执行: {report['execution']['maker_executions']}")
        print(f"  IOC 执行: {report['execution']['ioc_executions']}")

        # 健康度
        print("\n【健康检查】")
        alpha_status = "✅ 通过" if report['health']['alpha_healthy'] else "❌ 失败"
        fill_rate_status = "✅ 通过" if report['health']['maker_fill_rate_healthy'] else "❌ 失败"
        print(f"  Alpha 健康度: {alpha_status} (>= 70%)")
        print(f"  Maker 成交率: {fill_rate_status} (>= 80%)")

        print("\n" + "=" * 80 + "\n")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Week 1.5 Maker/Taker 混合策略回测")
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data/market_data/test_8hour",
        help="数据目录路径",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/paper_trading.yaml",
        help="配置文件路径",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="回放速度倍数（1.0 = 实时，10.0 = 10倍速）",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="交易对列表（默认使用配置文件）",
    )
    args = parser.parse_args()

    # 配置日志
    setup_logging()

    # 创建回测引擎
    engine = BacktestEngine(
        config_path=args.config,
        data_dir=args.data_dir,
        speed=args.speed,
        symbols=args.symbols,
    )

    # 运行回测
    await engine.run()

    # 生成并打印报告
    report = engine.generate_report()
    engine.print_report(report)


if __name__ == "__main__":
    asyncio.run(main())
