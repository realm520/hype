#!/bin/bash
# Week 1 测试运行脚本

set -e  # 遇到错误立即退出

echo "=========================================="
echo "  Week 1 IOC 交易系统测试套件"
echo "=========================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 检查环境
echo "🔍 检查测试环境..."
if [ ! -d ".venv" ]; then
    echo -e "${RED}❌ 虚拟环境不存在，请先运行: make setup${NC}"
    exit 1
fi

if ! command -v uv &> /dev/null; then
    echo -e "${RED}❌ uv 未安装，请安装 uv: curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
    exit 1
fi

echo -e "${GREEN}✅ 测试环境就绪${NC}"
echo ""

# 运行测试的函数
run_test_suite() {
    local name=$1
    local command=$2

    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  $name${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    if eval $command; then
        echo ""
        echo -e "${GREEN}✅ $name 通过${NC}"
        return 0
    else
        echo ""
        echo -e "${RED}❌ $name 失败${NC}"
        return 1
    fi
    echo ""
}

# 解析参数
QUICK=false
COVERAGE=false
VERBOSE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --quick)
            QUICK=true
            shift
            ;;
        --coverage)
            COVERAGE=true
            shift
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        *)
            echo "未知选项: $1"
            echo "用法: $0 [--quick] [--coverage] [--verbose]"
            exit 1
            ;;
    esac
done

# 设置 pytest 参数
PYTEST_ARGS="-v"
if [ "$VERBOSE" = true ]; then
    PYTEST_ARGS="-vv -s"
fi

# 开始测试
echo "⏱️  测试开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 统计
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

if [ "$QUICK" = true ]; then
    echo "🚀 快速测试模式（仅单元测试）"
    echo ""

    if run_test_suite "单元测试 - 信号层" "uv run pytest tests/unit/test_signals.py $PYTEST_ARGS"; then
        ((PASSED_TESTS++))
    else
        ((FAILED_TESTS++))
    fi
    ((TOTAL_TESTS++))

    if run_test_suite "单元测试 - 风控层" "uv run pytest tests/unit/test_risk.py $PYTEST_ARGS"; then
        ((PASSED_TESTS++))
    else
        ((FAILED_TESTS++))
    fi
    ((TOTAL_TESTS++))

    if run_test_suite "单元测试 - 分析层" "uv run pytest tests/unit/test_analytics.py $PYTEST_ARGS"; then
        ((PASSED_TESTS++))
    else
        ((FAILED_TESTS++))
    fi
    ((TOTAL_TESTS++))
else
    echo "🔬 完整测试模式"
    echo ""

    # 单元测试
    if run_test_suite "单元测试 - 信号层" "uv run pytest tests/unit/test_signals.py $PYTEST_ARGS"; then
        ((PASSED_TESTS++))
    else
        ((FAILED_TESTS++))
    fi
    ((TOTAL_TESTS++))

    if run_test_suite "单元测试 - 风控层" "uv run pytest tests/unit/test_risk.py $PYTEST_ARGS"; then
        ((PASSED_TESTS++))
    else
        ((FAILED_TESTS++))
    fi
    ((TOTAL_TESTS++))

    if run_test_suite "单元测试 - 分析层" "uv run pytest tests/unit/test_analytics.py $PYTEST_ARGS"; then
        ((PASSED_TESTS++))
    else
        ((FAILED_TESTS++))
    fi
    ((TOTAL_TESTS++))

    # 集成测试
    if run_test_suite "集成测试 - 交易流程" "uv run pytest tests/integration/test_trading_flow.py $PYTEST_ARGS"; then
        ((PASSED_TESTS++))
    else
        ((FAILED_TESTS++))
    fi
    ((TOTAL_TESTS++))
fi

# 覆盖率测试（可选）
if [ "$COVERAGE" = true ]; then
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  测试覆盖率分析${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    uv run pytest --cov=src --cov-report=term-missing --cov-report=html tests/

    echo ""
    echo -e "${GREEN}📊 覆盖率报告已生成: htmlcov/index.html${NC}"
    echo ""
fi

# 测试总结
echo ""
echo "=========================================="
echo "  测试总结"
echo "=========================================="
echo ""
echo "⏱️  测试结束时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
echo "📊 测试统计:"
echo "   总计: $TOTAL_TESTS 个测试套件"
echo -e "   ${GREEN}通过: $PASSED_TESTS${NC}"
echo -e "   ${RED}失败: $FAILED_TESTS${NC}"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}✅ 所有测试通过！${NC}"
    echo ""
    echo "🎉 Week 1 测试验证完成，系统就绪！"
    echo ""
    exit 0
else
    echo -e "${RED}❌ 有 $FAILED_TESTS 个测试套件失败${NC}"
    echo ""
    echo "💡 建议："
    echo "   1. 查看测试输出中的错误信息"
    echo "   2. 使用 --verbose 参数查看详细日志"
    echo "   3. 单独运行失败的测试进行调试"
    echo ""
    exit 1
fi
