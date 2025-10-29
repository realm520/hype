# Week 1 IOC-only 策略归档文档

## 归档原因

**策略废弃日期**：2025-10-29

经过多窗口 IC 分析和费用结构验证，发现 **Week 1 IOC-only 策略数学上不可行**：

### 致命缺陷

1. **成本假设错误**：
   - ❌ 原假设：单边成本 7.5 bps
   - ✅ 实际：往返成本 = 开仓 7.5 bps + 平仓 7.5 bps = **15 bps**

2. **期望收益公式错误**：
   - ❌ 原公式：`E[return] = IC × σ × 2`
   - ✅ 正确公式：`E[return] = IC × σ × z-score(signal)`
   - Top 20% 信号的 z-score = 0.84 std（不是 2.0！）

### 盈利性分析

基于 5 分钟窗口实测数据：
```
IC = 0.37（OBI 信号）
σ(returns) = 45 bps/5min
Top 20% 信号期望收益 = 0.37 × 45 × 0.84 = 14.0 bps
IOC-only 往返成本 = 15 bps

净收益 = 14.0 - 15 = -1.0 bps ❌ 亏损！
```

## 战略转向

**新方案**：Week 1.5 Maker/Taker 混合策略

通过 Maker 开仓降低成本 27%：
```
Maker 开仓：3.5 bps（1.5 fee + 1.0 slip + 1.0 impact）
Taker 平仓：7.5 bps（4.5 fee + 2.0 slip + 1.0 impact）
往返成本：11 bps（vs IOC-only 15 bps）

Top 20% 信号净收益 = 14.0 - 11 = +3.0 bps ✅ 盈利！
```

## 核心参考文档

Week 1.5 混合策略的核心文档（位于 `docs/` 根目录）：

1. **hybrid_strategy_design.md** - Week 1.5 混合策略完整设计
2. **revised_roadmap.md** - 修正后的项目路线图
3. **week1_strategy_reassessment.md** - 战略转折点分析
4. **multiwindow_ic_analysis_corrected.md** - 修正版多窗口 IC 分析
5. **strategy_review.md** - 更新后的策略评审方案

## 归档文件列表

本目录包含以下过时文档：

1. **multiwindow_ic_analysis.md** - 原始版多窗口 IC 分析（包含错误的盈利模型）
2. **week1_baseline_report.md** - Week 1 IOC-only 基线报告
3. **DAY7_VALIDATION_REPORT.md** - Day 7 测试报告（基于废弃策略）
4. **architecture_design.md**（待确认）- 可能基于 IOC-only 的架构设计

## 历史价值

虽然策略已废弃，但这些文档仍有历史价值：

- **学习教训**：避免重复相同的盈利模型错误
- **测试方法**：71/71 测试通过的质量工程方法论
- **开发流程**：完整的策略开发和验证流程记录
- **战略决策**：记录了从错误到修正的完整过程

---

**文档归档日期**：2025-10-29
**归档人**：开发团队
**项目状态**：Week 1.5 Maker/Taker 混合策略开发中
