#!/bin/bash
# 5 小时影子交易测试监控脚本
# 每 5 分钟输出一次关键指标

set -euo pipefail

# 配置
LOG_FILE="/Users/harry/code/quants/hype/logs/trading.log"
REPORT_INTERVAL=300  # 5 分钟
TOTAL_DURATION=$((5 * 3600))  # 5 小时

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "🚀 开始监控 5 小时影子交易测试"
echo "开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "预计结束: $(date -v +5H '+%Y-%m-%d %H:%M:%S')"
echo "监控日志: $LOG_FILE"
echo "报告间隔: 每 5 分钟"
echo "=========================================="
echo ""

START_TIME=$(date +%s)
REPORT_COUNT=0

while true; do
    ELAPSED=$(($(date +%s) - START_TIME))
    REMAINING=$((TOTAL_DURATION - ELAPSED))

    # 检查是否完成
    if [ $REMAINING -le 0 ]; then
        echo ""
        echo -e "${GREEN}✅ 测试已完成！总时长: 5 小时${NC}"
        break
    fi

    # 每 5 分钟报告一次
    if [ $((ELAPSED % REPORT_INTERVAL)) -eq 0 ] && [ $ELAPSED -gt 0 ]; then
        REPORT_COUNT=$((REPORT_COUNT + 1))
        ELAPSED_HOURS=$(awk "BEGIN {printf \"%.1f\", $ELAPSED/3600}")
        REMAINING_HOURS=$(awk "BEGIN {printf \"%.1f\", $REMAINING/3600}")

        echo ""
        echo "=========================================="
        echo -e "${YELLOW}📊 报告 #$REPORT_COUNT - $(date '+%H:%M:%S')${NC}"
        echo "进度: ${ELAPSED_HOURS}h / 5.0h (剩余: ${REMAINING_HOURS}h)"
        echo "=========================================="

        # 检查日志文件是否存在
        if [ ! -f "$LOG_FILE" ]; then
            echo -e "${RED}❌ 日志文件不存在！系统可能未启动${NC}"
            sleep 10
            continue
        fi

        # 1. 系统状态
        echo ""
        echo "🔧 系统状态:"
        LATEST_HEARTBEAT=$(tail -100 "$LOG_FILE" | grep "system_heartbeat" | tail -1)
        if [ -n "$LATEST_HEARTBEAT" ]; then
            UPTIME=$(echo "$LATEST_HEARTBEAT" | jq -r '.uptime_seconds // 0')
            UPTIME_MIN=$(awk "BEGIN {printf \"%.1f\", $UPTIME/60}")
            echo "  运行时间: ${UPTIME_MIN} 分钟"
        else
            echo -e "  ${RED}未检测到心跳信号${NC}"
        fi

        # 2. 信号质量
        echo ""
        echo "📈 信号质量:"
        LATEST_IC=$(tail -200 "$LOG_FILE" | grep "ic_calculated" | tail -1)
        if [ -n "$LATEST_IC" ]; then
            IC_VALUE=$(echo "$LATEST_IC" | jq -r '.ic // "N/A"')
            P_VALUE=$(echo "$LATEST_IC" | jq -r '.p_value // "N/A"')
            SAMPLE_COUNT=$(echo "$LATEST_IC" | jq -r '.sample_count // 0')

            # IC 颜色判断
            if [ "$IC_VALUE" != "N/A" ]; then
                IC_FLOAT=$(echo "$IC_VALUE" | awk '{printf "%.4f", $1}')
                if (( $(echo "$IC_FLOAT >= 0.03" | bc -l) )); then
                    IC_STATUS="${GREEN}✅ 达标${NC}"
                elif (( $(echo "$IC_FLOAT >= 0.02" | bc -l) )); then
                    IC_STATUS="${YELLOW}⚠️  接近${NC}"
                else
                    IC_STATUS="${RED}❌ 不达标${NC}"
                fi
                echo -e "  IC: $IC_VALUE $IC_STATUS"
            else
                echo "  IC: 尚未计算"
            fi

            echo "  P值: $P_VALUE"
            echo "  样本数: $SAMPLE_COUNT"
        else
            echo "  尚无 IC 数据"
        fi

        # 3. 待处理信号状态
        echo ""
        echo "📋 信号状态:"
        LATEST_PENDING=$(tail -100 "$LOG_FILE" | grep "pending_signals_status" | tail -1)
        if [ -n "$LATEST_PENDING" ]; then
            PENDING_COUNT=$(echo "$LATEST_PENDING" | jq -r '.pending_count // 0')
            OLDEST_AGE=$(echo "$LATEST_PENDING" | jq -r '.oldest_age_seconds // 0')
            echo "  待处理信号: $PENDING_COUNT"
            echo "  最老信号: ${OLDEST_AGE}s"
        else
            echo "  无待处理信号数据"
        fi

        # 4. 交易统计
        echo ""
        echo "💰 交易统计:"
        TRADE_COUNT=$(grep -c "trade_completed" "$LOG_FILE" || echo "0")
        echo "  完成交易: $TRADE_COUNT 笔"

        if [ $TRADE_COUNT -gt 0 ]; then
            # 计算总盈亏
            TOTAL_PNL=$(grep "trade_completed" "$LOG_FILE" | \
                jq -s 'map(.pnl // 0) | add' || echo "0")
            echo "  累计 PnL: $TOTAL_PNL USD"

            # 胜率
            WIN_COUNT=$(grep "trade_completed" "$LOG_FILE" | \
                jq -s 'map(select(.pnl > 0)) | length' || echo "0")
            if [ $TRADE_COUNT -gt 0 ]; then
                WIN_RATE=$(awk "BEGIN {printf \"%.1f\", $WIN_COUNT*100/$TRADE_COUNT}")
                echo "  胜率: ${WIN_RATE}%"
            fi
        fi

        # 5. 币种统计
        echo ""
        echo "📊 币种分布:"
        for symbol in ETH SOL ZEC; do
            COUNT=$(grep "\"symbol\": \"$symbol\"" "$LOG_FILE" | \
                grep "trade_completed" | wc -l | tr -d ' ')
            echo "  $symbol: $COUNT 笔"
        done

        # 6. 风险指标
        echo ""
        echo "⚠️  风险指标:"
        MAX_DD=$(grep "drawdown" "$LOG_FILE" | \
            jq -s 'map(.drawdown_pct // 0) | max' || echo "0")
        echo "  最大回撤: ${MAX_DD}%"

        # 检查风控触发
        RISK_TRIGGERS=$(grep -c "risk_control_triggered" "$LOG_FILE" || echo "0")
        if [ $RISK_TRIGGERS -gt 0 ]; then
            echo -e "  ${RED}⚠️  风控触发: $RISK_TRIGGERS 次${NC}"
        else
            echo -e "  ${GREEN}✓ 无风控触发${NC}"
        fi

        # 7. 延迟统计
        echo ""
        echo "⏱️  延迟统计:"
        LATEST_LATENCY=$(tail -100 "$LOG_FILE" | \
            grep "latency_ms" | tail -1 | jq -r '.latency_ms // "N/A"')
        echo "  最新延迟: ${LATEST_LATENCY}ms"

        echo ""
        echo "下次报告: $(date -v +5M '+%H:%M:%S')"
        echo "=========================================="
    fi

    sleep 10
done

echo ""
echo "🎯 测试完成总结"
echo "=========================================="
echo "总时长: 5 小时"
echo "日志文件: $LOG_FILE"
echo ""
echo "查看完整结果:"
echo "  tail -100 $LOG_FILE | jq ."
echo ""
echo "生成详细报告:"
echo "  python scripts/analyze_shadow_results.py \\"
echo "    --config config/shadow_5h_test.yaml \\"
echo "    --output docs/shadow_5h_report.html"
echo "=========================================="
