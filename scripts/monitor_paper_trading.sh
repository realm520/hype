#!/bin/bash

# Paper Trading 实时监控脚本
# 用途：监控 Paper Trading 系统的运行状态、性能指标和交易活动
# 使用方法：./scripts/monitor_paper_trading.sh

set -euo pipefail

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志文件路径
LOG_FILE="logs/trading.log"

# 检查日志文件是否存在
if [ ! -f "$LOG_FILE" ]; then
    echo -e "${RED}❌ 日志文件不存在: $LOG_FILE${NC}"
    exit 1
fi

# 打印标题
echo "════════════════════════════════════════════════════════════════════════"
echo -e "${BLUE}📊 Paper Trading 实时监控面板${NC}"
echo "════════════════════════════════════════════════════════════════════════"
echo ""

# 检查进程状态
echo -e "${GREEN}━━━ 系统状态 ━━━${NC}"
if pgrep -f "python.*src.main" > /dev/null; then
    PID=$(pgrep -f "python.*src.main" | head -1)
    echo -e "${GREEN}✅ Paper Trading 正在运行 (PID: $PID)${NC}"

    # 获取进程运行时间
    ELAPSED=$(ps -p "$PID" -o etime= 2>/dev/null | tr -d ' ' || echo "未知")
    echo -e "⏱  运行时长: $ELAPSED"
else
    echo -e "${RED}❌ Paper Trading 未运行${NC}"
    exit 1
fi
echo ""

# 最新系统事件
echo -e "${GREEN}━━━ 最新系统事件 (最近 10 条) ━━━${NC}"
tail -10 "$LOG_FILE" | while IFS= read -r line; do
    # 解析 JSON 日志
    EVENT=$(echo "$line" | jq -r '.event // "unknown"' 2>/dev/null || echo "unknown")
    LEVEL=$(echo "$line" | jq -r '.level // "info"' 2>/dev/null || echo "info")
    TIMESTAMP=$(echo "$line" | jq -r '.timestamp // ""' 2>/dev/null || echo "")

    # 根据日志级别着色
    case "$LEVEL" in
        error|critical)
            COLOR=$RED
            ICON="❌"
            ;;
        warning)
            COLOR=$YELLOW
            ICON="⚠️"
            ;;
        *)
            COLOR=$NC
            ICON="ℹ️"
            ;;
    esac

    # 格式化时间戳
    if [ -n "$TIMESTAMP" ]; then
        TIME=$(echo "$TIMESTAMP" | cut -d'T' -f2 | cut -d'.' -f1)
    else
        TIME="--:--:--"
    fi

    echo -e "${COLOR}${ICON} [$TIME] $EVENT${NC}"
done
echo ""

# 检查错误和警告
echo -e "${GREEN}━━━ 错误和警告统计 (最近 100 条日志) ━━━${NC}"
ERROR_COUNT=$(tail -100 "$LOG_FILE" | jq -r 'select(.level == "error")' 2>/dev/null | wc -l | tr -d ' ')
WARNING_COUNT=$(tail -100 "$LOG_FILE" | jq -r 'select(.level == "warning")' 2>/dev/null | wc -l | tr -d ' ')

if [ "$ERROR_COUNT" -gt 0 ]; then
    echo -e "${RED}❌ 错误: $ERROR_COUNT${NC}"
else
    echo -e "${GREEN}✅ 错误: $ERROR_COUNT${NC}"
fi

if [ "$WARNING_COUNT" -gt 0 ]; then
    echo -e "${YELLOW}⚠️  警告: $WARNING_COUNT${NC}"
else
    echo -e "${GREEN}✅ 警告: $WARNING_COUNT${NC}"
fi
echo ""

# WebSocket 连接状态
echo -e "${GREEN}━━━ WebSocket 连接状态 ━━━${NC}"
WS_CONNECTED=$(tail -50 "$LOG_FILE" | jq -r 'select(.event == "Websocket connected")' 2>/dev/null | wc -l | tr -d ' ')
if [ "$WS_CONNECTED" -gt 0 ]; then
    echo -e "${GREEN}✅ WebSocket 已连接${NC}"
else
    echo -e "${YELLOW}⚠️  WebSocket 状态未知${NC}"
fi
echo ""

# 信号统计（如果有）
echo -e "${GREEN}━━━ 信号统计 (如果可用) ━━━${NC}"
SIGNAL_COUNT=$(tail -100 "$LOG_FILE" | jq -r 'select(.event == "signal_calculated")' 2>/dev/null | wc -l | tr -d ' ')
if [ "$SIGNAL_COUNT" -gt 0 ]; then
    echo -e "📊 信号生成次数: $SIGNAL_COUNT"
else
    echo -e "${YELLOW}⚠️  暂无信号生成记录${NC}"
fi
echo ""

# 实时日志监控提示
echo "════════════════════════════════════════════════════════════════════════"
echo -e "${BLUE}💡 实时日志监控命令：${NC}"
echo -e "   tail -f $LOG_FILE | jq ."
echo "════════════════════════════════════════════════════════════════════════"
echo ""

# 控制面板提示
echo -e "${YELLOW}📝 注意事项：${NC}"
echo "   1. 按 Ctrl+C 停止监控"
echo "   2. Paper Trading 使用模拟资金 \$1,000"
echo "   3. 所有交易都是模拟的，不会影响真实资金"
echo "   4. 查看详细日志: tail -100 $LOG_FILE | jq ."
echo ""
