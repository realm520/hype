#!/usr/bin/env python3
"""验证日志系统功能

演示：
1. 文件日志写入（JSON 格式）
2. 控制台日志输出（彩色）
3. 审计日志独立记录
4. 日志级别控制
"""

import os
import sys
import time
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.logging import setup_logging, get_logger, get_audit_logger


def main():
    """主函数"""
    print("=== 日志系统验证 ===\n")

    # 设置临时日志目录
    log_dir = Path("logs/test_verify")
    log_dir.mkdir(parents=True, exist_ok=True)

    # 初始化日志系统
    print(f"1. 初始化日志系统（目录：{log_dir}）")
    setup_logging(log_dir=str(log_dir), log_level="INFO", enable_audit=True)
    print("   ✅ 日志系统初始化完成\n")

    # 获取日志记录器
    logger = get_logger(__name__)
    audit_logger = get_audit_logger()

    # 测试不同级别的日志
    print("2. 测试不同日志级别：")

    logger.debug("debug_message", detail="这条日志不会显示（级别太低）")
    print("   📝 DEBUG: 已记录（文件中可见，控制台不显示）")

    logger.info("info_message", status="normal", value=123)
    print("   📝 INFO: 已记录")

    logger.warning("warning_message", reason="test_warning", threshold=0.8)
    print("   ⚠️  WARNING: 已记录")

    logger.error("error_message", error="test_error", code=500)
    print("   ❌ ERROR: 已记录\n")

    # 测试审计日志
    print("3. 测试审计日志：")

    audit_logger.info(
        "order_executed",
        order_id="TEST-001",
        symbol="BTC",
        side="BUY",
        size=0.1,
        price=50000.0,
        status="FILLED",
    )
    print("   📋 订单执行已记录到审计日志")

    audit_logger.critical(
        "risk_control_triggered",
        trigger="max_drawdown_reached",
        reason="Daily drawdown exceeded 5%",
        current_nav=95000.0,
        action="stop_trading",
    )
    print("   🚨 风控触发已记录到审计日志\n")

    # 等待日志写入
    time.sleep(0.2)

    # 验证文件生成
    print("4. 验证日志文件：")

    trading_log = log_dir / "trading.log"
    audit_log = log_dir / "audit.log"

    if trading_log.exists():
        with open(trading_log, "r") as f:
            lines = f.readlines()
            print(f"   ✅ 交易日志：{trading_log}")
            print(f"      共 {len(lines)} 行记录")
    else:
        print(f"   ❌ 交易日志文件未创建：{trading_log}")

    if audit_log.exists():
        with open(audit_log, "r") as f:
            lines = f.readlines()
            print(f"   ✅ 审计日志：{audit_log}")
            print(f"      共 {len(lines)} 行记录")
    else:
        print(f"   ❌ 审计日志文件未创建：{audit_log}")

    print("\n5. 查看日志内容示例：")

    if trading_log.exists():
        with open(trading_log, "r") as f:
            lines = f.readlines()
            if lines:
                import json

                print("\n   交易日志最后一条：")
                last_log = json.loads(lines[-1])
                print(f"      事件: {last_log.get('event')}")
                print(f"      级别: {last_log.get('level')}")
                print(f"      时间: {last_log.get('timestamp')}")
                if "error" in last_log:
                    print(f"      错误: {last_log.get('error')}")

    if audit_log.exists():
        with open(audit_log, "r") as f:
            lines = f.readlines()
            if lines:
                import json

                print("\n   审计日志最后一条：")
                last_log = json.loads(lines[-1])
                print(f"      事件: {last_log.get('event')}")
                print(f"      级别: {last_log.get('level')}")
                print(f"      时间: {last_log.get('timestamp')}")
                if "action" in last_log:
                    print(f"      操作: {last_log.get('action')}")

    print("\n=== 验证完成 ===")
    print(f"\n💡 提示：")
    print(f"   - 查看完整日志：cat {trading_log}")
    print(f"   - 查看审计日志：cat {audit_log}")
    print(f"   - 实时监控：tail -f {trading_log}")
    print(f"   - JSON 解析：cat {trading_log} | jq .")


if __name__ == "__main__":
    main()
