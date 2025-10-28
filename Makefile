.PHONY: help setup install install-dev clean lint format typecheck test test-cov test-unit test-integration check pre-commit validate-signals backtest-week1 generate-report

help: ## 显示帮助信息
	@echo "Hyperliquid 高频交易系统 - 可用命令："
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## 完整环境设置（UV + venv + 依赖）
	@echo "🔧 设置开发环境..."
	uv venv --python 3.11
	@echo "✅ 虚拟环境已创建"
	@echo "请运行: source .venv/bin/activate"

install: ## 安装生产依赖
	@echo "📦 安装生产依赖..."
	uv pip install -e .

install-dev: ## 安装开发依赖
	@echo "📦 安装开发依赖..."
	uv pip install -e ".[dev]"

clean: ## 清理缓存和临时文件
	@echo "🧹 清理缓存..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/ .coverage htmlcov/
	@echo "✅ 清理完成"

lint: ## 运行 Ruff 代码检查
	@echo "🔍 运行代码检查..."
	ruff check src/ tests/

format: ## 使用 Black 格式化代码
	@echo "✨ 格式化代码..."
	black src/ tests/
	ruff check --fix src/ tests/

typecheck: ## 运行 Mypy 类型检查
	@echo "🔍 运行类型检查..."
	mypy src/

test: ## 运行所有测试
	@echo "🧪 运行测试..."
	uv run pytest tests/

test-cov: ## 运行测试并生成覆盖率报告
	@echo "🧪 运行测试并生成覆盖率报告..."
	uv run pytest --cov=src --cov-report=html --cov-report=term tests/
	@echo "📊 覆盖率报告已生成: htmlcov/index.html"

test-unit: ## 仅运行单元测试
	@echo "🧪 运行单元测试..."
	uv run pytest tests/unit/ -v

test-integration: ## 仅运行集成测试
	@echo "🧪 运行集成测试..."
	uv run pytest tests/integration/ -v -m integration

check: lint typecheck ## 运行所有质量检查
	@echo "✅ 所有检查通过"

pre-commit: format check test ## 提交前检查（格式化 + 检查 + 测试）
	@echo "✅ 提交前检查完成"

validate-init: ## 组件初始化验证（不需要网络）
	@echo "🔍 运行组件初始化验证..."
	uv run python scripts/validate_initialization.py
	@echo "✅ 初始化验证完成"

validate-system: ## 系统验证（需要网络连接）
	@echo "🔍 运行系统验证..."
	uv run python scripts/validate_system.py
	@echo "✅ 系统验证完成"

validate-signals: ## 信号验证（Week 1）
	@echo "📊 运行信号验证..."
	uv run python scripts/validate_signals.py \
		--data data/raw/btc_30d.parquet \
		--config config/signals.yaml \
		--output docs/signal_validation_report.html
	@echo "✅ 信号验证完成，报告：docs/signal_validation_report.html"

backtest-week1: ## 回测 Week 1 IOC-only 基线
	@echo "📈 运行 Week 1 回测..."
	uv run python scripts/run_week1_baseline.py \
		--data data/raw/btc_30d.parquet \
		--config config/week1_ioc.yaml \
		--output docs/baseline_performance.html
	@echo "✅ 回测完成，报告：docs/baseline_performance.html"

generate-report: ## 生成验证报告
	@echo "📝 生成验证报告..."
	uv run python scripts/generate_validation_report.py \
		--output docs/week1_validation_report.html
	@echo "✅ 报告已生成：docs/week1_validation_report.html"

validate-all: validate-signals backtest-week1 ## 运行所有验证
	@echo "✅ 所有验证完成"
