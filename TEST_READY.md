# 🎉 影子交易系统测试就绪

## ✅ 系统状态

### 已完成

1. **核心组件** (Phase 1-3)
   - ✅ 成交模拟器 (`fill_simulator.py`)
   - ✅ 影子执行器 (`shadow_executor.py`)
   - ✅ 影子持仓管理 (`shadow_position_manager.py`)
   - ✅ 影子分析器 (`shadow_analyzer.py`)
   - ✅ 实时监控器 (`live_monitor.py`)

2. **配置文件**
   - ✅ `config/shadow_test.yaml` - 10分钟快速测试
   - ✅ `config/shadow_mainnet.yaml` - 24小时完整验证

3. **运行脚本**
   - ✅ `scripts/run_shadow_trading.py` - 主启动脚本
   - ✅ `scripts/analyze_shadow_results.py` - 结果分析
   - ✅ `scripts/test_mainnet_connection.py` - 连接测试
   - ✅ `scripts/verify_imports.py` - 导入验证

4. **文档**
   - ✅ `docs/shadow_test_guide.md` - 完整测试指南

5. **验证结果**
   - ✅ 所有模块导入成功 (11/11)
   - ✅ 无语法错误
   - ✅ 无导入错误

---

## 🚀 立即开始

### 选项 1：10 分钟快速验证（推荐首次运行）

```bash
# 在终端执行（项目根目录）

# 1. 测试连接
.venv/bin/python3 scripts/test_mainnet_connection.py --duration 30

# 2. 运行 10 分钟测试
.venv/bin/python3 scripts/run_shadow_trading.py --config config/shadow_test.yaml

# 3. 查看结果
cat docs/shadow_test/shadow_trading_report_*.md
```

### 选项 2：1 小时验证（获得初步信号评估）

```bash
# 修改 config/shadow_test.yaml
# duration_hours: 1.0  # 改为 1 小时

# 运行
.venv/bin/python3 scripts/run_shadow_trading.py --config config/shadow_test.yaml
```

### 选项 3：24 小时完整验证（正式评估）

```bash
# 后台运行
nohup .venv/bin/python3 scripts/run_shadow_trading.py \
  --config config/shadow_mainnet.yaml \
  > logs/shadow_mainnet.log 2>&1 &

# 监控日志
tail -f logs/shadow_mainnet.log
```

---

## 📊 预期结果

### 10 分钟测试

**目标**：验证系统功能正常

**预期**：
- ✅ 无致命错误
- ✅ 能接收市场数据
- ✅ 能执行信号计算
- ✅ 能模拟订单成交
- ✅ 能生成报告

**不预期**：
- ❌ 达到上线标准（数据太少）
- ❌ IC 有统计意义
- ❌ Alpha 占比准确

### 1 小时测试

**目标**：初步评估信号质量

**预期**：
- ✅ IC 初步趋势
- ✅ Alpha 占比初步估算
- ✅ 执行效率统计
- ✅ 滑点和成本评估

### 24 小时测试

**目标**：正式决定是否上线

**标准**：
- IC ≥ 0.03
- Alpha 占比 ≥ 70%
- 成本占比 ≤ 25%
- 在线率 ≥ 99.9%
- P99 延迟 ≤ 150ms
- 胜率 ≥ 60%

**所有达标** → ✅ 可以上线真实交易

---

## 🔍 监控要点

### 实时监控（每 30 秒）

关键指标：
```json
{
  "ic": 0.032,              // ← 关注：是否 > 0.03
  "alpha_pct": 72.1,        // ← 关注：是否 > 70%
  "avg_latency_ms": 42.3,   // ← 关注：是否 < 100ms
  "fill_rate_pct": 95.8,    // ← 关注：是否 > 90%
  "total_pnl": 52.34        // ← 关注：是否为正
}
```

### 告警触发

如果看到以下告警，请检查：
- `HIGH_LATENCY` → 网络或计算瓶颈
- `LOW_FILL_RATE` → 流动性不足或滑点阈值太小
- `HIGH_DRAWDOWN` → 风控参数需要调整
- `CONSECUTIVE_LOSSES` → 信号质量问题

---

## 💡 调试技巧

### 查看实时日志

```bash
# 方式 1：tail
tail -f logs/shadow_test/trading_$(date +%Y%m%d).log

# 方式 2：grep 过滤
tail -f logs/shadow_test/trading_*.log | grep -E "alert|error|pnl"

# 方式 3：查看最新 100 条
tail -100 logs/shadow_test/trading_*.log
```

### 检查执行记录

```bash
# 查看有多少次执行
ls -lh data/shadow_test/*_records_*.parquet

# 快速分析
.venv/bin/python3 scripts/analyze_shadow_results.py --data-dir data/shadow_test
```

### 性能分析

```bash
# 如果延迟高，检查信号计算时间
grep "signal_calculation" logs/shadow_test/trading_*.log | \
  awk '{sum+=$NF; n++} END {print "平均:", sum/n, "ms"}'
```

---

## ⚠️ 重要提醒

1. **网络稳定性**
   - 测试期间保持网络连接
   - Wi-Fi 可能不够稳定，建议有线连接
   - 如果断连，系统会自动重连

2. **不会下真实订单**
   - 影子模式 100% 模拟
   - 不需要 API 私钥
   - 不会消耗资金

3. **测试时间建议**
   - 10 分钟：功能验证
   - 1 小时：初步评估
   - 24 小时：正式决策

4. **数据解读**
   - 10 分钟数据不足以评估 IC
   - 至少 1 小时才有统计意义
   - 24 小时才能准确判断

5. **如遇问题**
   - 查看 `docs/shadow_test_guide.md` 常见问题
   - 检查日志文件详细错误
   - 运行 `verify_imports.py` 确认模块正常

---

## 📞 支持资源

- **测试指南**: `docs/shadow_test_guide.md`
- **配置说明**: `config/shadow_test.yaml` 注释
- **日志目录**: `logs/shadow_test/`
- **结果目录**: `data/shadow_test/`, `docs/shadow_test/`

---

## 🎯 下一步

### 当前任务：运行 10 分钟测试

```bash
# 复制粘贴执行
cd /Users/harry/code/quants/hype
.venv/bin/python3 scripts/test_mainnet_connection.py --duration 30
.venv/bin/python3 scripts/run_shadow_trading.py --config config/shadow_test.yaml
```

### 测试成功后

选择：
- **选项 A**: 运行 1 小时测试（获得初步信号评估）
- **选项 B**: 直接运行 24 小时验证（需要耐心等待）
- **选项 C**: 继续 Phase 4（编写单元测试）

---

**祝测试顺利！** 🚀

有任何问题随时告诉我。
