#!/usr/bin/env python3
"""系统验证脚本

验证 Week 1 IOC 交易系统的所有组件是否正常工作
不会执行实际交易，仅测试系统初始化和数据流
"""

import asyncio
import sys
import time
from decimal import Decimal
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

from src.core.config import load_config
from src.main import TradingEngine

logger = structlog.get_logger()


class SystemValidator:
    """系统验证器"""

    def __init__(self, config_path: str = "config/week1_ioc.yaml"):
        """
        初始化验证器

        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path
        self.config = None
        self.engine = None
        self.validation_results = {
            "config_load": False,
            "engine_init": False,
            "data_connection": False,
            "signal_calculation": False,
            "risk_checks": False,
            "metrics_collection": False,
        }

    async def run_validation(self) -> bool:
        """
        运行完整验证

        Returns:
            bool: 验证是否全部通过
        """
        logger.info("=== 开始系统验证 ===")

        try:
            # 1. 配置加载验证
            if not await self._validate_config():
                return False

            # 2. 引擎初始化验证
            if not await self._validate_engine_init():
                return False

            # 3. 数据连接验证
            if not await self._validate_data_connection():
                return False

            # 4. 信号计算验证
            if not await self._validate_signal_calculation():
                return False

            # 5. 风控检查验证
            if not await self._validate_risk_checks():
                return False

            # 6. 指标收集验证
            if not await self._validate_metrics_collection():
                return False

            # 7. 打印验证报告
            self._print_validation_report()

            return all(self.validation_results.values())

        except Exception as e:
            logger.error("validation_error", error=str(e), exc_info=True)
            return False

        finally:
            # 清理资源
            if self.engine:
                try:
                    await self.engine.stop()
                except Exception:
                    pass

    async def _validate_config(self) -> bool:
        """验证配置加载"""
        logger.info("验证步骤 1/6: 配置加载")

        try:
            self.config = load_config(self.config_path)

            # 验证关键配置项
            assert self.config.hyperliquid.wallet_address, "缺少 wallet_address"
            assert self.config.hyperliquid.symbols, "缺少交易对列表"
            assert self.config.initial_nav > 0, "初始 NAV 必须大于 0"

            logger.info(
                "config_loaded",
                symbols=self.config.hyperliquid.symbols,
                use_mainnet=self.config.hyperliquid.use_mainnet,
                initial_nav=self.config.initial_nav,
            )

            self.validation_results["config_load"] = True
            return True

        except Exception as e:
            logger.error("config_load_failed", error=str(e), exc_info=True)
            return False

    async def _validate_engine_init(self) -> bool:
        """验证引擎初始化"""
        logger.info("验证步骤 2/6: 引擎初始化")

        try:
            self.engine = TradingEngine(self.config)

            # 验证所有组件已创建
            assert self.engine.data_manager, "数据管理器未创建"
            assert self.engine.signal_aggregator, "信号聚合器未创建"
            assert self.engine.executor, "执行器未创建"
            assert self.engine.hard_limits, "风控模块未创建"
            assert self.engine.position_manager, "持仓管理器未创建"
            assert self.engine.pnl_attribution, "PnL 归因模块未创建"
            assert self.engine.metrics_collector, "指标收集器未创建"

            logger.info("engine_initialized_successfully")
            self.validation_results["engine_init"] = True
            return True

        except Exception as e:
            logger.error("engine_init_failed", error=str(e), exc_info=True)
            return False

    async def _validate_data_connection(self) -> bool:
        """验证数据连接"""
        logger.info("验证步骤 3/6: 数据连接")

        try:
            # 启动数据管理器（仅订阅，不执行交易）
            await self.engine.data_manager.start(self.config.hyperliquid.symbols)

            # 等待接收数据
            logger.info("waiting_for_market_data")
            await asyncio.sleep(3)

            # 检查是否收到数据
            data_received = False
            for symbol in self.config.hyperliquid.symbols:
                market_data = self.engine.data_manager.get_market_data(symbol)
                if market_data:
                    logger.info(
                        "market_data_received",
                        symbol=symbol,
                        mid_price=float(market_data.mid_price),
                        bid_levels=len(market_data.bids),
                        ask_levels=len(market_data.asks),
                    )
                    data_received = True
                    break

            if not data_received:
                logger.warning("no_market_data_received")
                return False

            self.validation_results["data_connection"] = True
            return True

        except Exception as e:
            logger.error("data_connection_failed", error=str(e), exc_info=True)
            return False

    async def _validate_signal_calculation(self) -> bool:
        """验证信号计算"""
        logger.info("验证步骤 4/6: 信号计算")

        try:
            # 获取市场数据
            symbol = self.config.hyperliquid.symbols[0]
            market_data = self.engine.data_manager.get_market_data(symbol)

            if not market_data:
                logger.warning("no_market_data_for_signal_test")
                return False

            # 计算信号
            signal_score = self.engine.signal_aggregator.calculate(market_data)

            # 验证信号结构
            assert -1.0 <= signal_score.value <= 1.0, f"信号值超出范围: {signal_score.value}"
            assert signal_score.confidence in [
                "HIGH",
                "MEDIUM",
                "LOW",
            ], f"无效的置信度: {signal_score.confidence}"
            assert len(signal_score.individual_scores) == 3, "信号组件数量错误"

            logger.info(
                "signal_calculated",
                symbol=symbol,
                signal_value=signal_score.value,
                confidence=signal_score.confidence.name,
                individual_scores=[float(s) for s in signal_score.individual_scores],
            )

            self.validation_results["signal_calculation"] = True
            return True

        except Exception as e:
            logger.error("signal_calculation_failed", error=str(e), exc_info=True)
            return False

    async def _validate_risk_checks(self) -> bool:
        """验证风控检查"""
        logger.info("验证步骤 5/6: 风控检查")

        try:
            from src.core.types import Order, OrderSide, OrderStatus, OrderType

            # 创建测试订单
            test_order = Order(
                id="validation_test",
                symbol=self.config.hyperliquid.symbols[0],
                side=OrderSide.BUY,
                order_type=OrderType.IOC,
                price=Decimal("1500.0"),
                size=Decimal("1.0"),
                filled_size=Decimal("0"),
                status=OrderStatus.PENDING,
                created_at=int(time.time() * 1000),
            )

            # 测试风控检查
            is_allowed, reason = self.engine.hard_limits.check_order(
                test_order, Decimal("1500.0"), Decimal("0")
            )

            logger.info(
                "risk_check_completed",
                is_allowed=is_allowed,
                reason=reason if not is_allowed else "通过",
            )

            # 验证风控状态
            risk_status = self.engine.hard_limits.get_status()
            logger.info(
                "risk_status",
                current_nav=risk_status["current_nav"],
                daily_pnl=risk_status["daily_pnl"],
                is_breached=risk_status["is_breached"],
            )

            self.validation_results["risk_checks"] = True
            return True

        except Exception as e:
            logger.error("risk_checks_failed", error=str(e), exc_info=True)
            return False

    async def _validate_metrics_collection(self) -> bool:
        """验证指标收集"""
        logger.info("验证步骤 6/6: 指标收集")

        try:
            # 获取指标摘要
            metrics_summary = self.engine.metrics_collector.get_metrics_summary()

            logger.info(
                "metrics_summary",
                signal_quality=metrics_summary["signal_quality"],
                execution_quality=metrics_summary["execution_quality"],
            )

            # 验证 PnL 归因
            pnl_report = self.engine.pnl_attribution.get_attribution_report()
            logger.info(
                "pnl_attribution_report",
                trade_count=pnl_report["trade_count"],
                cumulative=pnl_report["cumulative"],
            )

            self.validation_results["metrics_collection"] = True
            return True

        except Exception as e:
            logger.error("metrics_collection_failed", error=str(e), exc_info=True)
            return False

    def _print_validation_report(self):
        """打印验证报告"""
        logger.info("\n" + "=" * 50)
        logger.info("系统验证报告")
        logger.info("=" * 50)

        for check, passed in self.validation_results.items():
            status = "✅ 通过" if passed else "❌ 失败"
            logger.info(f"{check:30s}: {status}")

        logger.info("=" * 50)

        if all(self.validation_results.values()):
            logger.info("✅ 系统验证全部通过！系统已准备好运行。")
        else:
            failed_checks = [k for k, v in self.validation_results.items() if not v]
            logger.error(f"❌ 验证失败项: {', '.join(failed_checks)}")

        logger.info("=" * 50 + "\n")


async def main():
    """主函数"""
    # 配置日志
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )

    # 创建验证器
    validator = SystemValidator()

    # 运行验证
    success = await validator.run_validation()

    # 退出代码
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
