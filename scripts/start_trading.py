#!/usr/bin/env python3
"""Hyperliquid IOC 交易系统启动脚本

使用示例：
    python scripts/start_trading.py
    python scripts/start_trading.py --config config/custom.yaml
    python scripts/start_trading.py --check-config
"""

import argparse
import asyncio
import sys
from pathlib import Path

import structlog

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.config import load_config
from src.main import TradingEngine

logger = structlog.get_logger()


def setup_logging(log_level: str = "INFO"):
    """
    配置日志系统

    Args:
        log_level: 日志级别（DEBUG/INFO/WARNING/ERROR）
    """
    import logging

    # 配置structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 设置根日志级别
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper()),
    )


def check_config(config_path: str) -> bool:
    """
    检查配置文件是否有效

    Args:
        config_path: 配置文件路径

    Returns:
        bool: 配置是否有效
    """
    logger.info("checking_configuration", path=config_path)

    try:
        # 加载配置
        config = load_config(config_path)

        # 验证必需字段
        assert config.hyperliquid.wallet_address, "Missing wallet_address"
        assert config.hyperliquid.private_key, "Missing private_key"
        assert len(config.hyperliquid.symbols) > 0, "No trading symbols specified"

        # 验证风控参数
        assert 0 < config.risk.max_single_loss_pct < 1, "Invalid max_single_loss_pct"
        assert 0 < config.risk.max_daily_drawdown_pct < 1, "Invalid max_daily_drawdown_pct"
        assert config.risk.max_position_size_usd > 0, "Invalid max_position_size_usd"

        # 验证信号参数
        assert 0 < config.signals.thresholds.theta_1 <= 1, "Invalid theta_1"
        assert 0 < config.signals.thresholds.theta_2 <= 1, "Invalid theta_2"
        assert (
            config.signals.thresholds.theta_1 > config.signals.thresholds.theta_2
        ), "theta_1 must be greater than theta_2"

        logger.info(
            "configuration_valid",
            symbols=config.hyperliquid.symbols,
            use_mainnet=config.hyperliquid.use_mainnet,
            initial_nav=float(config.initial_nav),
        )

        return True

    except Exception as e:
        logger.error("configuration_invalid", error=str(e), exc_info=True)
        return False


async def run_trading_system(config_path: str):
    """
    运行交易系统

    Args:
        config_path: 配置文件路径
    """
    logger.info("loading_configuration", path=config_path)

    # 加载配置
    config = load_config(config_path)

    logger.info(
        "starting_trading_engine",
        symbols=config.hyperliquid.symbols,
        network="mainnet" if config.hyperliquid.use_mainnet else "testnet",
        initial_nav=float(config.initial_nav),
    )

    # 创建交易引擎
    engine = TradingEngine(config)

    # 设置优雅关闭
    import signal

    def shutdown_handler(signum, frame):
        logger.info("shutdown_signal_received", signal=signum)
        asyncio.create_task(engine.stop())

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        # 启动引擎
        await engine.start()

    except KeyboardInterrupt:
        logger.info("keyboard_interrupt")

    except Exception as e:
        logger.error("system_error", error=str(e), exc_info=True)
        raise

    finally:
        await engine.stop()
        logger.info("system_shutdown_complete")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="Hyperliquid IOC 高频交易系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--config",
        type=str,
        default="config/week1_ioc.yaml",
        help="配置文件路径（默认：config/week1_ioc.yaml）",
    )

    parser.add_argument(
        "--check-config",
        action="store_true",
        help="仅检查配置文件是否有效",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别（默认：INFO）",
    )

    args = parser.parse_args()

    # 配置日志
    setup_logging(args.log_level)

    # 验证配置文件存在
    config_file = Path(args.config)
    if not config_file.exists():
        logger.error("config_file_not_found", path=str(config_file))
        return 1

    # 仅检查配置
    if args.check_config:
        if check_config(args.config):
            logger.info("✅ Configuration check passed")
            return 0
        else:
            logger.error("❌ Configuration check failed")
            return 1

    # 运行交易系统
    try:
        logger.info("=" * 60)
        logger.info("🚀 Hyperliquid IOC Trading System")
        logger.info("=" * 60)

        asyncio.run(run_trading_system(args.config))

        return 0

    except Exception as e:
        logger.error("fatal_error", error=str(e), exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
