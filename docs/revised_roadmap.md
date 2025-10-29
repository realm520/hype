# 修正后的项目实施路线图

**更新日期**: 2025-10-29  
**版本**: v2.0 - 基于多窗口IC分析修正  
**核心变更**: 从 Week 1 IOC-only 转向 Week 1.5 Maker/Taker 混合策略

---

## 执行摘要

**原计划问题**: Week 1 IOC-only 策略在 Level 0 费率下**数学上不可行**（Top 20% 信号净收益 -1 bps）。

**修正方案**: 采用 Maker/Taker 混合策略，降低成本 27%（15 bps → 11 bps），使 Top 20% 信号从亏损变为微利（+3 bps）。

**时间影响**: Week 1 延长 1-2 周（开发 Maker 执行器 + Paper Trading），但显著提升成功概率。

---

## 总体时间线

```
Week 0（已完成）: 数据采集 + 信号验证
Week 1.5（3周）: Maker/Taker 混合策略开发 + 验证
Week 2（2周）: 高级执行优化 + 自适应策略
Week 3（2周）: 规模化测试 + 风控强化
Week 4+: 持续运营 + 策略迭代

总计: ~7-8 周达到稳定盈利运营
```

---

## Week 0: 数据采集 + 信号验证（已完成 ✅）

### 目标
验证信号质量，确认预测能力达标。

### 已完成任务
- ✅ 采集 1 小时高质量市场数据（BTC/ETH）
- ✅ 多窗口 IC 分析（1/5/10/15 分钟）
- ✅ 数据质量评估（99.99/100 分）
- ✅ 发现盈利模型错误并修正

### 关键成果
```
IC 结果:
  1m:  0.42-0.55 ✅ (18倍目标)
  5m:  0.24-0.37 ✅ (8倍目标)
  10m: 0.13-0.20 ✅ (4-6倍目标)

结论: 信号质量优秀，但 IOC-only 不可行
```

### 关键文档
- `docs/multiwindow_ic_analysis_corrected.md` - 修正版分析报告
- `docs/week1_strategy_reassessment.md` - Week 1 策略重新评估
- `docs/hybrid_strategy_design.md` - 混合策略设计

---

## Week 1.5: Maker/Taker 混合策略（3 周）

### 目标
实现混合执行策略，验证成本降低至 11 bps，Top 20% 信号盈利。

### Phase 1: 开发（Day 1-3）

#### 任务清单
```
□ SignalClassifier - 信号强度分级器
  ├─ 实现 calibrate_thresholds() - 基于历史数据校准
  ├─ 实现 classify() - 分级逻辑（高/中/低）
  └─ 单元测试覆盖率 > 90%

□ ShallowMakerExecutor - 浅被动 Maker 执行器
  ├─ 实现 place_maker_order() - 盘口 +1 tick 挂单
  ├─ 实现超时机制（5s/3s）
  ├─ 实现订单取消逻辑
  └─ 单元测试 + Mock API 测试

□ HybridExecutor - 混合执行协调器
  ├─ 集成 Maker + IOC 执行器
  ├─ 实现分级执行逻辑
  ├─ Maker 失败回退逻辑
  └─ 集成测试

□ MakerFillRateMonitor - 成交率监控
  ├─ 实现滑动窗口统计
  ├─ 实现健康度检查
  └─ 告警集成

□ DynamicCostEstimator - 动态成本估计
  ├─ 基于成交率估计实际成本
  ├─ 实时成本更新
  └─ 与 PnL 分析集成
```

#### 关键代码文件
```
src/execution/
  ├─ signal_classifier.py       # 新增
  ├─ shallow_maker_executor.py  # 新增
  ├─ hybrid_executor.py          # 新增
  └─ ioc_executor.py             # 已存在

src/analytics/
  ├─ maker_fill_rate_monitor.py # 新增
  └─ dynamic_cost_estimator.py  # 新增
```

#### 验收标准
- ✅ 所有单元测试通过（覆盖率 > 80%）
- ✅ 集成测试通过（模拟环境）
- ✅ 代码 Review 完成

### Phase 2: Paper Trading（Day 4-10）

#### 任务清单
```
□ Paper Trading 环境搭建
  ├─ 模拟订单簿环境
  ├─ 实时数据接入（Hyperliquid WebSocket）
  ├─ 订单模拟器（延迟 + 滑点模拟）
  └─ 日志/监控系统

□ 运行 Paper Trading
  ├─ 24/7 运行 7 天
  ├─ 每日监控报告（成交率/成本/收益）
  ├─ 异常事件记录
  └─ 策略参数调优
```

#### 关键监控指标
| 指标 | 目标 | 实际 | 达成 |
|------|------|------|------|
| Maker 成交率（高置信度） | ≥ 80% | 待测 | - |
| Maker 成交率（中置信度） | ≥ 75% | 待测 | - |
| 实际往返成本 | ≤ 12 bps | 待测 | - |
| Top 20% 净收益 | ≥ +2 bps | 待测 | - |
| 端到端延迟 p99 | < 150ms | 待测 | - |

#### 决策点 1（Day 10）

**评估问题**:
1. Maker 成交率是否达标（≥ 80%/75%）？
2. 实际成本是否 ≤ 12 bps？
3. 预期净收益是否 ≥ +2 bps？

**决策树**:
```
IF 所有指标达标:
    → 进入 Phase 3（小资金实盘）
ELSE IF 成交率 70-80%:
    → 调整策略参数（提高阈值/缩短超时）
    → 重新 Paper Trading 3 天
ELSE:
    → Plan B: 回归 Top 5% 信号 + 纯 IOC
    → 或探索其他执行方式
```

### Phase 3: 小资金实盘（Day 11-21）

#### Week 1 实盘（Day 11-17）

**配置**:
```yaml
initial_capital: $5,000
max_position_size: $500 (10% 净值)
max_daily_trades: 150
symbols: [BTC, ETH]
strategy: Maker/Taker Hybrid
risk_limits:
  max_single_loss: 0.8% NAV
  max_daily_drawdown: 5%
```

**任务清单**:
```
□ Day 11: 实盘启动
  ├─ 最终配置检查
  ├─ 风控参数确认
  ├─ 监控系统启动
  └─ 首笔交易验证

□ Day 11-17: 持续监控
  ├─ 每日 PnL 分析
  ├─ 成本归因（Alpha/Fee/Slip）
  ├─ Maker 成交率跟踪
  ├─ 异常事件处理
  └─ 每日报告生成
```

#### Week 2 实盘（Day 18-21）

**配置调整**:
```yaml
capital: $10,000 (如果 Week 1 达标)
max_position_size: $800
```

**验证重点**:
- 策略容量测试（2x 资金是否影响成交率）
- 成本稳定性（规模放大是否导致滑点增加）
- 风控有效性（更大仓位下的风险管理）

#### 决策点 2（Day 17）

**评估问题**:
1. 7 日累计收益是否 > 10%？
2. 夏普比率是否 > 1.5？
3. 最大回撤是否 < 8%？
4. 实盘 vs Paper Trading 偏差是否 < 30%？

**决策树**:
```
IF 所有指标达标:
    → 放大至 $10K，进入 Week 2 实盘
ELSE IF 收益 > 0 但夏普 < 1.5:
    → 继续小资金运行，观察 2 周
    → 分析收益波动原因
ELSE IF 收益 < 0:
    → 暂停实盘，回归分析阶段
    → 检查信号/执行/成本问题
```

### 验收标准（Week 1.5 结束）

#### 必达指标
| 指标 | 目标 | 说明 |
|------|------|------|
| **Maker 成交率** | ≥ 80% | 高置信度信号 |
| **实际往返成本** | ≤ 12 bps | 平均值（含 Maker 失败） |
| **Top 20% 净收益** | ≥ +2 bps | 扣除实际成本 |
| **7 日夏普比率** | > 1.5 | 风险调整后收益 |
| **最大回撤** | < 8% | 单日或连续 3 日 |
| **实盘 vs Paper 偏差** | < 30% | 收益/成本偏差 |

#### 挑战指标（可选）
| 指标 | 目标 | 说明 |
|------|------|------|
| 日均收益 | > 3% | 超额收益 |
| 月化收益 | > 60% | 年化 >600% |
| 连续盈利天数 | ≥ 10 | 稳定性验证 |

---

## Week 2: 高级执行优化（2 周）

### 目标
在 Week 1.5 基础上，进一步优化执行效率和风险管理。

### 核心任务

#### 1. 动态成本估计优化

**问题**: 静态成本假设（11 bps）在不同市场状态下不准确。

**解决方案**:
```python
class AdaptiveCostEstimator:
    """自适应成本估计器"""
    
    def estimate_cost(
        self,
        confidence: ConfidenceLevel,
        market_state: MarketState,
        volatility: float
    ) -> Decimal:
        """
        动态估计成本
        
        考虑因素:
        - Maker 成交率（实时）
        - 市场波动率（高波动 → 高滑点）
        - 流动性（低流动性 → 高冲击）
        - 点差（宽点差 → 高成本）
        """
        base_cost = self.base_cost_by_confidence[confidence]
        
        # 波动率调整
        volatility_factor = 1.0 + (volatility - baseline_vol) / baseline_vol * 0.5
        
        # 流动性调整
        liquidity_factor = 1.0 if liquidity > threshold else 1.3
        
        # 点差调整
        spread_factor = 1.0 + (spread - normal_spread) / normal_spread * 0.3
        
        adjusted_cost = base_cost * volatility_factor * liquidity_factor * spread_factor
        
        return adjusted_cost
```

#### 2. 市场状态检测

**问题**: 所有市场状态使用相同策略，忽略了市场特性变化。

**解决方案**:
```python
class MarketStateDetector:
    """市场状态检测器"""
    
    def detect_state(self, market_data: MarketData) -> MarketState:
        """
        检测市场状态
        
        状态分类:
        - NORMAL: 正常波动，流动性充足
        - HIGH_VOL: 高波动，扩大止损
        - LOW_LIQ: 低流动性，减小尺寸
        - TRENDING: 趋势市场，延长持仓
        - CHOPPY: 震荡市场，缩短持仓
        """
        volatility = calculate_volatility(market_data, window=60)
        liquidity = calculate_liquidity(market_data)
        trend_strength = calculate_trend(market_data)
        
        if volatility > vol_threshold_high:
            return MarketState.HIGH_VOL
        elif liquidity < liq_threshold:
            return MarketState.LOW_LIQ
        elif trend_strength > trend_threshold:
            return MarketState.TRENDING
        elif is_choppy(market_data):
            return MarketState.CHOPPY
        else:
            return MarketState.NORMAL
```

#### 3. 自适应信号阈值

**问题**: 固定阈值（θ₁=0.45, θ₂=0.25）可能在不同市场状态下不是最优。

**解决方案**:
```python
class AdaptiveThresholdManager:
    """自适应阈值管理器"""
    
    def adjust_thresholds(
        self,
        recent_performance: dict,
        market_state: MarketState
    ) -> tuple[float, float]:
        """
        动态调整阈值
        
        逻辑:
        - 高波动 → 提高阈值（降低交易频率）
        - 低流动性 → 提高阈值（避免冲击）
        - 信号质量下降 → 提高阈值（更保守）
        - 成本上升 → 提高阈值（需要更高收益覆盖）
        """
        base_theta_1 = 0.45
        base_theta_2 = 0.25
        
        # 市场状态调整
        if market_state == MarketState.HIGH_VOL:
            theta_1 = base_theta_1 * 1.2
            theta_2 = base_theta_2 * 1.2
        elif market_state == MarketState.LOW_LIQ:
            theta_1 = base_theta_1 * 1.3
            theta_2 = base_theta_2 * 1.3
        else:
            theta_1 = base_theta_1
            theta_2 = base_theta_2
        
        # 性能反馈调整
        recent_ic = recent_performance.get("ic", 0.37)
        if recent_ic < 0.30:  # 信号质量下降
            theta_1 *= 1.2
            theta_2 *= 1.2
        
        return theta_1, theta_2
```

#### 4. 多品种动态权重

**问题**: BTC 和 ETH 固定权重，未考虑相对信号质量。

**解决方案**:
```python
class DynamicAssetAllocator:
    """动态资产配置器"""
    
    def allocate_capital(
        self,
        signals: dict[str, SignalScore],
        performance: dict[str, float]
    ) -> dict[str, float]:
        """
        动态分配资金
        
        考虑因素:
        - 信号强度（更强 → 更多资金）
        - 近期表现（表现好 → 增加权重）
        - 流动性（更高 → 允许更大仓位）
        """
        weights = {}
        
        for symbol in ["BTC", "ETH"]:
            signal_quality = abs(signals[symbol].value)
            recent_sharpe = performance[symbol]["sharpe_7d"]
            liquidity = get_liquidity(symbol)
            
            # 综合评分
            score = (
                signal_quality * 0.4 +
                recent_sharpe * 0.3 +
                liquidity * 0.3
            )
            
            weights[symbol] = score
        
        # 归一化
        total = sum(weights.values())
        for symbol in weights:
            weights[symbol] /= total
        
        return weights
```

### 验收标准（Week 2 结束）

| 指标 | Week 1.5 | Week 2 目标 | 说明 |
|------|----------|------------|------|
| 日均收益 | 3% | **3.5%** | 提升 0.5% |
| 夏普比率 | 1.5 | **2.0** | 风险调整后收益提升 |
| 最大回撤 | 8% | **6%** | 风险降低 |
| 成本偏差 | ±20% | **±10%** | 估计更准确 |

---

## Week 3: 规模化测试（2 周）

### 目标
验证策略在更大资金规模下的表现，测试策略容量。

### 资金放大计划

```
Week 3.1 (Day 1-7): $50K
Week 3.2 (Day 8-14): $100K（如果达标）
```

### 关键验证点

#### 1. 策略容量测试

**问题**: 更大订单是否导致成本显著上升？

**测试方法**:
```
测试不同订单尺寸:
  - Baseline: $500/单
  - 2x: $1,000/单
  - 5x: $2,500/单
  - 10x: $5,000/单

监控指标:
  - 滑点变化
  - Maker 成交率变化
  - 实际成本变化
```

**容量上限估计**:
```
如果 $5K/单 成本上升 <20%:
  → 策略容量 ≈ $500K - $1M
如果 $2.5K/单 成本上升 >30%:
  → 策略容量 ≈ $200K - $300K
```

#### 2. 多账户分散

**问题**: 单账户大额交易可能触发平台风控或影响成交率。

**解决方案**:
```
使用 2-3 个账户分散交易:
  - 主账户: $100K
  - 副账户1: $50K
  - 副账户2: $50K

优势:
  - 降低单笔订单尺寸
  - 避免平台风控
  - 提高整体成交率
```

#### 3. 风控压力测试

**场景设计**:
```
场景 1: 连续亏损
  - 模拟连续 10 笔亏损交易
  - 验证硬熔断是否触发
  - 验证资金保护机制

场景 2: 极端波动
  - 模拟价格单边暴涨/暴跌 5%
  - 验证止损是否有效
  - 验证紧急平仓逻辑

场景 3: API 异常
  - 模拟 API 延迟 >1s
  - 验证超时处理
  - 验证订单状态同步
```

### 验收标准（Week 3 结束）

| 指标 | $5K | $50K | $100K |
|------|-----|------|-------|
| 日均收益 | 3.5% | **3.2%** | **3.0%** |
| 夏普比率 | 2.0 | **1.8** | **1.6** |
| 成本增幅 | - | **<15%** | **<25%** |
| 容量验证 | - | ✅ | ✅ |

---

## Week 4+: 持续运营 + 策略迭代

### 目标
稳定盈利运营，持续优化策略和风控。

### 运营模式

#### 1. 日常监控

**每日任务**:
```
09:00 - 检查过夜仓位和 PnL
10:00 - 查看监控仪表盘（成交率/成本/收益）
12:00 - 中盘检查（异常事件处理）
18:00 - 尾盘总结
21:00 - 生成日报
```

**监控指标**:
- 实时 PnL
- Maker 成交率
- 实际成本 vs 预期
- 信号 IC（滚动 7 日）
- 风控触发次数

#### 2. 每周复盘

**周报内容**:
```
1. 性能总结
   - 周收益率
   - 夏普比率
   - 最大回撤

2. 成本分析
   - Alpha 占比
   - Fee 占比
   - Slippage 占比

3. 信号质量
   - 7 日滚动 IC
   - 分层收益分析

4. 异常事件
   - 风控触发
   - API 故障
   - 大额滑点

5. 改进建议
```

#### 3. 策略迭代

**优化方向**:
```
短期（1-2 月）:
  - 新信号研发（VWAP, Trade Flow）
  - 多品种扩展（SOL, ARB）
  - 执行优化（TWAP, Iceberg）

中期（3-6 月）:
  - 跨交易所套利
  - 做市策略（双边报价）
  - 统计套利（配对交易）

长期（6-12 月）:
  - 机器学习增强
  - 高频策略（<1s 持仓）
  - 衍生品套利
```

---

## 里程碑与关键节点

### 时间线总览

```
Week 0: ✅ 数据采集 + 信号验证（已完成）
  └─ 产出: 多窗口 IC 分析报告

Week 1.5: Maker/Taker 混合策略（3 周）
  ├─ Day 3: 开发完成
  ├─ Day 10: Paper Trading 完成（决策点 1）
  └─ Day 21: 小资金实盘完成（决策点 2）

Week 2: 高级执行优化（2 周）
  └─ Day 35: 自适应策略验证完成

Week 3: 规模化测试（2 周）
  ├─ Day 42: $50K 测试完成
  └─ Day 49: $100K 容量验证完成

Week 4+: 持续运营
  └─ 稳定盈利，策略迭代
```

### 关键决策点

**Decision Point 1**（Day 10 - Paper Trading 后）:
```
评估: Maker 成交率 + 实际成本
决策: 继续 OR 调整 OR Plan B
```

**Decision Point 2**（Day 17 - 实盘 Week 1 后）:
```
评估: 净收益 + 夏普比率 + 回撤
决策: 放大 OR 继续观察 OR 暂停
```

**Decision Point 3**（Day 35 - Week 2 后）:
```
评估: 优化效果 + 稳定性
决策: 规模化 OR 继续优化
```

**Decision Point 4**（Day 49 - Week 3 后）:
```
评估: 策略容量 + 风险可控性
决策: 满负荷运营 OR 分散账户 OR 降低规模
```

---

## 风险管理

### 主要风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| Maker 成交率不达标 | 中 | 高 | 实时监控 + 动态阈值调整 |
| 信号 IC 下降 | 中 | 高 | 7 日滚动监控 + 自动降频 |
| 成本超预期 | 低 | 中 | 动态成本估计 + 市场状态检测 |
| API 异常 | 低 | 高 | 硬熔断 + 订单状态同步 |
| 市场极端波动 | 低 | 高 | 止损 + 最大回撤限制 |

### 应急预案

**Plan B**（如果 Maker 策略失败）:
```
回归 Top 5% 信号 + 纯 IOC:
  - 净收益: +3 to +12 bps
  - 交易频率: ~25 次/天
  - 日收益: 0.5-1.0%（较低）
```

**Plan C**（如果所有策略失败）:
```
暂停交易 + 深度复盘:
  - 重新采集 1 周数据
  - 验证信号是否失效
  - 探索新的执行方式或新信号
```

---

## 资源需求

### 人力
- 主开发: 1 人（全职）
- 风控/监控: 0.5 人（兼职）
- 数据分析: 0.5 人（兼职）

### 资金
```
Week 1.5: $5K - $10K（小资金测试）
Week 2: $10K - $20K（优化验证）
Week 3: $50K - $100K（规模化测试）
Week 4+: $100K - $500K（满负荷运营）
```

### 技术
- Hyperliquid API 访问
- 实时数据订阅
- 服务器（低延迟，推荐香港/新加坡）
- 监控系统（Grafana/Prometheus）

---

## 成功标准

### 最终目标（Week 4 结束）

| 指标 | 目标 | 说明 |
|------|------|------|
| 月化收益率 | > 50% | 扣除所有成本 |
| 夏普比率 | > 1.5 | 风险调整后收益 |
| 最大回撤 | < 15% | 任意时段 |
| 连续盈利月 | ≥ 2 | 稳定性验证 |
| 策略容量 | > $500K | 可规模化 |

### 备用成功标准（保守）

| 指标 | 目标 | 说明 |
|------|------|------|
| 月化收益率 | > 30% | 可接受 |
| 夏普比率 | > 1.0 | 基本健康 |
| 最大回撤 | < 20% | 可承受 |

---

**路线图版本**: v2.0  
**最后更新**: 2025-10-29  
**下一次审查**: Week 1.5 结束后（~2025-11-19）
