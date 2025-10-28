# 影子交易系统测试指南

## ✅ 系统验证完成

所有核心模块已成功导入并验证：
- ✅ 数据接入层 (MarketDataManager, WebSocket)
- ✅ 信号层 (Aggregator, OBI, Microprice, Impact)
- ✅ 执行层 (FillSimulator, ShadowIOCExecutor)
- ✅ 持仓管理 (ShadowPositionManager)
- ✅ 分析层 (ShadowAnalyzer, LiveMonitor)

---

## 🚀 快速开始（10 分钟测试）

### 步骤 1：测试 Mainnet 连接

```bash
# 在项目根目录执行
.venv/bin/python3 scripts/test_mainnet_connection.py --duration 30
```

**预期输出**：
```
================================================================================
Mainnet 连接测试报告
================================================================================

✅ 测试通过

测试时长: 30.2 秒
测试交易对: BTC-USD, ETH-USD

数据更新统计:
  - BTC-USD: 302 次更新 (10.01 Hz)
  - ETH-USD: 298 次更新 (9.87 Hz)

未发现问题

建议:
  ✅ 连接正常，可以开始影子交易
================================================================================
```

**如果出现错误**：
- 检查网络连接
- 验证 Hyperliquid API 是否可用: `curl https://api.hyperliquid.xyz`
- 查看日志详细错误

---

### 步骤 2：运行 10 分钟影子交易测试

```bash
# 使用测试配置（10分钟）
.venv/bin/python3 scripts/run_shadow_trading.py --config config/shadow_test.yaml
```

**运行过程**：
```
2025-10-26 10:00:00 [INFO] shadow_trading_system_starting
2025-10-26 10:00:01 [INFO] shadow_trading_engine_initializing
2025-10-26 10:00:02 [INFO] waiting_for_initial_data
2025-10-26 10:00:05 [INFO] shadow_trading_started
                            start_time=2025-10-26T10:00:05
                            end_time=2025-10-26T10:10:05
2025-10-26 10:00:05 [INFO] main_loop_started
```

**监控日志**（每 30 秒一次）：
```json
{
  "timestamp": "2025-10-26T10:01:00",
  "event": "live_monitor_update",
  "ic": 0.0312,
  "ic_p_value": 0.0156,
  "avg_latency_ms": 42.3,
  "p99_latency_ms": 87.5,
  "fill_rate_pct": 95.8,
  "avg_slippage_bps": 3.2,
  "max_drawdown_pct": 0.8,
  "total_pnl": 52.34,
  "alpha_pct": 72.1,
  "cost_pct": 27.9,
  "win_rate_pct": 61.2
}
```

**10 分钟后自动停止**：
```
2025-10-26 10:10:05 [INFO] duration_completed duration_hours=0.167
2025-10-26 10:10:05 [INFO] main_loop_completed
2025-10-26 10:10:05 [INFO] shadow_trading_stopping
2025-10-26 10:10:06 [INFO] generating_final_report
2025-10-26 10:10:07 [INFO] final_report_generated
                            ready_for_launch=False  # 10分钟数据不足
                            launch_score=45.3
```

---

### 步骤 3：查看测试结果

#### 3.1 查看最终报告

```bash
# Markdown 报告
cat docs/shadow_test/shadow_trading_report_*.md

# 或打开 HTML 报告（浏览器）
open docs/shadow_test/shadow_trading_report_*.html
```

**报告示例**：
```markdown
# 影子交易验证报告

**生成时间**: 2025-10-26T10:10:07
**运行时长**: 0.2 小时
**上线准备度**: 45.3/100 ❌

---

## 1. 信号质量
- **IC**: 0.0312
- **IC p-value**: 0.0156
- **Top 20% 收益**: 0.0023
- **Bottom 20% 收益**: -0.0018
- **样本数**: 45

## 2. 执行效率
- **平均延迟**: 42.3 ms
- **P99 延迟**: 87.5 ms
- **成交率**: 95.8%
- **平均滑点**: 3.2 bps

## 3. PnL 归因
- **总盈亏**: $52.34
- **Alpha**: $67.82 (72.1%)
- **手续费**: -$8.23
- **滑点**: -$7.25
- **交易次数**: 45
- **胜率**: 61.2%

## 4. 风控表现
- **最大回撤**: 0.8%
- **夏普比率**: 1.82
- **连续亏损**: 2
- **在线率**: 100.0%

## 5. 上线建议
❌ **未满足上线标准，需要改进**

需要改进的指标:
- 样本数不足（需要 24 小时数据）
```

#### 3.2 分析执行记录

```bash
# 生成详细分析
.venv/bin/python3 scripts/analyze_shadow_results.py \
  --data-dir data/shadow_test \
  --format both \
  --output test_analysis

# 查看结果
cat test_analysis.md
open test_analysis.html
```

---

## 📊 测试结果解读

### ✅ 系统正常的标志

1. **连接稳定**：
   - 更新频率 > 5 Hz
   - 数据延迟 < 1 秒
   - 无频繁断线重连

2. **执行流畅**：
   - 平均延迟 < 100ms
   - P99 延迟 < 150ms
   - 成交率 > 90%

3. **无致命错误**：
   - 无 Python 异常
   - 无数据解析错误
   - 无订单簿重建失败

### ⚠️ 需要关注的问题

1. **IC 偏低** (< 0.02)
   - 可能原因：信号参数需要调整
   - 解决：调整 theta_1/theta_2 阈值
   - 建议：先运行 24 小时获取更多数据

2. **Alpha 占比低** (< 60%)
   - 可能原因：交易成本过高
   - 解决：减小订单尺寸或降低交易频率
   - 建议：分析 PnL 归因找出成本来源

3. **延迟过高** (P99 > 200ms)
   - 可能原因：网络问题或计算瓶颈
   - 解决：优化信号计算或改善网络
   - 建议：使用 `--ultrathink` 模式深度分析

---

## 🔧 常见问题

### Q1: 连接测试失败

**错误**：`connection_test_error: timeout`

**解决**：
```bash
# 1. 检查网络
curl -v https://api.hyperliquid.xyz

# 2. 检查防火墙/代理
```

### Q2: 影子交易启动失败

**错误**：`initial_data_verification_failed`

**解决**：
```bash
# 延长等待时间（修改 run_shadow_trading.py）
# 将 await asyncio.sleep(5) 改为 await asyncio.sleep(10)
```

### Q3: IC 计算失败

**错误**：`ic_calculation_error: insufficient samples`

**解决**：
- 10 分钟测试数据太少，这是正常的
- 至少需要运行 1 小时才能得到有意义的 IC
- 24 小时完整测试才能准确评估

### Q4: 没有看到任何交易

**原因**：
- 信号强度不够（|score| < theta_1 = 0.5）
- 市场波动小，没有触发交易信号

**解决**：
```bash
# 降低阈值（测试用）
# 编辑 config/shadow_test.yaml
# theta_1: 0.3  # 从 0.5 降低到 0.3
```

---

## 📈 下一步

### ✅ 测试成功后

如果 10 分钟测试一切正常（无致命错误），进行 **1 小时完整测试**：

```bash
# 修改配置
# config/shadow_test.yaml 中 duration_hours: 1.0

# 运行 1 小时
.venv/bin/python3 scripts/run_shadow_trading.py --config config/shadow_test.yaml
```

### ✅ 1 小时测试通过后

进行 **24 小时正式验证**：

```bash
# 使用 nohup 后台运行
nohup .venv/bin/python3 scripts/run_shadow_trading.py \
  --config config/shadow_mainnet.yaml \
  > logs/shadow_mainnet.log 2>&1 &

# 查看实时日志
tail -f logs/shadow_mainnet.log

# 或使用 screen/tmux
screen -S shadow_trading
.venv/bin/python3 scripts/run_shadow_trading.py --config config/shadow_mainnet.yaml
# Ctrl+A D 分离会话
```

### ✅ 24 小时验证完成后

检查上线标准：
- IC ≥ 0.03 ✅
- Alpha 占比 ≥ 70% ✅
- 成本占比 ≤ 25% ✅
- 在线率 ≥ 99.9% ✅
- P99 延迟 ≤ 150ms ✅
- 胜率 ≥ 60% ✅

**所有标准满足** → 可以切换到真实交易！

---

## 📝 重要提醒

1. **影子模式不下单**：所有执行都是模拟的，不会消耗真实资金
2. **网络稳定性重要**：确保测试期间网络稳定，避免数据断连
3. **数据量要求**：10 分钟只是功能验证，需要 24 小时才能准确评估
4. **市场条件影响**：不同市场状态（波动大小）会影响信号表现
5. **阈值需要调优**：theta_1/theta_2 可能需要根据实际情况调整

---

## 🎯 测试检查清单

- [ ] 模块导入验证通过
- [ ] Mainnet 连接测试通过（30秒）
- [ ] 10 分钟影子交易无致命错误
- [ ] 查看并理解测试报告
- [ ] 1 小时测试执行完成
- [ ] 24 小时验证（可选但推荐）
- [ ] 所有上线标准满足
- [ ] 准备切换到真实交易

---

**文档版本**: v1.0
**最后更新**: 2025-10-26
