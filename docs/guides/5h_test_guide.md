# 5 小时多币种影子交易测试指南

## 📋 测试概述

**测试目标**：验证系统在 ETH/SOL/ZEC 三个币种上的稳定性和信号质量

**测试时长**：5 小时

**关键配置**：
- **币种**：ETH, SOL, ZEC
- **信号阈值**：theta_1=0.7（高置信度），theta_2=0.4（中置信度）
- **IC 窗口**：2 小时（足够积累样本）
- **最小样本数**：50（严格统计要求）
- **订单类型**：IOC + 限价单混合（Week 2 模式）

---

## 🚀 快速启动

### 1. 准备工作

```bash
# 1.1 确保虚拟环境已激活
source .venv/bin/activate

# 1.2 检查依赖
python -c "import hyperliquid; import structlog; import asyncio"

# 1.3 清理旧日志（可选）
rm -rf logs/shadow_5h_test
mkdir -p logs/shadow_5h_test
```

### 2. 启动测试（推荐：后台运行）

```bash
# 2.1 后台启动测试
nohup .venv/bin/python3 scripts/run_shadow_trading.py \
    --config config/shadow_5h_test.yaml \
    > shadow_5h_test.log 2>&1 &

# 2.2 记录进程 PID
echo $! > shadow_5h_test.pid
echo "测试已启动，PID: $(cat shadow_5h_test.pid)"

# 2.3 启动监控脚本（新终端窗口）
./scripts/monitor_5h_test.sh
```

### 3. 前台运行（调试用）

```bash
# 如果需要直接查看输出
.venv/bin/python3 scripts/run_shadow_trading.py \
    --config config/shadow_5h_test.yaml
```

---

## 📊 监控指南

### 自动监控（推荐）

监控脚本会每 5 分钟自动输出：

```bash
./scripts/monitor_5h_test.sh
```

**监控内容**：
- ✅ 系统运行时间和状态
- 📈 IC 值和统计显著性
- 📋 待处理信号数量
- 💰 交易统计和盈亏
- 📊 三个币种的交易分布
- ⚠️  风险指标和回撤
- ⏱️  延迟统计

### 手动检查

```bash
# 查看实时日志
tail -f logs/trading.log

# 查看最新 100 行（JSON 格式）
tail -100 logs/trading.log | jq .

# 检查 IC 计算
grep "ic_calculated" logs/trading.log | tail -5 | jq .

# 检查交易完成情况
grep "trade_completed" logs/trading.log | jq .

# 统计各币种交易数
for symbol in ETH SOL ZEC; do
    echo "$symbol: $(grep "\"symbol\": \"$symbol\"" logs/trading.log | grep trade_completed | wc -l)"
done

# 检查风控触发
grep "risk_control_triggered" logs/trading.log | jq .
```

---

## 🎯 验证指标

测试完成后需要验证以下指标：

### 1. 信号质量 ✓
- [ ] **IC ≥ 0.03**（Spearman 相关性）
- [ ] **p 值 < 0.05**（统计显著性）
- [ ] **样本数 ≥ 50**（足够的统计样本）

### 2. PnL 结构健康 ✓
- [ ] **Alpha 占比 ≥ 70%**（盈利主要来自信号）
- [ ] **总成本 ≤ 25%**（Fee + Slip）
- [ ] **胜率 ≥ 60%**（扣除成本后）

### 3. 系统稳定性 ✓
- [ ] **运行时长 = 5 小时**（无宕机）
- [ ] **API 成功率 ≥ 99.5%**
- [ ] **p99 延迟 < 150ms**
- [ ] **无风控触发或误触发**

### 4. 币种均衡性 ✓
- [ ] **三个币种都有交易**（无偏向）
- [ ] **各币种 IC 稳健**（跨品种验证）

---

## 🛑 停止测试

### 正常停止

```bash
# 1. 查找进程 PID
cat shadow_5h_test.pid

# 2. 优雅停止（发送 SIGINT）
kill -INT $(cat shadow_5h_test.pid)

# 3. 等待 30 秒让系统保存状态
sleep 30

# 4. 确认进程已停止
ps aux | grep run_shadow_trading.py
```

### 强制停止（紧急情况）

```bash
# 强制终止
kill -9 $(cat shadow_5h_test.pid)

# 清理
rm shadow_5h_test.pid
```

---

## 📈 测试后分析

### 1. 查看完整日志

```bash
# 查看最后 200 行
tail -200 logs/trading.log | jq .

# 导出到文件
jq . logs/trading.log > logs/shadow_5h_test/formatted.json
```

### 2. 生成详细报告（TODO：待实现）

```bash
python scripts/analyze_shadow_results.py \
    --config config/shadow_5h_test.yaml \
    --output docs/shadow_5h_report.html
```

### 3. 关键指标提取

```bash
# IC 值时间序列
grep "ic_calculated" logs/trading.log | \
    jq -r '[.timestamp, .ic, .p_value, .sample_count] | @tsv' > ic_timeline.tsv

# 交易统计
grep "trade_completed" logs/trading.log | \
    jq -s '{
        total_trades: length,
        total_pnl: map(.pnl) | add,
        win_count: map(select(.pnl > 0)) | length,
        avg_pnl: (map(.pnl) | add / length)
    }'

# 币种分布
grep "trade_completed" logs/trading.log | \
    jq -s 'group_by(.symbol) |
    map({symbol: .[0].symbol, count: length, pnl: map(.pnl) | add})'
```

---

## ⚠️ 常见问题

### Q1: 测试启动后没有日志输出？

**检查步骤**：
1. 确认进程是否在运行：`ps aux | grep run_shadow_trading.py`
2. 检查日志文件是否创建：`ls -lh logs/trading.log`
3. 查看错误日志：`cat shadow_5h_test.log`
4. 检查 WebSocket 连接：`grep "websocket" logs/trading.log`

### Q2: IC 一直是 N/A？

**可能原因**：
- **样本不足**：等待至少 2 小时（IC 窗口）+ 10 分钟（未来收益）
- **信号质量过滤**：检查 `signal_quality_filtered` 事件
- **未来收益未更新**：检查 `future_returns_updated` 事件

**解决方案**：
```bash
# 检查待处理信号状态
grep "pending_signals_status" logs/trading.log | tail -5 | jq .

# 检查未来收益更新
grep "future_returns_updated" logs/trading.log | wc -l

# 诊断 IC 计算
grep "ic_diagnosis" logs/trading.log | tail -1 | jq .
```

### Q3: 风控频繁触发？

**检查**：
```bash
# 查看风控触发原因
grep "risk_control_triggered" logs/trading.log | jq .

# 查看回撤情况
grep "drawdown" logs/trading.log | jq -s 'map(.drawdown_pct) | max'
```

**调整**（谨慎）：
- 提高 `max_daily_drawdown_pct`：5% → 6%
- 提高 `max_single_loss_pct`：0.8% → 1.0%

### Q4: 某个币种没有交易？

**可能原因**：
- **流动性问题**：该币种盘口太薄
- **信号质量**：该币种信号强度不够
- **WebSocket 订阅失败**

**检查**：
```bash
# 检查 WebSocket 订阅
grep "subscribed" logs/trading.log | grep -E "(ETH|SOL|ZEC)"

# 检查各币种信号
grep "signal_generated" logs/trading.log | \
    jq -s 'group_by(.symbol) | map({symbol: .[0].symbol, count: length})'
```

---

## 📁 文件结构

测试相关文件：

```
hype/
├── config/
│   └── shadow_5h_test.yaml          # 测试配置文件
├── scripts/
│   ├── run_shadow_trading.py        # 主运行脚本
│   └── monitor_5h_test.sh           # 监控脚本
├── logs/
│   ├── trading.log                  # 主日志文件
│   └── shadow_5h_test/              # 测试专用日志目录
├── data/
│   └── shadow_5h_test/              # 测试数据存储
├── docs/
│   ├── 5h_test_guide.md             # 本文档
│   └── shadow_5h_test/              # 测试报告输出目录
├── shadow_5h_test.log               # 启动日志
└── shadow_5h_test.pid               # 进程 PID 文件
```

---

## 🎓 验证清单

测试完成后，使用此清单验证结果：

### 启动前
- [ ] 虚拟环境已激活
- [ ] 配置文件存在：`config/shadow_5h_test.yaml`
- [ ] 监控脚本可执行：`scripts/monitor_5h_test.sh`
- [ ] 旧日志已清理（可选）

### 运行中（每小时检查）
- [ ] 进程正常运行（检查 PID）
- [ ] 日志持续更新
- [ ] 三个币种都有数据
- [ ] 无异常错误或崩溃

### 完成后
- [ ] 运行时长 ≥ 5 小时
- [ ] IC ≥ 0.03（合格）
- [ ] Alpha 占比 ≥ 70%
- [ ] 总成本 ≤ 25%
- [ ] 胜率 ≥ 60%
- [ ] 无风控误触发
- [ ] 三个币种交易均衡
- [ ] p99 延迟 < 150ms

---

## 📞 支持

遇到问题？

1. **查看日志**：`tail -100 logs/trading.log | jq .`
2. **检查状态**：`./scripts/monitor_5h_test.sh`
3. **诊断脚本**：运行各种检查命令（见"常见问题"）

---

**文档版本**：v1.0
**最后更新**：2025-10-26
**适用系统**：Hyperliquid 影子交易系统 Week 2
