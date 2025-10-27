"""验证影子交易系统所有模块导入

检查所有必需的模块是否可以成功导入。
"""

import sys
from typing import List, Tuple


def verify_imports() -> List[Tuple[str, bool, str]]:
    """验证所有导入"""
    results = []

    # 核心模块
    modules = [
        ("src.core.data_feed", "MarketDataManager"),
        ("src.core.types", "MarketData, Order, SignalScore"),
        ("src.hyperliquid.websocket_client", "HyperliquidWebSocket"),
        ("src.signals.aggregator", "create_aggregator_from_config"),
        ("src.execution.fill_simulator", "FillSimulator"),
        ("src.execution.shadow_executor", "ShadowIOCExecutor"),
        ("src.risk.shadow_position_manager", "ShadowPositionManager"),
        ("src.analytics.shadow_analyzer", "ShadowAnalyzer"),
        ("src.analytics.live_monitor", "LiveMonitor"),
    ]

    for module_path, items in modules:
        try:
            # 尝试导入
            module = __import__(module_path, fromlist=items.split(","))

            # 检查每个项目是否存在
            for item in items.split(","):
                item = item.strip()
                if not hasattr(module, item):
                    results.append(
                        (f"{module_path}.{item}", False, f"属性 {item} 不存在")
                    )
                else:
                    results.append((f"{module_path}.{item}", True, "OK"))
        except Exception as e:
            results.append((module_path, False, str(e)))

    return results


def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("影子交易系统模块导入验证")
    print("=" * 80 + "\n")

    results = verify_imports()

    success_count = sum(1 for _, success, _ in results if success)
    total_count = len(results)

    print(f"验证结果: {success_count}/{total_count} 通过\n")

    # 打印详细结果
    for module, success, message in results:
        status = "✅" if success else "❌"
        print(f"{status} {module}")
        if not success:
            print(f"   错误: {message}")

    print("\n" + "=" * 80)

    if success_count == total_count:
        print("✅ 所有模块导入成功！可以继续运行测试。")
        return 0
    else:
        print(f"❌ {total_count - success_count} 个模块导入失败，请检查错误信息。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
