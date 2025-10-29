

# 数据采集与回放系统使用指南

## 概述

本系统提供数据采集和回放功能，允许你：
1. 一次采集真实市场数据
2. 多次快速回放用于测试
3. 避免重复等待真实时间

### 时间效率对比

| 场景 | 实时运行 | 回放运行 (100x) | 节省时间 |
|------|----------|-----------------|----------|
| 10 分钟测试 | 10 分钟 | 6 秒 | 99% |
| 1 小时测试 | 1 小时 | 36 秒 | 99% |
| 24 小时测试 | 24 小时 | 14.4 分钟 | 99% |

---

## 快速开始

### Step 1: 采集 10 分钟测试数据

```bash
# 采集 10 分钟 BTC + ETH 数据（支持增量保存）
python scripts/collect_market_data.py \
    --symbols BTC ETH \
    --duration 600 \
    --output data/market_data/test_10min

# 输出文件：
# - data/market_data/test_10min_l2.parquet      (L2 订单簿快照)
# - data/market_data/test_10min_trades.parquet  (成交数据)
# - data/market_data/test_10min_metadata.json   (元数据)
```

**增量保存特性**：
- 每 1000 条记录 OR 每 60 秒自动保存一次
- 防止内存溢出和数据丢失
- 支持 Ctrl+C 中断后数据恢复

**预计文件大小**：2-5 MB（压缩后）


### Step 2: 使用回放数据测试

#### 方式 1：通过配置文件

编辑 `config/shadow_test.yaml`：

```yaml
# 数据源配置
data_source:
  mode: "replay"  # "live" | "replay"
  replay_path: "data/market_data/test_10min"
  replay_speed: 100.0  # 100倍加速
```

运行测试：

```bash
python scripts/run_shadow_trading.py --config config/shadow_test.yaml
```

#### 方式 2：通过命令行参数

```bash
python scripts/run_shadow_trading.py \
    --config config/shadow_test.yaml \
    --replay-data data/market_data/test_10min \
    --replay-speed 100
```

### Step 3: 查看结果

```bash
# 分析回测结果
python scripts/analyze_shadow_results.py --data-dir data/shadow_test

# 生成报告
python scripts/generate_report.py --input data/shadow_test --output docs/test_report.html
```

---

## 详细用法

### 数据采集器（collect_market_data.py）

#### 基本用法

```bash
python scripts/collect_market_data.py [OPTIONS]
```

#### 选项说明

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--symbols` | list[str] | BTC ETH | 交易对列表 |
| `--duration` | int | 600 | 采集时长（秒） |
| `--output` | str | data/market_data/test.parquet | 输出文件路径（不含后缀） |

#### 示例

```bash
# 采集 1 小时 BTC 数据
python scripts/collect_market_data.py \
    --symbols BTC \
    --duration 3600 \
    --output data/market_data/btc_1hour

# 采集 24 小时多币种数据
python scripts/collect_market_data.py \
    --symbols BTC ETH SOL \
    --duration 86400 \
    --output data/market_data/multi_24hour
```

#### 输出文件

1. **L2 订单簿快照** (`*_l2.parquet`)
   ```python
   {
       "timestamp": int,      # 毫秒时间戳
       "symbol": str,         # BTC, ETH
       "mid_price": float,    # 中间价
       "bids": [              # 买盘（前10档）
           {"price": float, "size": float},
           ...
       ],
       "asks": [              # 卖盘（前10档）
           {"price": float, "size": float},
           ...
       ]
   }
   ```

2. **成交数据** (`*_trades.parquet`)
   ```python
   {
       "timestamp": int,
       "symbol": str,
       "side": str,           # BUY, SELL
       "price": float,
       "size": float
   }
   ```

3. **元数据** (`*_metadata.json`)
   ```json
   {
       "symbols": ["BTC", "ETH"],
       "duration_seconds": 600,
       "actual_duration_seconds": 600.1,
       "start_timestamp": 1761661200000,
       "end_timestamp": 1761661800000,
       "stats": {
           "BTC": {"l2_updates": 5234, "trades": 823},
           "ETH": {"l2_updates": 4981, "trades": 691}
       },
       "total_l2_snapshots": 10215,
       "total_trades": 1514,
       "saver_stats": {
           "total_l2_saved": 10215,
           "total_trades_saved": 1514,
           "save_count": 11
       }
   }
   ```

### 数据回放引擎（DataReplayEngine）

#### Python API 使用

```python
from src.core.data_replay import DataReplayEngine

# 创建回放引擎
engine = DataReplayEngine(
    data_dir="data/market_data/test_10min",
    replay_speed=100.0  # 100倍加速
)

# 加载数据
engine.load_data()

# 开始回放
engine.start_replay()

# 主循环
while not engine.is_finished():
    # 更新状态
    new_data = engine.update()

    # 处理新数据
    for market_data in new_data:
        print(f"Symbol: {market_data.symbol}, Price: {market_data.mid_price}")

    # 获取进度
    progress = engine.get_progress()
    print(f"Progress: {progress * 100:.1f}%")

    await asyncio.sleep(0.01)  # 10ms 采样间隔
```

#### 统一数据接口（DataSource）

```python
from src.core.data_source import create_data_source

# 创建实时数据源
live_source = create_data_source(mode="live")

# 创建回放数据源
replay_source = create_data_source(
    mode="replay",
    replay_path="data/market_data/test_10min",
    replay_speed=100.0
)

# 使用方式完全相同
await live_source.connect()
await live_source.subscribe(["BTC", "ETH"])

market_data = live_source.get_market_data("BTC")
```

---

## 工作流程示例

### 场景 1：快速验证信号逻辑

```bash
# 1. 采集 10 分钟数据（一次性，10 分钟）
python scripts/collect_market_data.py --duration 600 --output data/market_data/quick_test

# 2. 调整信号参数
vim config/signals.yaml
# theta_1: 0.5 → 0.3

# 3. 快速测试（6 秒）
python scripts/run_shadow_trading.py \
    --config config/shadow_test.yaml \
    --replay-data data/market_data/quick_test \
    --replay-speed 100

# 4. 查看结果
python scripts/analyze_shadow_results.py

# 5. 再次调整参数，重复步骤 3-4（无需重新采集）
```

**总耗时**：首次 10 分钟 + 后续每次 6 秒

### 场景 2：参数网格搜索

```bash
# 采集 1 小时数据（一次性）
python scripts/collect_market_data.py --duration 3600 --output data/market_data/param_tuning

# 测试多组参数（自动化）
for theta1 in 0.3 0.5 0.7; do
    for theta2 in 0.1 0.2 0.3; do
        echo "Testing theta1=$theta1, theta2=$theta2"

        # 修改配置
        cat > config/test_params.yaml <<EOF
signals:
  thresholds:
    theta_1: $theta1
    theta_2: $theta2
EOF

        # 运行回测（36 秒）
        python scripts/run_shadow_trading.py \
            --config config/test_params.yaml \
            --replay-data data/market_data/param_tuning \
            --output-dir "results/theta1_${theta1}_theta2_${theta2}"
    done
done

# 对比所有结果
python scripts/compare_results.py results/
```

**总耗时**：1 小时采集 + 9 组参数 × 36 秒 = 1 小时 5.4 分钟

如果不用回放：9 组参数 × 1 小时 = 9 小时！

### 场景 3：极端行情回测

```bash
# 采集高波动时段数据（人工选择时间窗口）
# 例如：2025-01-15 20:00 - 21:00（美联储议息）
python scripts/collect_market_data.py \
    --duration 3600 \
    --output data/market_data/fomc_volatile

# 使用极端行情数据测试风控
python scripts/run_shadow_trading.py \
    --config config/stress_test.yaml \
    --replay-data data/market_data/fomc_volatile \
    --replay-speed 10  # 降低加速，仔细观察
```

---

## 数据管理

### 推荐的数据组织结构

```
data/market_data/
├── quick_test_10min_l2.parquet       # 快速测试（10分钟）
├── quick_test_10min_trades.parquet
├── quick_test_10min_metadata.json
├── normal_1hour_l2.parquet           # 常规测试（1小时）
├── normal_1hour_trades.parquet
├── normal_1hour_metadata.json
├── full_24hour_l2.parquet            # 完整测试（24小时）
├── full_24hour_trades.parquet
├── full_24hour_metadata.json
├── volatile_fomc_l2.parquet          # 极端行情
├── volatile_fomc_trades.parquet
└── volatile_fomc_metadata.json
```

### 存储空间估算

| 时长 | L2 快照 | Trades | 总计 |
|------|---------|--------|------|
| 10 分钟 | 2-3 MB | 0.5-1 MB | 3-4 MB |
| 1 小时 | 15-20 MB | 3-5 MB | 20-25 MB |
| 24 小时 | 400-500 MB | 70-100 MB | 500-600 MB |

### 数据清理

```bash
# 删除旧数据（保留最近 7 天）
find data/market_data/ -name "*.parquet" -mtime +7 -delete
find data/market_data/ -name "*.json" -mtime +7 -delete
```

---

## 故障排查

### 问题 1：程序完成后无法退出（已修复）

**症状**：
```
collection_complete
进程无法退出，Ctrl+C 也无效
```

**原因**：hyperliquid-python-sdk 创建了非 daemon 线程

**解决**：已在代码中使用 `os._exit(0)` 强制退出（正常行为）

### 问题 2：采集数据为空

**症状**：
```
WARNING: no_data_collected
```

**原因**：WebSocket 连接失败或未收到数据

**解决**：
1. 检查网络连接
2. 验证 Hyperliquid API 状态
3. 检查防火墙设置

```bash
# 测试连接
python scripts/test_hyperliquid_connection.py --duration 30
```

### 问题 2：回放速度过快导致遗漏数据

**症状**：信号计算结果与实时不一致

**原因**：回放速度过高（>1000x），CPU 处理不过来

**解决**：降低回放速度

```bash
# 降低到 100x
python scripts/run_shadow_trading.py \
    --replay-data data/market_data/test \
    --replay-speed 100
```

### 问题 3：中断后数据丢失

**症状**：Ctrl+C 中断后部分数据未保存

**原因**：未启用增量保存

**解决**：现已默认启用增量保存（每 1000 条 OR 60 秒）

### 问题 4：内存溢出（已优化）

**症状**：
```
MemoryError: Unable to allocate array
```

**原因**：数据文件过大（>2GB）或未启用增量保存

**解决**：
1. **已启用增量保存**（防止内存溢出）
2. 如需处理超大文件，使用分块加载：

```python
# 修改 data_replay.py
# 启用分块加载（lazy evaluation）
self.l2_df = pl.scan_parquet(l2_path)  # 懒加载
```

---

## 高级用法

### 1. 数据质量检查

```python
# 检查数据质量
from scripts.check_data_quality import check_data_quality

report = check_data_quality("data/market_data/test_10min")
print(report)

# 输出：
# {
#     "missing_timestamps": [],
#     "max_gap_ms": 102,  # 最大数据间隔
#     "avg_gap_ms": 98,   # 平均数据间隔
#     "anomalies": []     # 异常值
# }
```

### 2. 数据可视化

```bash
# 绘制价格曲线
python scripts/plot_market_data.py \
    --input data/market_data/test_10min \
    --output docs/price_chart.png
```

### 3. 数据合并

```bash
# 合并多个时段的数据
python scripts/merge_market_data.py \
    --inputs data/market_data/morning.parquet data/market_data/afternoon.parquet \
    --output data/market_data/full_day.parquet
```

---

## 性能优化建议

### 1. 采集阶段

- **使用 SSD**：提升写入速度
- **增量保存**：已默认启用（每 1000 条记录 OR 60 秒）
  - 防止内存溢出
  - 支持中断恢复
  - 可通过参数调整触发条件
- **压缩配置**：使用 zstd（高压缩比，平衡速度）

### 2. 回放阶段

- **合理设置速度**：
  - 快速验证：100-1000x
  - 详细调试：1-10x
  - 压力测试：10-50x

- **批量处理**：一次回放测试多组参数

---

## 总结

### 优势

1. **时间效率**：99% 时间节省
2. **可重复性**：相同数据多次测试
3. **快速迭代**：参数调整后秒级验证
4. **极端场景**：捕获特殊市场状态

### 最佳实践

1. **分级采集**：
   - 快速验证：10 分钟
   - 初步验证：1 小时
   - 完整验证：24 小时

2. **数据管理**：
   - 标注数据特征（时段、波动性）
   - 定期清理旧数据
   - 备份重要数据集

3. **测试流程**：
   - 先用 10 分钟数据快速迭代
   - 参数稳定后用 1 小时数据验证
   - 最终用 24 小时数据确认

---

## 后续增强计划

1. **数据标注**：自动识别高波动、低流动性时段
2. **数据增强**：生成模拟数据补充极端场景
3. **并行回放**：支持多进程并行测试不同参数
4. **实时对比**：同时运行实时和回放，验证一致性
