# Maker/Taker 混合策略设计方案

**策略名称**: Week 1.5 Hybrid Strategy  
**设计日期**: 2025-10-29  
**预期时间线**: 2-3 周  
**目标**: 通过混合执行方式降低成本，实现 Top 20% 信号盈利

---

## 执行摘要

**核心创新**: 根据信号强度**动态选择执行方式**，高置信度使用浅被动 Maker（降低成本），中置信度使用 IOC。

**关键指标**:
```
往返成本: 11 bps（vs 纯IOC 15 bps）
成本降低: 27%
Top 20% 净收益: +3 bps（vs -1 bps）✅
Top 10% 净收益: +10 bps（vs +6 bps）✅
```

**预期性能**:
- 日交易次数: ~100 次（5分钟窗口）
- 日预期收益: +3 bps × 100 = +300 bps = **+3%/天**
- 月化收益: ~60-90%（扣除风控降频）
- 最大回撤: <8%（日均3%，连续亏损3天）

---

## 1. 策略架构

### 1.1 三层执行逻辑

```
信号计算 → 强度评估 → 执行方式选择
    ↓           ↓              ↓
  OBI/       |Score|      [High] → Maker+Taker
Microprice     |           [Mid]  → Maker尝试
               ↓           [Low]  → 跳过
          θ₁, θ₂阈值
```

### 1.2 信号强度分级

| 等级 | |Score| 范围 | 分位数 | 执行方式 | 说明 |
|------|------------|--------|----------|------|
| **高** | > θ₁ = 0.45 | Top 10% | Maker + Taker | 盘口+1 tick，5s超时 |
| **中** | θ₂ ~ θ₁ (0.25-0.45) | Top 10-30% | Maker 尝试 | 盘口+1 tick，3s超时，未成交跳过 |
| **低** | ≤ θ₂ = 0.25 | Bottom 70% | 不交易 | 信号太弱，避免噪音 |

**阈值校准方法**:
```python
# 基于历史数据的信号分布
θ₁ = np.percentile(abs(signal_values), 90)  # Top 10%
θ₂ = np.percentile(abs(signal_values), 70)  # Top 30%
```

### 1.3 成本对比

| 执行方式 | 开仓成本 | 平仓成本 | 往返成本 | 适用场景 |
|---------|---------|---------|---------|---------|
| **纯 IOC** | 7.5 bps | 7.5 bps | **15 bps** | 基线（已证明不可行） |
| **Maker + Taker** | 3.5 bps | 7.5 bps | **11 bps** | 高置信度（推荐）|
| **纯 Maker** | 3.5 bps | 3.5 bps | **7 bps** | 理想但难实现 |

**成本明细**:
```
Maker 成本:
  - Maker Fee: 1.5 bps
  - 滑点: 1.0 bps（盘口价，几乎无滑点）
  - 冲击: 1.0 bps
  - 总计: 3.5 bps

Taker 成本（IOC）:
  - Taker Fee: 4.5 bps
  - 滑点: 2.0 bps
  - 冲击: 1.0 bps
  - 总计: 7.5 bps
```

---

## 2. 核心执行逻辑

### 2.1 高置信度信号（Top 10%）

**执行流程**:
```
1. 信号触发: |Score| > θ₁ = 0.45
2. 计算目标仓位: size = f(score, NAV, risk)
3. 开仓（Maker）:
   - 买入信号: 挂单价格 = Best Bid + 1 tick
   - 卖出信号: 挂单价格 = Best Ask - 1 tick
   - 超时: 5 秒
4. 未成交处理:
   - 转 IOC: price = Best Ask（买入）or Best Bid（卖出）
   - 记录: Maker 失败事件，用于成交率监控
5. 持仓管理:
   - 目标持仓时间: 5 分钟
   - 平仓方式: IOC（确定性成交）
   - 止损: -3 bps（防止被套）
```

**示例代码**:
```python
async def execute_high_confidence(signal: SignalScore, position: Position) -> Order:
    """高置信度信号执行"""
    # 1. 计算目标尺寸
    size = calculate_position_size(signal, position.nav)
    
    # 2. Maker 开仓
    if signal.value > 0:  # 买入信号
        maker_price = orderbook.best_bid + Decimal("0.1")  # +1 tick
        order = await place_maker_order(
            side=Side.BUY,
            size=size,
            price=maker_price,
            timeout=5.0
        )
    else:  # 卖出信号
        maker_price = orderbook.best_ask - Decimal("0.1")  # -1 tick
        order = await place_maker_order(
            side=Side.SELL,
            size=size,
            price=maker_price,
            timeout=5.0
        )
    
    # 3. 未成交转 IOC
    if not order.is_filled:
        logger.warning("maker_failed", signal_score=signal.value)
        order = await place_ioc_order(
            side=order.side,
            size=size,
            price=orderbook.best_ask if order.side == Side.BUY else orderbook.best_bid
        )
    
    return order
```

### 2.2 中置信度信号（Top 10-30%）

**执行流程**:
```
1. 信号触发: θ₂ < |Score| ≤ θ₁
2. 开仓（Maker 尝试）:
   - 挂单价格: Best Bid/Ask + 1 tick
   - 超时: 3 秒（更短，避免过度等待）
3. 未成交处理:
   - 不转 IOC，直接跳过
   - 原因: 中置信度信号净收益微薄（+1-3 bps），IOC 成本过高会亏损
4. 持仓管理:
   - 同高置信度
```

**关键差异**:
- **更短超时**（3s vs 5s）- 降低价格反转风险
- **不强制成交** - 避免 IOC 成本侵蚀微薄利润

### 2.3 低置信度信号（Bottom 70%）

**执行流程**:
```
跳过交易 - 信号太弱，噪音大于信息
```

---

## 3. 盈利能力分析

### 3.1 高置信度（Top 10%）

**收益模型**（5分钟窗口）:
```
IC = 0.37
σ = 45 bps
z-score(Top 10%) = 1.28 std

预期方向性收益 = 0.37 × 45 × 1.28 = 21.3 bps
往返成本 = 11 bps（Maker 3.5 + Taker 7.5）
净收益 = 21.3 - 11 = +10.3 bps ✅
```

**期望值**（假设胜率 65%）:
```
E[trade] = 0.65 × 21.3 - 0.35 × 21.3 - 11
         = 13.8 - 7.5 - 11
         = -4.7 bps ❌

等等，这个计算有问题！
```

**修正期望值公式**:
```
正确公式:
E[trade] = p × (收益 - 成本) - (1-p) × (亏损 + 成本)

对于对称分布（收益 = 亏损 = 21.3 bps）:
E[trade] = p × (21.3 - 11) - (1-p) × (21.3 + 11)
         = 0.65 × 10.3 - 0.35 × 32.3
         = 6.7 - 11.3
         = -4.6 bps ❌

还是负的！问题在哪？
```

**重新思考**:

成本应该在盈利和亏损两边都减掉：
```
E[trade] = p × 收益 - (1-p) × 亏损 - 成本

其中"收益"和"亏损"是扣除成本前的绝对收益

对于信号质量 IC = 0.37, Top 10%：
盈利交易平均收益 = 21.3 bps（方向正确）
亏损交易平均亏损 = 21.3 bps（方向错误）

但实际上，盈利交易的绝对收益 > 亏损交易，因为信号有预测能力！

更准确的模型:
胜率 p 已经隐含在 IC 中
期望收益 = IC × σ × z-score = 21.3 bps

这个 21.3 bps 已经是考虑了胜率后的净方向性收益！

所以：
净收益 = 21.3 - 11 = +10.3 bps ✅（这是正确的）
```

### 3.2 中置信度（Top 10-30%）

**收益模型**:
```
z-score(Top 20%) = 0.84 std
预期收益 = 0.37 × 45 × 0.84 = 14.0 bps
往返成本 = 11 bps
净收益 = 14.0 - 11 = +3.0 bps ✅
```

### 3.3 完整盈利矩阵

| 信号等级 | 分位数 | 预期收益 | 成本 | 净收益 | Maker成交率 | 实际成本 | 实际净收益 |
|---------|--------|---------|------|--------|-----------|---------|-----------|
| **高** | Top 10% | 21.3 bps | 11 bps | **+10.3** ✅ | 85% | 11.6 bps | **+9.7** ✅ |
| **中** | Top 10-30% | 14.0 bps | 11 bps | **+3.0** ✅ | 75% | 12.5 bps | **+1.5** ✅ |
| **低** | Bottom 70% | - | - | **不交易** | - | - | - |

**实际成本计算**（考虑 Maker 成交率）:
```
假设 Maker 成交率 = 85%

实际成本 = 0.85 × 11 + 0.15 × 15
         = 9.35 + 2.25
         = 11.6 bps

高置信度实际净收益 = 21.3 - 11.6 = +9.7 bps ✅
```

---

## 4. 性能预测

### 4.1 日交易频率

**假设**:
```
5分钟窗口 × 24小时 = 288 个信号/天
Top 30% 信号 = 288 × 0.3 = ~86 次/天
其中:
  - Top 10%（高置信度）: ~29 次/天
  - Top 10-30%（中置信度）: ~57 次/天
```

**Maker 成交率影响**:
```
高置信度实际交易:
  Maker 成交: 29 × 0.85 = ~25 次
  转 IOC: 29 × 0.15 = ~4 次

中置信度实际交易:
  Maker 成交: 57 × 0.75 = ~43 次
  未成交跳过: 57 × 0.25 = ~14 次

总交易次数: 25 + 4 + 43 = ~72 次/天
```

### 4.2 日收益预测

**乐观场景**（Maker 成交率达标）:
```
高置信度收益: 25 × 9.7 + 4 × 6.0 = 242.5 + 24 = 266.5 bps
中置信度收益: 43 × 1.5 = 64.5 bps
日总收益: 266.5 + 64.5 = 331 bps = +3.31%/天 ✅

月化收益: 3.31% × 20 = 66.2%
年化收益: ~600-800%（考虑复利）
```

**基准场景**（Maker 成交率 80%/70%）:
```
高置信度: 23 × 9.7 + 6 × 6.0 = 223 + 36 = 259 bps
中置信度: 40 × 1.5 = 60 bps
日总收益: 259 + 60 = 319 bps = +3.19%/天 ✅

月化收益: 3.19% × 20 = 63.8%
```

**悲观场景**（Maker 成交率 75%/60%）:
```
高置信度: 22 × 9.7 + 7 × 6.0 = 213 + 42 = 255 bps
中置信度: 34 × 1.5 = 51 bps
日总收益: 255 + 51 = 306 bps = +3.06%/天 ✅

月化收益: 3.06% × 20 = 61.2%
```

### 4.3 风险指标

**最大回撤估计**:
```
单次最大亏损 = 21.3 + 11.6 = 32.9 bps
日最大亏损（连续亏损 5 次）= 32.9 × 5 = 164 bps = 1.64%
3 日连续亏损 = 1.64% × 3 = 4.92%

风控阈值（5% 日回撤）: 4.92% < 5% ✅
```

**夏普比率估计**:
```
日均收益 = 3.2%
日波动率 = 1.5%（估计）
夏普比率 = 3.2 / 1.5 = 2.13 ✅（健康）
```

---

## 5. 技术实现

### 5.1 核心模块

#### 5.1.1 信号强度分级器

```python
from enum import Enum
from decimal import Decimal

class ConfidenceLevel(Enum):
    HIGH = "high"      # Top 10%
    MEDIUM = "medium"  # Top 10-30%
    LOW = "low"        # Bottom 70%

class SignalClassifier:
    """信号强度分级器"""
    
    def __init__(self, theta_1: float = 0.45, theta_2: float = 0.25):
        self.theta_1 = theta_1  # Top 10% 阈值
        self.theta_2 = theta_2  # Top 30% 阈值
    
    def classify(self, signal_score: float) -> ConfidenceLevel:
        """分级信号强度"""
        abs_score = abs(signal_score)
        
        if abs_score > self.theta_1:
            return ConfidenceLevel.HIGH
        elif abs_score > self.theta_2:
            return ConfidenceLevel.MEDIUM
        else:
            return ConfidenceLevel.LOW
    
    def calibrate_thresholds(self, historical_signals: list[float]):
        """基于历史数据校准阈值"""
        import numpy as np
        abs_signals = np.abs(historical_signals)
        
        self.theta_1 = float(np.percentile(abs_signals, 90))
        self.theta_2 = float(np.percentile(abs_signals, 70))
        
        logger.info(
            "thresholds_calibrated",
            theta_1=self.theta_1,
            theta_2=self.theta_2
        )
```

#### 5.1.2 浅被动 Maker 执行器

```python
from typing import Optional
import asyncio

class ShallowMakerExecutor:
    """浅被动 Maker 执行器"""
    
    def __init__(
        self,
        api_client: HyperliquidAPI,
        orderbook: OrderBook,
        tick_size: Decimal = Decimal("0.1")
    ):
        self.api = api_client
        self.orderbook = orderbook
        self.tick_size = tick_size
    
    async def place_maker_order(
        self,
        side: Side,
        size: Decimal,
        timeout: float = 5.0
    ) -> Optional[Order]:
        """
        放置浅被动 Maker 订单
        
        Args:
            side: 买/卖方向
            size: 订单尺寸
            timeout: 超时时间（秒）
        
        Returns:
            成交订单或 None
        """
        # 1. 计算挂单价格（盘口 +/- 1 tick）
        if side == Side.BUY:
            price = self.orderbook.best_bid + self.tick_size
        else:
            price = self.orderbook.best_ask - self.tick_size
        
        # 2. 提交限价单
        order = await self.api.place_order(
            symbol=self.orderbook.symbol,
            side=side,
            size=size,
            price=price,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.GTC  # Good Till Cancel
        )
        
        # 3. 等待成交（带超时）
        try:
            filled_order = await asyncio.wait_for(
                self._wait_for_fill(order.id),
                timeout=timeout
            )
            
            logger.info(
                "maker_filled",
                order_id=order.id,
                price=float(price),
                size=float(size),
                fill_time=filled_order.fill_time
            )
            
            return filled_order
            
        except asyncio.TimeoutError:
            # 4. 超时取消订单
            await self.api.cancel_order(order.id)
            
            logger.warning(
                "maker_timeout",
                order_id=order.id,
                wait_time=timeout
            )
            
            return None
    
    async def _wait_for_fill(self, order_id: str) -> Order:
        """轮询订单状态直到成交"""
        while True:
            order = await self.api.get_order(order_id)
            
            if order.status == OrderStatus.FILLED:
                return order
            
            await asyncio.sleep(0.1)  # 100ms 轮询间隔
```

#### 5.1.3 混合执行协调器

```python
class HybridExecutor:
    """混合执行协调器"""
    
    def __init__(
        self,
        maker_executor: ShallowMakerExecutor,
        ioc_executor: IOCExecutor,
        classifier: SignalClassifier
    ):
        self.maker = maker_executor
        self.ioc = ioc_executor
        self.classifier = classifier
    
    async def execute(
        self,
        signal: SignalScore,
        position: Position
    ) -> Optional[Order]:
        """
        根据信号强度选择执行方式
        
        Args:
            signal: 信号评分
            position: 当前仓位
        
        Returns:
            成交订单或 None
        """
        # 1. 信号分级
        confidence = self.classifier.classify(signal.value)
        
        # 2. 计算订单尺寸
        size = calculate_position_size(signal, position.nav)
        side = Side.BUY if signal.value > 0 else Side.SELL
        
        # 3. 根据置信度执行
        if confidence == ConfidenceLevel.HIGH:
            # 高置信度: Maker 尝试，失败转 IOC
            order = await self.maker.place_maker_order(
                side=side,
                size=size,
                timeout=5.0
            )
            
            if order is None:
                # Maker 失败，转 IOC
                logger.info("maker_failed_fallback_ioc", signal_score=signal.value)
                order = await self.ioc.execute(side, size)
            
            return order
        
        elif confidence == ConfidenceLevel.MEDIUM:
            # 中置信度: Maker 尝试，失败跳过
            order = await self.maker.place_maker_order(
                side=side,
                size=size,
                timeout=3.0
            )
            
            if order is None:
                logger.info("maker_failed_skip", signal_score=signal.value)
            
            return order
        
        else:
            # 低置信度: 跳过
            logger.debug("signal_too_weak_skip", signal_score=signal.value)
            return None
```

### 5.2 风控集成

#### 5.2.1 Maker 成交率监控

```python
class MakerFillRateMonitor:
    """Maker 成交率监控"""
    
    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self.attempts: deque[bool] = deque(maxlen=window_size)
    
    def record_attempt(self, filled: bool):
        """记录 Maker 尝试结果"""
        self.attempts.append(filled)
    
    def get_fill_rate(self) -> float:
        """获取当前成交率"""
        if len(self.attempts) == 0:
            return 0.0
        
        return sum(self.attempts) / len(self.attempts)
    
    def is_healthy(self, min_fill_rate: float = 0.75) -> bool:
        """检查成交率是否健康"""
        if len(self.attempts) < 20:  # 样本太少，暂不判断
            return True
        
        fill_rate = self.get_fill_rate()
        
        if fill_rate < min_fill_rate:
            logger.warning(
                "maker_fill_rate_low",
                fill_rate=fill_rate,
                threshold=min_fill_rate,
                samples=len(self.attempts)
            )
            return False
        
        return True
```

#### 5.2.2 成本实时估计

```python
class DynamicCostEstimator:
    """动态成本估计器"""
    
    def __init__(self):
        self.maker_fill_rate_monitor = MakerFillRateMonitor()
    
    def estimate_cost(self, confidence: ConfidenceLevel) -> Decimal:
        """
        估计实际交易成本
        
        Args:
            confidence: 信号置信度
        
        Returns:
            预期往返成本（bps）
        """
        fill_rate = self.maker_fill_rate_monitor.get_fill_rate()
        
        if confidence == ConfidenceLevel.HIGH:
            # 高置信度: Maker 尝试，失败转 IOC
            cost = fill_rate * Decimal("11") + (1 - fill_rate) * Decimal("15")
        elif confidence == ConfidenceLevel.MEDIUM:
            # 中置信度: Maker 尝试，失败跳过（无成本）
            cost = fill_rate * Decimal("11")
        else:
            cost = Decimal("0")
        
        return cost
```

---

## 6. 测试计划

### 6.1 单元测试

**测试模块**:
1. `SignalClassifier` - 阈值校准和分级逻辑
2. `ShallowMakerExecutor` - 订单放置和超时处理
3. `HybridExecutor` - 执行方式选择逻辑

**测试场景**:
```python
def test_signal_classifier():
    """测试信号分级器"""
    classifier = SignalClassifier(theta_1=0.45, theta_2=0.25)
    
    assert classifier.classify(0.5) == ConfidenceLevel.HIGH
    assert classifier.classify(0.3) == ConfidenceLevel.MEDIUM
    assert classifier.classify(0.1) == ConfidenceLevel.LOW

def test_maker_timeout():
    """测试 Maker 超时处理"""
    # Mock API 延迟响应
    # 验证超时后订单被取消
    pass
```

### 6.2 集成测试

**测试场景**:
1. 高置信度信号 → Maker成交 → 验证成本 = 11 bps
2. 高置信度信号 → Maker超时 → IOC成交 → 验证成本 = 15 bps
3. 中置信度信号 → Maker超时 → 跳过 → 验证无交易

### 6.3 Paper Trading

**目标**:
1. 验证 Maker 成交率 ≥ 80%（高置信度）
2. 验证实际成本 ≤ 12 bps
3. 验证端到端延迟 p99 < 150ms

**运行时间**: 7 天

**关键监控指标**:
```
- Maker 成交率（分置信度）
- 实际滑点分布
- 订单提交延迟
- 信号计算延迟
- 价格反转事件（Maker 期间价格反向突破）
```

---

## 7. 部署路线图

### Phase 1: 开发（Day 1-3）

```
Day 1: 核心模块开发
  ├─ SignalClassifier 实现
  ├─ ShallowMakerExecutor 实现
  └─ HybridExecutor 集成

Day 2: 风控模块开发
  ├─ MakerFillRateMonitor 实现
  ├─ DynamicCostEstimator 实现
  └─ 与现有风控系统集成

Day 3: 单元测试 + 集成测试
  ├─ 测试覆盖率 > 80%
  ├─ 所有测试通过
  └─ 代码 Review
```

### Phase 2: Paper Trading（Day 4-10）

```
Day 4-5: Paper Trading 环境搭建
  ├─ 模拟订单簿环境
  ├─ 实时数据接入
  └─ 日志/监控系统

Day 6-10: Paper Trading 运行
  ├─ 24/7 运行
  ├─ 每日监控报告
  └─ 成交率/成本验证
```

### Phase 3: 小资金实盘（Day 11-24）

```
Day 11: 实盘启动
  ├─ 初始资金: $5,000
  ├─ 严格风控: 单笔 < $500
  └─ 实时监控

Day 11-17: Week 1 实盘验证
  ├─ 每日 PnL 分析
  ├─ 成本归因
  └─ 策略调优

Day 18-24: Week 2 放大测试
  ├─ 资金 → $10,000
  ├─ 验证策略容量
  └─ 最终评估
```

---

## 8. 成功标准

### 必达指标（Week 2 结束）

| 指标 | 目标 | 达成条件 |
|------|------|---------|
| **Maker 成交率** | ≥ 80% | 高置信度信号 |
| **实际往返成本** | ≤ 12 bps | 平均值 |
| **Top 20% 净收益** | ≥ +2 bps | 扣除实际成本 |
| **7日夏普比率** | > 1.5 | 风险调整后收益 |
| **最大回撤** | < 8% | 单日/连续3日 |
| **实盘 vs 回测偏差** | < 30% | 收益/成本偏差 |

### 挑战指标（可选）

| 指标 | 目标 | 说明 |
|------|------|------|
| **日均收益** | > 3% | 超额收益目标 |
| **月化收益** | > 60% | 年化 >600% |
| **连续盈利天数** | ≥ 10 | 稳定性验证 |

---

## 9. 风险与缓解

### 主要风险

1. **Maker 成交率不达标**（< 75%）
   - **影响**: 实际成本上升至 13-14 bps，利润空间压缩
   - **缓解**: 
     - 实时监控成交率，< 75% 时调整策略
     - 缩短超时时间（5s → 3s）
     - 提高信号阈值（θ₁: 0.45 → 0.50）

2. **滑点超预期**（> 3 bps）
   - **影响**: 成本上升，侵蚀利润
   - **缓解**:
     - 动态尺寸调整（低流动性时减小）
     - 避开高波动时段
     - 实时滑点估计

3. **信号在实盘中 IC 下降**
   - **影响**: 预期收益下降，无法覆盖成本
   - **缓解**:
     - 持续监控信号 IC
     - IC < 0.30 时触发警报
     - 准备 Plan B（回归 Top 5% 信号）

### 故障恢复

**Maker 执行器故障** → 自动切换至纯 IOC 模式（保证可用性，接受成本上升）

**API 限流/异常** → 硬熔断，停止交易

---

## 10. 关键决策点

### Decision Point 1: Paper Trading 后（Day 10）

**评估问题**:
- Maker 成交率是否 ≥ 80%？
- 实际成本是否 ≤ 12 bps？

**决策**:
```
IF 成交率 ≥ 80% AND 成本 ≤ 12 bps:
    → 进入小资金实盘
ELSE IF 成交率 ≥ 70%:
    → 调整策略（提高阈值/缩短超时）后重新 Paper Trading
ELSE:
    → 放弃 Maker，回归纯 IOC + Top 5% 信号
```

### Decision Point 2: 实盘 Week 1 后（Day 17）

**评估问题**:
- 实际净收益是否 ≥ +2 bps？
- 7日夏普比率是否 > 1.5？

**决策**:
```
IF 净收益 ≥ +2 bps AND 夏普 > 1.5:
    → 放大至 $10K，继续验证
ELSE IF 净收益 > 0:
    → 继续小资金运行，观察 2 周
ELSE:
    → 暂停策略，回归设计阶段
```

---

**设计完成时间**: 2025-10-29  
**下一步**: 开始 Phase 1 开发（核心模块实现）  
**预期完成时间**: 2025-11-19（3 周后）
