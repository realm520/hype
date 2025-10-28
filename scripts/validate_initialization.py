#!/usr/bin/env python3
"""组件初始化验证

只验证所有组件能够正确初始化，不需要网络连接
"""

import sys
from decimal import Decimal
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

logger = structlog.get_logger()


def validate_types():
    """验证类型系统"""
    try:
        from src.core.types import (
            ConfidenceLevel,
            Level,
            MarketData,
            Order,
            OrderSide,
            OrderStatus,
            OrderType,
            SignalScore,
        )

        # 创建测试对象
        test_level = Level(price=Decimal("1500.0"), size=Decimal("10.0"))
        test_market_data = MarketData(
            symbol="ETH",
            timestamp=1000000,
            bids=[test_level],
            asks=[test_level],
            mid_price=Decimal("1500.0"),
        )
        test_order = Order(
            id="test_001",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("1500.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("0"),
            status=OrderStatus.CREATED,
            created_at=1000000,
        )
        test_signal = SignalScore(
            value=0.5,
            confidence=ConfidenceLevel.HIGH,
            individual_scores=[0.2, 0.2, 0.1],
            timestamp=1000000,
        )

        logger.info("✅ 类型系统验证通过")
        return True

    except Exception as e:
        logger.error("❌ 类型系统验证失败", error=str(e), exc_info=True)
        return False


def validate_signals():
    """验证信号层"""
    try:
        from decimal import Decimal

        from src.core.types import Level, MarketData
        from src.signals.aggregator import SignalAggregator
        from src.signals.impact import ImpactSignal
        from src.signals.microprice import MicropriceSignal
        from src.signals.obi import OBISignal

        # 创建信号
        obi = OBISignal(levels=5, weight=0.4)
        micro = MicropriceSignal(weight=0.3)
        impact = ImpactSignal(window_ms=100, weight=0.3)

        # 创建聚合器
        aggregator = SignalAggregator(
            signals=[obi, micro, impact], theta_1=0.5, theta_2=0.2
        )

        # 创建测试市场数据
        test_data = MarketData(
            symbol="ETH",
            timestamp=1000000,
            bids=[Level(Decimal("1500.0"), Decimal("10.0"))],
            asks=[Level(Decimal("1500.5"), Decimal("10.0"))],
            mid_price=Decimal("1500.25"),
        )

        # 计算信号
        signal = aggregator.calculate(test_data)
        assert -1.0 <= signal.value <= 1.0

        logger.info("✅ 信号层验证通过")
        return True

    except Exception as e:
        logger.error("❌ 信号层验证失败", error=str(e), exc_info=True)
        return False


def validate_execution():
    """验证执行层（模拟模式）"""
    try:
        from decimal import Decimal

        from src.core.types import Level, MarketData, OrderSide
        from src.execution.slippage_estimator import SlippageEstimator

        # 创建滑点估算器
        estimator = SlippageEstimator(max_slippage_bps=20.0)

        # 创建测试数据
        test_data = MarketData(
            symbol="ETH",
            timestamp=1000000,
            bids=[Level(Decimal("1500.0"), Decimal("10.0"))],
            asks=[Level(Decimal("1500.5"), Decimal("10.0"))],
            mid_price=Decimal("1500.25"),
        )

        # 估算滑点
        result = estimator.estimate(test_data, OrderSide.BUY, Decimal("1.0"))
        assert "slippage_bps" in result
        assert "is_acceptable" in result

        logger.info("✅ 执行层验证通过")
        return True

    except Exception as e:
        logger.error("❌ 执行层验证失败", error=str(e), exc_info=True)
        return False


def validate_risk():
    """验证风控层"""
    try:
        from decimal import Decimal

        from src.core.types import Order, OrderSide, OrderStatus, OrderType
        from src.risk.hard_limits import HardLimits
        from src.risk.position_manager import PositionManager

        # 创建风控
        limits = HardLimits(
            initial_nav=Decimal("100000.0"),
            max_single_loss_pct=0.008,
            max_daily_drawdown_pct=0.05,
            max_position_size_usd=10000.0,
        )

        # 创建持仓管理器
        manager = PositionManager()

        # 测试订单检查
        test_order = Order(
            id="test",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("1500.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("0"),
            status=OrderStatus.CREATED,
            created_at=1000000,
        )

        is_allowed, reason = limits.check_order(
            test_order, Decimal("1500.0"), Decimal("0")
        )
        assert isinstance(is_allowed, bool)

        logger.info("✅ 风控层验证通过")
        return True

    except Exception as e:
        logger.error("❌ 风控层验证失败", error=str(e), exc_info=True)
        return False


def validate_analytics():
    """验证分析层"""
    try:
        from decimal import Decimal

        from src.analytics.metrics import MetricsCollector
        from src.analytics.pnl_attribution import PnLAttribution
        from src.core.types import Order, OrderSide, OrderStatus, OrderType

        # 创建 PnL 归因
        attribution = PnLAttribution()

        # 创建指标收集器
        collector = MetricsCollector()

        # 测试归因
        test_order = Order(
            id="test",
            symbol="ETH",
            side=OrderSide.BUY,
            order_type=OrderType.IOC,
            price=Decimal("1500.0"),
            size=Decimal("1.0"),
            filled_size=Decimal("1.0"),
            status=OrderStatus.FILLED,
            created_at=1000000,
        )

        result = attribution.attribute_trade(
            order=test_order,
            signal_value=0.8,
            reference_price=Decimal("1500.0"),
            actual_fill_price=Decimal("1500.5"),
            best_price=Decimal("1500.5"),
        )

        assert result is not None
        assert hasattr(result, "total_pnl")

        logger.info("✅ 分析层验证通过")
        return True

    except Exception as e:
        logger.error("❌ 分析层验证失败", error=str(e), exc_info=True)
        return False


def validate_config():
    """验证配置加载"""
    try:
        from src.core.config import load_config

        config = load_config("config/week1_ioc.yaml")

        assert config.hyperliquid.symbols, "缺少交易对配置"
        assert config.initial_nav > 0, "初始 NAV 必须大于 0"

        logger.info("✅ 配置加载验证通过")
        return True

    except Exception as e:
        logger.error("❌ 配置加载验证失败", error=str(e), exc_info=True)
        return False


def main():
    """主函数"""
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
        cache_logger_on_first_use=False,
    )

    logger.info("=" * 60)
    logger.info("组件初始化验证")
    logger.info("=" * 60)

    results = {
        "类型系统": validate_types(),
        "信号层": validate_signals(),
        "执行层": validate_execution(),
        "风控层": validate_risk(),
        "分析层": validate_analytics(),
        "配置加载": validate_config(),
    }

    logger.info("\n" + "=" * 60)
    logger.info("验证结果总结")
    logger.info("=" * 60)

    for component, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        logger.info(f"{component:15s}: {status}")

    logger.info("=" * 60)

    if all(results.values()):
        logger.info("🎉 所有组件初始化验证通过！")
        logger.info("下一步: 运行完整测试 (make test)")
        return 0
    else:
        failed = [k for k, v in results.items() if not v]
        logger.error(f"❌ 验证失败: {', '.join(failed)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
