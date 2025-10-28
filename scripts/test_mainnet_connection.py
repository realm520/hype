"""Mainnet 连接测试脚本

测试与 Hyperliquid mainnet 的连接，验证数据接收质量。
在运行影子交易前执行，确保连接正常。

用法：
    python scripts/test_mainnet_connection.py
    python scripts/test_mainnet_connection.py --duration 60  # 测试 60 秒
"""

import argparse
import asyncio
import time
from datetime import datetime

import structlog

from src.core.data_feed import MarketDataManager
from src.hyperliquid.websocket_client import HyperliquidWebSocket

logger = structlog.get_logger()


class ConnectionTester:
    """连接测试器"""

    def __init__(self, use_mainnet: bool = True, test_duration: int = 30):
        """
        初始化连接测试器

        Args:
            use_mainnet: 是否使用 mainnet（默认 True）
            test_duration: 测试持续时间（秒）
        """
        self.use_mainnet = use_mainnet
        self.test_duration = test_duration
        self.symbols = ["BTC", "ETH"]

        # 统计数据
        self.stats: dict[str, dict[str, int]] = {
            symbol: {
                "l2_updates": 0,
                "trade_updates": 0,
                "last_update_timestamp": 0,
            }
            for symbol in self.symbols
        }
        self.connection_issues: list[str] = []

        logger.info(
            "connection_tester_initialized",
            use_mainnet=use_mainnet,
            test_duration=test_duration,
        )

    async def run_test(self) -> dict[str, any]:
        """
        运行连接测试

        Returns:
            Dict: 测试结果
        """
        logger.info("connection_test_starting")

        # 创建 WebSocket 客户端
        ws_client = HyperliquidWebSocket(self.use_mainnet)
        data_manager = MarketDataManager(ws_client)

        try:
            # 1. 测试连接
            logger.info("testing_websocket_connection")
            await data_manager.start(self.symbols)

            # 等待初始数据
            logger.info("waiting_for_initial_data")
            await asyncio.sleep(3)

            # 2. 验证初始数据
            initial_data_ok = await self._verify_initial_data(data_manager)

            if not initial_data_ok:
                logger.error("initial_data_verification_failed")
                return {
                    "success": False,
                    "error": "未收到初始数据或数据不完整",
                }

            # 3. 持续监控数据质量
            logger.info("monitoring_data_quality", duration=self.test_duration)
            start_time = time.time()
            end_time = start_time + self.test_duration

            while time.time() < end_time:
                await self._check_data_quality(data_manager)
                await asyncio.sleep(1)

            # 4. 生成测试报告
            test_result = self._generate_test_report(start_time, time.time())

            logger.info("connection_test_completed", success=test_result["success"])

            return test_result

        except Exception as e:
            logger.error("connection_test_error", error=str(e), exc_info=True)
            return {
                "success": False,
                "error": str(e),
            }

        finally:
            # 停止数据管理器
            await data_manager.stop()

    async def _verify_initial_data(
        self, data_manager: MarketDataManager
    ) -> bool:
        """验证初始数据"""
        logger.info("verifying_initial_data")

        all_ok = True

        for symbol in self.symbols:
            market_data = data_manager.get_market_data(symbol)

            if not market_data:
                logger.error("no_initial_data", symbol=symbol)
                self.connection_issues.append(f"{symbol}: 未收到初始数据")
                all_ok = False
                continue

            # 检查订单簿
            if not market_data.bids or not market_data.asks:
                logger.error("incomplete_orderbook", symbol=symbol)
                self.connection_issues.append(f"{symbol}: 订单簿不完整")
                all_ok = False
                continue

            # 检查价格合理性
            if market_data.mid_price <= 0:
                logger.error("invalid_price", symbol=symbol)
                self.connection_issues.append(f"{symbol}: 价格无效")
                all_ok = False
                continue

            logger.info(
                "initial_data_ok",
                symbol=symbol,
                mid_price=float(market_data.mid_price),
                bid_levels=len(market_data.bids),
                ask_levels=len(market_data.asks),
            )

        return all_ok

    async def _check_data_quality(
        self, data_manager: MarketDataManager
    ) -> None:
        """检查数据质量"""
        current_time = int(time.time() * 1000)

        for symbol in self.symbols:
            market_data = data_manager.get_market_data(symbol)

            if not market_data:
                continue

            # 更新统计
            if market_data.timestamp > self.stats[symbol]["last_update_timestamp"]:
                self.stats[symbol]["l2_updates"] += 1
                self.stats[symbol]["last_update_timestamp"] = market_data.timestamp

            # 检查数据新鲜度（不应超过 5 秒）
            data_age_ms = current_time - market_data.timestamp
            if data_age_ms > 5000:
                issue = (
                    f"{symbol}: 数据延迟 {data_age_ms}ms "
                    f"({datetime.fromtimestamp(market_data.timestamp / 1000).isoformat()})"
                )
                logger.warning("stale_data", symbol=symbol, age_ms=data_age_ms)
                if issue not in self.connection_issues:
                    self.connection_issues.append(issue)

            # 检查订单簿深度
            if len(market_data.bids) < 5 or len(market_data.asks) < 5:
                issue = (
                    f"{symbol}: 订单簿深度不足 "
                    f"(bids: {len(market_data.bids)}, asks: {len(market_data.asks)})"
                )
                logger.warning(
                    "shallow_orderbook",
                    symbol=symbol,
                    bid_levels=len(market_data.bids),
                    ask_levels=len(market_data.asks),
                )
                if issue not in self.connection_issues:
                    self.connection_issues.append(issue)

            # 检查价差合理性（不应超过 1%）
            best_bid = market_data.bids[0].price
            best_ask = market_data.asks[0].price
            spread_pct = float((best_ask - best_bid) / market_data.mid_price * 100)

            if spread_pct > 1.0:
                issue = f"{symbol}: 价差过大 ({spread_pct:.4f}%)"
                logger.warning("wide_spread", symbol=symbol, spread_pct=spread_pct)
                if issue not in self.connection_issues:
                    self.connection_issues.append(issue)

    def _generate_test_report(
        self, start_time: float, end_time: float
    ) -> dict[str, any]:
        """生成测试报告"""
        duration = end_time - start_time

        # 计算更新频率
        update_rates = {}
        for symbol, stats in self.stats.items():
            update_rates[symbol] = stats["l2_updates"] / duration

        # 判断测试是否成功
        success = True

        # 检查更新频率（应该 > 0.1 Hz）
        for symbol, rate in update_rates.items():
            if rate < 0.1:
                success = False
                self.connection_issues.append(
                    f"{symbol}: 更新频率过低 ({rate:.2f} Hz)"
                )

        return {
            "success": success,
            "duration_seconds": duration,
            "symbols": self.symbols,
            "update_rates": update_rates,
            "total_updates": {
                symbol: stats["l2_updates"] for symbol, stats in self.stats.items()
            },
            "issues": self.connection_issues,
        }


def print_test_report(result: dict[str, any]) -> None:
    """打印测试报告"""
    print("\n" + "=" * 80)
    print("Mainnet 连接测试报告")
    print("=" * 80)

    if result["success"]:
        print("\n✅ 测试通过")
    else:
        print("\n❌ 测试失败")

    print(f"\n测试时长: {result.get('duration_seconds', 0):.1f} 秒")
    print(f"测试交易对: {', '.join(result.get('symbols', []))}")

    # 更新统计
    print("\n数据更新统计:")
    for symbol in result.get("symbols", []):
        total_updates = result.get("total_updates", {}).get(symbol, 0)
        update_rate = result.get("update_rates", {}).get(symbol, 0)
        print(f"  - {symbol}: {total_updates} 次更新 ({update_rate:.2f} Hz)")

    # 问题列表
    issues = result.get("issues", [])
    if issues:
        print(f"\n发现 {len(issues)} 个问题:")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
    else:
        print("\n未发现问题")

    # 建议
    print("\n建议:")
    if result["success"]:
        print("  ✅ 连接正常，可以开始影子交易")
    else:
        print("  ❌ 连接存在问题，请检查网络或 API 配置")
        print("  建议:")
        print("    1. 检查网络连接")
        print("    2. 验证 Hyperliquid API 是否可用")
        print("    3. 查看日志文件获取详细错误信息")

    print("=" * 80 + "\n")


async def main() -> None:
    """主函数"""
    parser = argparse.ArgumentParser(description="测试 Mainnet 连接")
    parser.add_argument(
        "--duration",
        type=int,
        default=30,
        help="测试持续时间（秒，默认 30）",
    )
    parser.add_argument(
        "--testnet",
        action="store_true",
        help="使用 testnet 而不是 mainnet",
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
        cache_logger_on_first_use=False,
    )

    logger.info(
        "connection_test_starting",
        duration=args.duration,
        use_mainnet=not args.testnet,
    )

    # 创建测试器
    tester = ConnectionTester(
        use_mainnet=not args.testnet,
        test_duration=args.duration,
    )

    try:
        # 运行测试
        result = await tester.run_test()

        # 打印报告
        print_test_report(result)

        # 返回退出码
        exit(0 if result["success"] else 1)

    except Exception as e:
        logger.error("test_failed", error=str(e), exc_info=True)
        print(f"\n❌ 测试失败: {str(e)}\n")
        exit(1)


if __name__ == "__main__":
    asyncio.run(main())
