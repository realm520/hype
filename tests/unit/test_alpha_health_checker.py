"""AlphaHealthChecker 单元测试

测试覆盖：
    1. 健康状态分类逻辑
    2. IC 衰减检测
    3. 市场状态适应
    4. 系统响应建议生成
    5. 边界条件和异常处理
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.analytics.alpha_health_checker import (
    AlphaHealthChecker,
    HealthMetrics,
    HealthStatus,
)
from src.analytics.market_state_detector import MarketMetrics, MarketState


@pytest.fixture
def mock_pnl_attribution():
    """Mock PnL 归因分析器"""
    mock = MagicMock()
    mock._attribution_history = []  # 空交易历史
    mock.get_attribution_percentages.return_value = {
        "alpha": 75.0,  # 默认 75% Alpha 占比
        "fee": -15.0,
        "slippage": -8.0,
        "impact": -2.0,
        "rebate": 0.0,
    }
    return mock


@pytest.fixture
def mock_metrics_collector():
    """Mock 指标收集器"""
    mock = MagicMock()
    mock.get_ic_stats.return_value = {
        "ic": 0.05,  # 默认 IC = 0.05（健康）
        "p_value": 0.001,
        "sample_size": 100,
    }
    mock.get_signal_metrics.return_value = {
        "total_signals": 100,
        "avg_signal_strength": 0.45,
        "hit_rate": 0.62,
    }
    return mock


@pytest.fixture
def mock_market_state_detector():
    """Mock 市场状态检测器"""
    mock = MagicMock()
    return mock


@pytest.fixture
def health_checker(
    mock_pnl_attribution, mock_metrics_collector, mock_market_state_detector
):
    """创建测试健康检查器"""
    return AlphaHealthChecker(
        pnl_attribution=mock_pnl_attribution,
        metrics_collector=mock_metrics_collector,
        market_state_detector=mock_market_state_detector,
    )


@pytest.fixture
def normal_market_metrics():
    """正常市场指标"""
    return MarketMetrics(
        volatility=0.01,
        liquidity_score=0.8,
        spread_bps=3.0,
        price_reversals=2,
        detected_state=MarketState.NORMAL,
    )


class TestHealthStatusClassification:
    """测试健康状态分类逻辑"""

    def test_healthy_status(
        self, health_checker, mock_metrics_collector, normal_market_metrics
    ):
        """HEALTHY 状态：IC ≥ 0.03, Alpha ≥ 70%, IC 衰减 < 20%"""
        # 设置健康指标
        mock_metrics_collector.get_ic_stats.return_value = {"ic": 0.05, "p_value": 0.001}

        # 填充 IC 历史（无衰减）
        for i in range(200):
            health_checker._ic_history.append((1000 + i, 0.05))

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=2000,
        )

        assert result.status == HealthStatus.HEALTHY
        assert result.recommend_stop_trading is False
        assert result.recommend_reduce_size is False
        assert result.recommended_size_factor == 1.0

    def test_degrading_status_low_ic(
        self, health_checker, mock_metrics_collector, normal_market_metrics
    ):
        """DEGRADING 状态：IC 在 0.01-0.03 之间"""
        # 设置降级 IC
        mock_metrics_collector.get_ic_stats.return_value = {"ic": 0.02, "p_value": 0.05}

        # 填充 IC 历史
        for i in range(200):
            health_checker._ic_history.append((1000 + i, 0.02))

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=2000,
        )

        assert result.status == HealthStatus.DEGRADING
        assert result.recommend_reduce_size is True
        assert result.recommend_increase_threshold is True
        assert result.recommended_size_factor == 0.5  # 减半
        assert result.recommended_theta_adjustment == 0.1

    def test_degrading_status_low_alpha(
        self, health_checker, mock_pnl_attribution, normal_market_metrics
    ):
        """DEGRADING 状态：Alpha 占比在 50-70% 之间"""
        # 设置降级 Alpha 占比
        mock_pnl_attribution.get_attribution_percentages.return_value = {
            "alpha": 60.0,  # 60%
            "fee": -25.0,
            "slippage": -12.0,
            "impact": -3.0,
            "rebate": 0.0,
        }

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=1000,
        )

        assert result.status == HealthStatus.DEGRADING
        assert result.alpha_percentage == 60.0

    def test_degrading_status_high_vol_market(
        self, health_checker, mock_metrics_collector
    ):
        """DEGRADING 状态：市场状态为 HIGH_VOL"""
        # 正常 IC 和 Alpha，但市场高波动
        high_vol_metrics = MarketMetrics(
            volatility=0.03,  # 高于阈值
            liquidity_score=0.7,
            spread_bps=5.0,
            price_reversals=3,
            detected_state=MarketState.HIGH_VOL,
        )

        mock_metrics_collector.get_ic_stats.return_value = {"ic": 0.05}  # 健康 IC

        result = health_checker.check_health(
            current_market_metrics=high_vol_metrics,
            current_timestamp=1000,
        )

        assert result.status == HealthStatus.DEGRADING
        assert result.market_state == MarketState.HIGH_VOL

    def test_failed_status_very_low_ic(
        self, health_checker, mock_metrics_collector, normal_market_metrics
    ):
        """FAILED 状态：IC < 0.01"""
        mock_metrics_collector.get_ic_stats.return_value = {"ic": 0.005}

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=1000,
        )

        assert result.status == HealthStatus.FAILED
        assert result.recommend_stop_trading is True
        assert result.recommended_size_factor == 0.0

    def test_failed_status_very_low_alpha(
        self, health_checker, mock_pnl_attribution, normal_market_metrics
    ):
        """FAILED 状态：Alpha 占比 < 50%"""
        mock_pnl_attribution.get_attribution_percentages.return_value = {
            "alpha": 40.0,
            "fee": -35.0,
            "slippage": -20.0,
            "impact": -5.0,
            "rebate": 0.0,
        }

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=1000,
        )

        assert result.status == HealthStatus.FAILED
        assert result.alpha_percentage == 40.0

    def test_failed_status_consecutive_losses(
        self, health_checker, normal_market_metrics
    ):
        """FAILED 状态：连续亏损 > 5 笔"""
        # 模拟 6 笔连续亏损
        for _ in range(6):
            health_checker.update_consecutive_losses(is_loss=True)

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=1000,
        )

        assert result.status == HealthStatus.FAILED
        assert result.consecutive_losses == 6


class TestICDecayDetection:
    """测试 IC 衰减检测"""

    def test_no_decay_healthy(self, health_checker, normal_market_metrics):
        """无衰减情况（健康）"""
        # 填充 IC 历史：稳定在 0.05
        for i in range(500):
            health_checker._ic_history.append((1000 + i, 0.05))

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=2000,
        )

        assert result.ic_decay_rate < 1.0  # 几乎无衰减
        assert result.status == HealthStatus.HEALTHY

    def test_moderate_decay_degrading(self, health_checker, normal_market_metrics):
        """中等衰减（降级）"""
        # 填充 IC 历史：从 0.05 降至 0.03
        for i in range(400):
            health_checker._ic_history.append((1000 + i, 0.05))  # 长期 IC
        for i in range(100):
            health_checker._ic_history.append((1400 + i, 0.03))  # 短期 IC 下降

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=2000,
        )

        # 衰减率 = (0.05 - 0.03) / 0.05 * 100 = 40%
        assert 30.0 < result.ic_decay_rate < 50.0
        assert result.status == HealthStatus.DEGRADING

    def test_severe_decay_failed(self, health_checker, normal_market_metrics):
        """严重衰减（失败）"""
        # 填充 IC 历史：从 0.05 降至 0.01
        for i in range(400):
            health_checker._ic_history.append((1000 + i, 0.05))
        for i in range(100):
            health_checker._ic_history.append((1400 + i, 0.01))  # 严重下降

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=2000,
        )

        # 衰减率 = (0.05 - 0.01) / 0.05 * 100 = 80%
        assert result.ic_decay_rate > 50.0
        assert result.status == HealthStatus.FAILED

    def test_ic_improvement_not_reported_as_decay(
        self, health_checker, normal_market_metrics
    ):
        """IC 改善不报告为衰减"""
        # 填充 IC 历史：从 0.03 提升至 0.05
        for i in range(400):
            health_checker._ic_history.append((1000 + i, 0.03))
        for i in range(100):
            health_checker._ic_history.append((1400 + i, 0.05))  # 改善

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=2000,
        )

        # 只报告衰减（正值），改善归零
        assert result.ic_decay_rate == 0.0
        assert result.status == HealthStatus.HEALTHY


class TestMarketStateAdaptation:
    """测试市场状态适应"""

    def test_low_liq_duration_triggers_failed(self, health_checker):
        """持续低流动性触发 FAILED 状态"""
        low_liq_metrics = MarketMetrics(
            volatility=0.01,
            liquidity_score=0.2,
            spread_bps=20.0,
            price_reversals=2,
            detected_state=MarketState.LOW_LIQ,
        )

        # 第一次检查（开始低流动性）
        result1 = health_checker.check_health(
            current_market_metrics=low_liq_metrics,
            current_timestamp=1000,
        )
        assert health_checker._low_liq_start_time == 1000

        # 第二次检查（持续 2000 秒 > 阈值 1800 秒）
        result2 = health_checker.check_health(
            current_market_metrics=low_liq_metrics,
            current_timestamp=3000,
        )

        assert result2.status == HealthStatus.FAILED
        assert result2.recommend_stop_trading is True

    def test_low_liq_recovery_resets_timer(self, health_checker, normal_market_metrics):
        """低流动性恢复重置计时器"""
        low_liq_metrics = MarketMetrics(
            volatility=0.01,
            liquidity_score=0.2,
            spread_bps=20.0,
            price_reversals=2,
            detected_state=MarketState.LOW_LIQ,
        )

        # 开始低流动性
        health_checker.check_health(
            current_market_metrics=low_liq_metrics,
            current_timestamp=1000,
        )
        assert health_checker._low_liq_start_time == 1000

        # 恢复正常
        health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=1500,
        )
        assert health_checker._low_liq_start_time is None

    def test_high_vol_increases_theta_adjustment(self, health_checker):
        """HIGH_VOL 状态增加阈值调整建议"""
        # IC 在降级范围（触发 DEGRADING）
        health_checker.metrics_collector.get_ic_stats.return_value = {"ic": 0.02}

        high_vol_metrics = MarketMetrics(
            volatility=0.03,
            liquidity_score=0.7,
            spread_bps=5.0,
            price_reversals=3,
            detected_state=MarketState.HIGH_VOL,
        )

        result = health_checker.check_health(
            current_market_metrics=high_vol_metrics,
            current_timestamp=1000,
        )

        assert result.status == HealthStatus.DEGRADING
        assert result.recommended_theta_adjustment == 0.1  # 基础调整


class TestRecommendationGeneration:
    """测试系统响应建议生成"""

    def test_healthy_no_recommendations(
        self, health_checker, mock_metrics_collector, normal_market_metrics
    ):
        """HEALTHY 状态无建议"""
        mock_metrics_collector.get_ic_stats.return_value = {"ic": 0.05}

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=1000,
        )

        assert result.recommend_stop_trading is False
        assert result.recommend_reduce_size is False
        assert result.recommend_increase_threshold is False
        assert result.recommended_size_factor == 1.0
        assert result.recommended_theta_adjustment == 0.0

    def test_degrading_recommendations(
        self, health_checker, mock_metrics_collector, normal_market_metrics
    ):
        """DEGRADING 状态建议减小尺寸、提高阈值"""
        mock_metrics_collector.get_ic_stats.return_value = {"ic": 0.02}  # 降级 IC

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=1000,
        )

        assert result.status == HealthStatus.DEGRADING
        assert result.recommend_reduce_size is True
        assert result.recommend_increase_threshold is True
        assert result.recommended_size_factor == 0.5
        assert result.recommended_theta_adjustment == 0.1

    def test_degrading_severe_decay_reduces_size_more(
        self, health_checker, mock_metrics_collector, normal_market_metrics
    ):
        """严重衰减（> 30%，但 < 50%）进一步减小尺寸"""
        # 设置 IC 在 DEGRADING 范围内
        mock_metrics_collector.get_ic_stats.return_value = {"ic": 0.025}

        # 填充 IC 历史：中等衰减（约 35%）
        for i in range(400):
            health_checker._ic_history.append((1000 + i, 0.04))  # 长期 IC
        for i in range(100):
            health_checker._ic_history.append((1400 + i, 0.026))  # 短期 IC 下降

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=2000,
        )

        # 衰减 35% > 30%，状态为 DEGRADING，尺寸系数 = 0.3
        assert result.status == HealthStatus.DEGRADING
        assert 30.0 < result.ic_decay_rate < 50.0  # 在 30-50% 范围
        assert result.recommended_size_factor == 0.3

    def test_failed_recommendations_stop_trading(
        self, health_checker, mock_metrics_collector, normal_market_metrics
    ):
        """FAILED 状态建议停止交易"""
        mock_metrics_collector.get_ic_stats.return_value = {"ic": 0.005}  # 失败 IC

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=1000,
        )

        assert result.status == HealthStatus.FAILED
        assert result.recommend_stop_trading is True
        assert result.recommend_reduce_size is True
        assert result.recommended_size_factor == 0.0
        assert result.recommended_theta_adjustment == 0.2  # 大幅提高


class TestConsecutiveLossesTracking:
    """测试连续亏损追踪"""

    def test_update_consecutive_losses_increase(self, health_checker):
        """连续亏损计数递增"""
        health_checker.update_consecutive_losses(is_loss=True)
        assert health_checker._consecutive_losses == 1

        health_checker.update_consecutive_losses(is_loss=True)
        assert health_checker._consecutive_losses == 2

        health_checker.update_consecutive_losses(is_loss=True)
        assert health_checker._consecutive_losses == 3

    def test_update_consecutive_losses_reset_on_win(self, health_checker):
        """盈利时重置连续亏损"""
        health_checker.update_consecutive_losses(is_loss=True)
        health_checker.update_consecutive_losses(is_loss=True)
        assert health_checker._consecutive_losses == 2

        health_checker.update_consecutive_losses(is_loss=False)
        assert health_checker._consecutive_losses == 0

    def test_consecutive_losses_triggers_degrading(
        self, health_checker, normal_market_metrics
    ):
        """连续亏损 3-5 笔触发 DEGRADING"""
        # 模拟 4 笔连续亏损
        for _ in range(4):
            health_checker.update_consecutive_losses(is_loss=True)

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=1000,
        )

        assert result.status == HealthStatus.DEGRADING
        assert result.consecutive_losses == 4


class TestUtilityMethods:
    """测试工具方法"""

    def test_get_ic_history(self, health_checker):
        """测试获取 IC 历史"""
        # 添加 IC 历史
        for i in range(100):
            health_checker._ic_history.append((1000 + i, 0.05 - i * 0.0001))

        # 获取全部历史
        full_history = health_checker.get_ic_history()
        assert len(full_history) == 100

        # 获取窗口历史
        window_history = health_checker.get_ic_history(window=10)
        assert len(window_history) == 10
        assert window_history[-1][1] == pytest.approx(0.0401, abs=1e-4)

    def test_get_market_state_distribution(self, health_checker, normal_market_metrics):
        """测试获取市场状态分布"""
        # 添加市场状态历史
        for _ in range(10):
            health_checker.check_health(
                current_market_metrics=normal_market_metrics,
                current_timestamp=1000,
            )

        high_vol_metrics = MarketMetrics(
            volatility=0.03,
            liquidity_score=0.7,
            spread_bps=5.0,
            price_reversals=3,
            detected_state=MarketState.HIGH_VOL,
        )
        for _ in range(5):
            health_checker.check_health(
                current_market_metrics=high_vol_metrics,
                current_timestamp=2000,
            )

        distribution = health_checker.get_market_state_distribution()

        assert distribution[MarketState.NORMAL] == 10
        assert distribution[MarketState.HIGH_VOL] == 5
        assert distribution[MarketState.LOW_LIQ] == 0
        assert distribution[MarketState.CHOPPY] == 0

    def test_reset(self, health_checker):
        """测试重置健康检查器"""
        # 添加一些历史数据
        health_checker._ic_history.append((1000, 0.05))
        health_checker._market_state_history.append((1000, MarketState.NORMAL))
        health_checker._consecutive_losses = 3
        health_checker._low_liq_start_time = 1000

        # 重置
        health_checker.reset()

        assert len(health_checker._ic_history) == 0
        assert len(health_checker._market_state_history) == 0
        assert health_checker._consecutive_losses == 0
        assert health_checker._low_liq_start_time is None


class TestEdgeCases:
    """测试边界条件"""

    def test_insufficient_samples_returns_zero_decay(
        self, health_checker, normal_market_metrics
    ):
        """样本不足时 IC 衰减率为 0"""
        # 仅添加 5 个样本（< min_samples = 10）
        for i in range(5):
            health_checker._ic_history.append((1000 + i, 0.05))

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=2000,
        )

        assert result.ic_decay_rate == 0.0

    def test_zero_baseline_ic_handles_gracefully(
        self, health_checker, mock_metrics_collector, normal_market_metrics
    ):
        """基准 IC 为 0 时优雅处理"""
        # 填充 IC 历史：全部为 0
        for i in range(500):
            health_checker._ic_history.append((1000 + i, 0.0))

        mock_metrics_collector.get_ic_stats.return_value = {"ic": 0.0}

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=2000,
        )

        # 不应抛出除零异常
        assert result.ic_decay_rate == 0.0
        assert isinstance(result, HealthMetrics)

    def test_negative_alpha_percentage_uses_absolute_value(
        self, health_checker, mock_pnl_attribution, normal_market_metrics
    ):
        """负 Alpha 占比使用绝对值"""
        # 亏损时 Alpha 可能为负
        mock_pnl_attribution.get_attribution_percentages.return_value = {
            "alpha": -60.0,  # 负值
            "fee": 25.0,
            "slippage": 12.0,
            "impact": 3.0,
            "rebate": 0.0,
        }

        result = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=1000,
        )

        # 使用绝对值
        assert result.alpha_percentage == 60.0
        assert result.status == HealthStatus.DEGRADING


class TestIntegration:
    """集成测试"""

    def test_full_workflow_healthy_to_degrading(
        self, health_checker, mock_metrics_collector, normal_market_metrics
    ):
        """完整工作流：从 HEALTHY 降级至 DEGRADING"""
        # 初始健康状态
        mock_metrics_collector.get_ic_stats.return_value = {"ic": 0.05}

        for i in range(100):
            health_checker._ic_history.append((1000 + i, 0.05))

        result1 = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=2000,
        )
        assert result1.status == HealthStatus.HEALTHY

        # IC 开始衰减
        mock_metrics_collector.get_ic_stats.return_value = {"ic": 0.02}

        for i in range(100):
            health_checker._ic_history.append((2000 + i, 0.02))

        result2 = health_checker.check_health(
            current_market_metrics=normal_market_metrics,
            current_timestamp=3000,
        )
        assert result2.status == HealthStatus.DEGRADING

    def test_repr_output(self, health_checker):
        """验证 __repr__ 输出"""
        repr_str = repr(health_checker)
        assert "AlphaHealthChecker" in repr_str
        assert "healthy_ic=0.030" in repr_str
        assert "degrading_ic=0.010" in repr_str
        assert "healthy_alpha=70.0%" in repr_str
