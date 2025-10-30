#!/bin/bash

# Paper Trading 1小时运行脚本
# 用途：启动 Paper Trading，运行 1 小时后自动停止并生成报告

set -e

# ============================================
# 配置参数
# ============================================
DURATION_HOURS=1
LOG_FILE="paper_trading_$(date +%Y%m%d_%H%M).log"
PID_FILE="paper_trading.pid"
VENV_PYTHON=".venv/bin/python3"

# ============================================
# 启动 Paper Trading
# ============================================
echo "╔════════════════════════════════════════════════════════════╗"
echo "║         Paper Trading 1小时测试                            ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "📅 开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "⏱️  运行时长: $DURATION_HOURS 小时"
echo "📝 日志文件: $LOG_FILE"
echo ""

# 检查虚拟环境
if [ ! -f "$VENV_PYTHON" ]; then
    echo "❌ 错误: 虚拟环境不存在，请先运行 'uv venv --python 3.11'"
    exit 1
fi

# 启动 Paper Trading（后台运行）
echo "🚀 启动 Paper Trading..."
nohup $VENV_PYTHON -m src.main > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
PID=$(cat "$PID_FILE")
echo "✅ Paper Trading 已启动 (PID: $PID)"
echo ""

# ============================================
# 等待系统初始化
# ============================================
echo "⏳ 等待系统初始化（15秒）..."
sleep 15

# 检查进程是否还在运行
if ! ps -p $PID > /dev/null 2>&1; then
    echo "❌ 错误: Paper Trading 启动失败"
    echo ""
    echo "=== 最后 20 行日志 ==="
    tail -20 "$LOG_FILE"
    exit 1
fi

echo "✅ 系统初始化完成"
echo ""

# 显示初始状态
echo "=== 初始化日志（最后 20 行）==="
tail -20 "$LOG_FILE"
echo ""

# ============================================
# 实时监控（可选）
# ============================================
echo "╔════════════════════════════════════════════════════════════╗"
echo "║  实时监控已启动                                             ║"
echo "║  按 Ctrl+C 退出监控（不会停止 Paper Trading）               ║"
echo "║  Paper Trading 将在 $DURATION_HOURS 小时后自动停止                         ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# 实时监控日志（可中断）
timeout ${DURATION_HOURS}h tail -f "$LOG_FILE" 2>/dev/null || true

# ============================================
# 停止 Paper Trading
# ============================================
echo ""
echo "⏹️  正在停止 Paper Trading..."
if ps -p $PID > /dev/null 2>&1; then
    kill $PID 2>/dev/null
    sleep 3

    # 强制终止（如果还在运行）
    if ps -p $PID > /dev/null 2>&1; then
        kill -9 $PID 2>/dev/null
    fi
    echo "✅ Paper Trading 已停止"
else
    echo "⚠️  进程已提前退出"
fi

rm -f "$PID_FILE"
echo ""

# ============================================
# 生成结果报告
# ============================================
echo "╔════════════════════════════════════════════════════════════╗"
echo "║         Paper Trading 运行结果                              ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "📅 结束时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 交易统计
TOTAL_TRADES=$(grep -c "trade_completed" "$LOG_FILE" 2>/dev/null || echo "0")
BTC_TRADES=$(grep "trade_completed" "$LOG_FILE" 2>/dev/null | grep -c "BTC" || echo "0")
ETH_TRADES=$(grep "trade_completed" "$LOG_FILE" 2>/dev/null | grep -c "ETH" || echo "0")

echo "📊 交易统计:"
echo "   总交易次数: $TOTAL_TRADES"
echo "   - BTC: $BTC_TRADES"
echo "   - ETH: $ETH_TRADES"

# 盈亏统计（macOS 兼容）
FINAL_NAV=$(grep "pnl_updated" "$LOG_FILE" 2>/dev/null | tail -1 | sed -E 's/.*current_nav=([0-9.]+).*/\1/' || echo "N/A")
DAILY_PNL=$(grep "pnl_updated" "$LOG_FILE" 2>/dev/null | tail -1 | sed -E 's/.*daily_pnl=([0-9.-]+).*/\1/' || echo "N/A")

echo ""
echo "💰 盈亏统计:"
echo "   最终净值: \$$FINAL_NAV"
echo "   日内盈亏: \$$DAILY_PNL"

if [ "$FINAL_NAV" != "N/A" ]; then
    RETURN_PCT=$(echo "scale=2; ($FINAL_NAV - 1000) / 1000 * 100" | bc)
    echo "   收益率: ${RETURN_PCT}%"
fi

# 成交率统计
MAKER_FILLS=$(grep "maker_fill_rate" "$LOG_FILE" 2>/dev/null | wc -l || echo "0")
echo ""
echo "📈 执行统计:"
echo "   Maker 成交记录: $MAKER_FILLS"

# 风控统计
RISK_BLOCKS=$(grep "position_size_limit_breach" "$LOG_FILE" 2>/dev/null | wc -l || echo "0")
echo "   风控拦截次数: $RISK_BLOCKS"

# 文件路径
echo ""
echo "📁 日志文件:"
echo "   控制台日志: $LOG_FILE"
echo "   结构化日志: logs/trading.log"
echo "   审计日志: logs/audit.log"

# ============================================
# 生成详细分析（可选）
# ============================================
echo ""
echo "📊 生成详细分析报告..."

cat > analyze_results.py << 'PYTHON_EOF'
import json
import sys
from pathlib import Path

def analyze_trading_log(log_file="logs/trading.log"):
    """分析交易日志"""
    if not Path(log_file).exists():
        print(f"⚠️  日志文件不存在: {log_file}")
        return

    stats = {
        'trades': [],
        'positions': [],
        'pnl_updates': [],
        'orders': 0,
        'fills': 0,
    }

    try:
        with open(log_file) as f:
            for line in f:
                try:
                    log = json.loads(line)
                    event = log.get('event', '')

                    if event == 'trade_completed':
                        stats['trades'].append(log)
                        stats['fills'] += 1
                    elif event == 'order_submitted':
                        stats['orders'] += 1
                    elif event == 'position_updated':
                        stats['positions'].append(log)
                    elif event == 'pnl_updated':
                        stats['pnl_updates'].append(log)
                except json.JSONDecodeError:
                    continue

        # 打印详细统计
        print("\n╔════════════════════════════════════════════════════════════╗")
        print("║         详细分析报告                                        ║")
        print("╚════════════════════════════════════════════════════════════╝\n")

        # 交易明细
        if stats['trades']:
            print("📝 最近 5 笔交易:")
            for trade in stats['trades'][-5:]:
                symbol = trade.get('symbol', 'N/A')
                side = trade.get('side', 'N/A')
                size = trade.get('size', 0)
                pnl = trade.get('pnl', 0)
                timestamp = trade.get('timestamp', '')
                print(f"   {timestamp[:19]} | {symbol:4} {side:4} {size:>8.4f} | PnL: ${pnl:>8.2f}")

        # 持仓统计
        if stats['positions']:
            print("\n📊 当前持仓:")
            latest_positions = {}
            for pos in stats['positions']:
                symbol = pos.get('symbol', 'N/A')
                latest_positions[symbol] = pos

            for symbol, pos in latest_positions.items():
                size = pos.get('size', 0)
                value = pos.get('position_value_usd', 0)
                print(f"   {symbol:4}: {size:>10.4f} 币 (${value:>10.2f})")

        # 执行效率
        if stats['orders'] > 0:
            fill_rate = stats['fills'] / stats['orders'] * 100
            print(f"\n⚡ 执行效率:")
            print(f"   订单总数: {stats['orders']}")
            print(f"   成交数量: {stats['fills']}")
            print(f"   成交率: {fill_rate:.1f}%")

        # PnL 曲线
        if stats['pnl_updates']:
            print(f"\n💹 净值曲线（最近 10 个点）:")
            for pnl in stats['pnl_updates'][-10:]:
                nav = pnl.get('current_nav', 0)
                daily_pnl = pnl.get('daily_pnl', 0)
                timestamp = pnl.get('timestamp', '')[:19]
                print(f"   {timestamp} | NAV: ${nav:>10.2f} | 日PnL: ${daily_pnl:>8.2f}")

        print("\n✅ 分析完成")

    except Exception as e:
        print(f"❌ 分析失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    analyze_trading_log()
PYTHON_EOF

$VENV_PYTHON analyze_results.py
rm -f analyze_results.py

# ============================================
# 完成提示
# ============================================
echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║  Paper Trading 测试完成                                     ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "🔍 快速查看命令:"
echo "   完整日志:    cat $LOG_FILE"
echo "   结构化日志:  tail -100 logs/trading.log | jq ."
echo "   审计日志:    tail -50 logs/audit.log | jq ."
echo ""
