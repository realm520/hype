# Hyperliquid 高频交易系统

> **纯盈利导向**的 IOC-only 高频交易策略，基于 Hyperliquid 平台

## 项目状态

🚧 **Week 1 开发中** - IOC-only 基线实现

## 快速开始

### 1. 环境设置

```bash
# 创建虚拟环境
make setup
source .venv/bin/activate

# 安装依赖
make install-dev
```

### 2. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，填入你的 API 密钥
vim .env
```

### 3. 运行测试

```bash
# 代码质量检查
make check

# 运行测试
make test
```

## 核心文档

- **[开发指南](CLAUDE.md)** - 完整的开发指南和 API 文档
- **[策略评审](docs/strategy_review.md)** - 策略理论和盈利模型
- **[架构设计](docs/architecture_design.md)** - 系统架构和模块设计

## Week 1 目标

- [ ] 数据层：WebSocket 连接 + 订单簿重建
- [ ] 信号层：OBI + Microprice + Impact 信号
- [ ] 执行层：IOC 执行器 + 滑点估计
- [ ] 风控层：硬熔断（单笔/日回撤/API 异常）
- [ ] 分析层：PnL 归因系统

## 关键指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| **信号 IC** | ≥ 0.03 | Spearman 相关性 |
| **Alpha 占比** | ≥ 70% | 方向性收益主导 |
| **成交成本** | ≤ 25% | Fee + Slip |
| **胜率** | ≥ 60% | 扣除成本后 |
| **端到端延迟** | < 100ms | p99 延迟 |

## 常用命令

```bash
# 开发
make format          # 格式化代码
make lint            # 代码检查
make test            # 运行测试
make pre-commit      # 提交前检查

# 验证（需要历史数据）
make validate-signals      # 信号验证
make backtest-week1        # Week 1 回测
make validate-all          # 全部验证

# 运行
python -m src.main --dry-run    # 干跑测试
python -m src.main              # 正式运行
```

## 项目结构

```
hype/
├── src/              # 核心代码
├── tests/            # 测试代码
├── config/           # 配置文件
├── docs/             # 文档
├── scripts/          # 工具脚本
└── data/             # 数据目录
```

## 安全提示

⚠️ **重要**：
- 不要将 `.env` 文件提交到 Git
- 定期审查交易日志和 PnL 归因
- 遵守 Hyperliquid 平台的 API 限流规则

## License

MIT
