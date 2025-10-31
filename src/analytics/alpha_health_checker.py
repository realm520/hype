"""Alpha 健康检查器

Week 2 Phase 3 - Day 4-5

实时监控信号质量和 Alpha 衰减，提供系统响应建议：
    - HEALTHY: IC ≥ 0.03, Alpha 占比 ≥ 70%, IC 衰减 < 20%
    - DEGRADING: IC 0.01-0.03 或 Alpha 占比 50-70%, IC 衰减 20-50%
    - FAILED: IC < 0.01 或 Alpha 占比 < 50%, IC 衰减 > 50%

设计原则：
    - 集成现有分析模块（PnLAttribution, MetricsCollector, MarketStateDetector）
    - 提供分层健康状态分类和系统响应建议
    - 支持实时监控和历史趋势分析
    - 考虑市场状态对健康评估的影响
"""

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

import structlog

from src.analytics.market_state_detector import MarketState

if TYPE_CHECKING:
    from src.analytics.market_state_detector import MarketMetrics, MarketStateDetector
    from src.analytics.metrics import MetricsCollector
    from src.analytics.pnl_attribution import PnLAttribution

logger = structlog.get_logger(__name__)


class HealthStatus(Enum):
    """健康状态枚举"""

    HEALTHY = "healthy"  # IC ≥ 0.03, Alpha ≥ 70%, IC衰减 < 20%
    DEGRADING = "degrading"  # IC 0.01-0.03 或 Alpha 50-70%, IC衰减 20-50%
    FAILED = "failed"  # IC < 0.01 或 Alpha < 50%, IC衰减 > 50%


@dataclass
class HealthMetrics:
    """健康度量指标"""

    status: HealthStatus  # 健康状态
    ic: float  # 当前 IC（信息系数）
    alpha_percentage: float  # Alpha 占比（%）
    ic_decay_rate: float  # IC 衰减率（%）
    market_state: MarketState  # 当前市场状态
    signal_count: int  # 信号总数
    trade_count: int  # 交易总数
    avg_signal_strength: float  # 平均信号强度
    consecutive_losses: int  # 连续亏损次数
    timestamp: int  # 时间戳

    # 系统建议
    recommend_stop_trading: bool  # 是否建议停止交易
    recommend_reduce_size: bool  # 是否建议减小尺寸
    recommend_increase_threshold: bool  # 是否建议提高阈值
    recommended_size_factor: float  # 建议尺寸系数（0.5 = 减半）
    recommended_theta_adjustment: float  # 建议阈值调整（+0.1 = 提高）

    def __repr__(self) -> str:
        return (
            f"HealthMetrics({self.status.value}, "
            f"IC={self.ic:.4f}, "
            f"Alpha={self.alpha_percentage:.1f}%, "
            f"Decay={self.ic_decay_rate:.1f}%, "
            f"State={self.market_state.value})"
        )


class AlphaHealthChecker:
    """Alpha 健康检查器

    监控信号质量和 Alpha 衰减，提供实时健康评估和系统响应建议。

    健康状态分类：
        1. HEALTHY（健康）：
           - IC ≥ 0.03（显著）
           - Alpha 占比 ≥ 70%
           - IC 衰减 < 20%
           - 市场状态 NORMAL 或 CHOPPY

        2. DEGRADING（降级）：
           - IC 0.01-0.03 OR Alpha 占比 50-70%
           - IC 衰减 20-50% OR 连续亏损 3-5 笔
           - 市场状态 HIGH_VOL 或 LOW_LIQ

        3. FAILED（失败）：
           - IC < 0.01 OR Alpha 占比 < 50%
           - IC 衰减 > 50% OR 连续亏损 > 5 笔
           - 持续 LOW_LIQ 状态 > 30 分钟

    系统响应建议：
        - HEALTHY → 继续交易（无限制）
        - DEGRADING → 减小尺寸 50%、提高阈值 +0.1
        - FAILED → 停止交易、告警通知

    性能指标：
        - 更新延迟：< 50ms（每 10 秒更新）
        - 内存占用：< 50MB（包含历史数据）
        - IC 计算：最小 10 样本
        - 支持多窗口：1h/4h/24h
    """

    def __init__(
        self,
        pnl_attribution: "PnLAttribution",
        metrics_collector: "MetricsCollector",
        market_state_detector: "MarketStateDetector",
        # 健康阈值
        healthy_ic_threshold: float = 0.03,  # 健康 IC 阈值
        degrading_ic_threshold: float = 0.01,  # 降级 IC 阈值
        healthy_alpha_threshold: float = 70.0,  # 健康 Alpha 占比（%）
        degrading_alpha_threshold: float = 50.0,  # 降级 Alpha 占比（%）
        healthy_decay_threshold: float = 20.0,  # 健康 IC 衰减阈值（%）
        degrading_decay_threshold: float = 50.0,  # 降级 IC 衰减阈值（%）
        # IC 计算窗口
        ic_window_short: int = 100,  # 短期 IC 窗口（最近 1 小时）
        ic_window_long: int = 500,  # 长期 IC 窗口（过去 24 小时）
        min_samples: int = 10,  # 最小样本数
        # 连续亏损检测
        max_consecutive_losses_degrading: int = 3,  # 降级连续亏损阈值
        max_consecutive_losses_failed: int = 5,  # 失败连续亏损阈值
        # 市场状态影响
        low_liq_duration_threshold: int = 1800,  # 低流动性持续时间阈值（秒）
        max_history: int = 10000,  # 最大历史记录数
    ):
        """
        初始化 Alpha 健康检查器

        Args:
            pnl_attribution: PnL 归因分析器
            metrics_collector: 指标收集器
            market_state_detector: 市场状态检测器
            healthy_ic_threshold: 健康 IC 阈值
            degrading_ic_threshold: 降级 IC 阈值
            healthy_alpha_threshold: 健康 Alpha 占比阈值（%）
            degrading_alpha_threshold: 降级 Alpha 占比阈值（%）
            healthy_decay_threshold: 健康 IC 衰减阈值（%）
            degrading_decay_threshold: 降级 IC 衰减阈值（%）
            ic_window_short: 短期 IC 窗口大小
            ic_window_long: 长期 IC 窗口大小
            min_samples: 最小样本数
            max_consecutive_losses_degrading: 降级连续亏损阈值
            max_consecutive_losses_failed: 失败连续亏损阈值
            low_liq_duration_threshold: 低流动性持续时间阈值（秒）
            max_history: 最大历史记录数
        """
        self.pnl_attribution = pnl_attribution
        self.metrics_collector = metrics_collector
        self.market_state_detector = market_state_detector

        # 健康阈值
        self.healthy_ic_threshold = healthy_ic_threshold
        self.degrading_ic_threshold = degrading_ic_threshold
        self.healthy_alpha_threshold = healthy_alpha_threshold
        self.degrading_alpha_threshold = degrading_alpha_threshold
        self.healthy_decay_threshold = healthy_decay_threshold
        self.degrading_decay_threshold = degrading_decay_threshold

        # IC 计算窗口
        self.ic_window_short = ic_window_short
        self.ic_window_long = ic_window_long
        self.min_samples = min_samples

        # 连续亏损检测
        self.max_consecutive_losses_degrading = max_consecutive_losses_degrading
        self.max_consecutive_losses_failed = max_consecutive_losses_failed

        # 市场状态影响
        self.low_liq_duration_threshold = low_liq_duration_threshold

        # 历史数据
        self._ic_history: deque = deque(maxlen=max_history)  # IC 历史
        self._market_state_history: deque = deque(maxlen=max_history)  # 市场状态历史
        self._consecutive_losses = 0  # 当前连续亏损次数
        self._low_liq_start_time: int | None = None  # 低流动性开始时间

        logger.info(
            "alpha_health_checker_initialized",
            healthy_ic=healthy_ic_threshold,
            degrading_ic=degrading_ic_threshold,
            healthy_alpha=healthy_alpha_threshold,
            degrading_alpha=degrading_alpha_threshold,
            ic_window_short=ic_window_short,
            ic_window_long=ic_window_long,
        )

    def check_health(
        self,
        current_market_metrics: "MarketMetrics",
        current_timestamp: int,
    ) -> HealthMetrics:
        """
        检查 Alpha 健康度

        流程：
            1. 收集实时指标（IC、Alpha 占比、连续亏损）
            2. 计算 IC 衰减率（短期 vs 长期）
            3. 考虑市场状态影响
            4. 分类健康状态（HEALTHY/DEGRADING/FAILED）
            5. 生成系统响应建议

        Args:
            current_market_metrics: 当前市场指标
            current_timestamp: 当前时间戳

        Returns:
            HealthMetrics: 健康度量指标和系统建议
        """
        try:
            # 1. 收集基础指标
            current_ic = self._get_current_ic()
            alpha_percentage = self._get_alpha_percentage()
            ic_decay_rate = self._calculate_ic_decay()
            market_state = current_market_metrics.detected_state

            # 2. 更新历史数据
            self._ic_history.append((current_timestamp, current_ic))
            self._market_state_history.append((current_timestamp, market_state))

            # 3. 检测市场状态持续时间
            low_liq_duration = self._get_low_liq_duration(
                market_state, current_timestamp
            )

            # 4. 获取统计信息
            signal_metrics = self.metrics_collector.get_signal_metrics()
            signal_count = signal_metrics.get("total_signals", 0)
            trade_count = len(self.pnl_attribution._attribution_history)
            avg_signal_strength = signal_metrics.get("avg_signal_strength", 0.0)

            # 5. 分类健康状态
            status = self._determine_health_status(
                ic=current_ic,
                alpha_percentage=alpha_percentage,
                ic_decay_rate=ic_decay_rate,
                market_state=market_state,
                low_liq_duration=low_liq_duration,
                consecutive_losses=self._consecutive_losses,
            )

            # 6. 生成系统响应建议
            recommendations = self._generate_recommendations(
                status=status,
                ic=current_ic,
                alpha_percentage=alpha_percentage,
                ic_decay_rate=ic_decay_rate,
                market_state=market_state,
            )

            # 7. 创建健康度量对象
            health_metrics = HealthMetrics(
                status=status,
                ic=current_ic,
                alpha_percentage=alpha_percentage,
                ic_decay_rate=ic_decay_rate,
                market_state=market_state,
                signal_count=signal_count,
                trade_count=trade_count,
                avg_signal_strength=avg_signal_strength,
                consecutive_losses=self._consecutive_losses,
                timestamp=current_timestamp,
                **recommendations,  # 解包系统建议
            )

            logger.info(
                "alpha_health_checked",
                status=status.value,
                ic=current_ic,
                alpha_pct=alpha_percentage,
                ic_decay=ic_decay_rate,
                market_state=market_state.value,
                recommend_stop=recommendations["recommend_stop_trading"],
            )

            return health_metrics

        except Exception as e:
            logger.error(
                "health_check_error",
                error=str(e),
                exc_info=True,
            )
            raise

    def _get_current_ic(self) -> float:
        """
        获取当前 IC（使用短期窗口）

        Returns:
            float: 当前 IC 值
        """
        ic_stats = self.metrics_collector.get_ic_stats()
        return ic_stats.get("ic", 0.0)

    def _get_alpha_percentage(self) -> float:
        """
        获取 Alpha 占比

        Returns:
            float: Alpha 占比（%）
        """
        percentages = self.pnl_attribution.get_attribution_percentages()
        return abs(percentages.get("alpha", 0.0))  # 使用绝对值

    def _calculate_ic_decay(self) -> float:
        """
        计算 IC 衰减率

        逻辑：
            - 短期 IC（最近 100 个样本）
            - 长期 IC（过去 500 个样本）
            - 衰减率 = (长期 IC - 短期 IC) / 长期 IC × 100%
            - 只报告衰减（正值），不报告改善（负值归零）

        Returns:
            float: IC 衰减率（%）
        """
        if len(self._ic_history) < self.min_samples:
            return 0.0

        # 获取短期和长期 IC
        recent_ics = [ic for _, ic in list(self._ic_history)[-self.ic_window_short :]]
        all_ics = [ic for _, ic in list(self._ic_history)[-self.ic_window_long :]]

        if len(recent_ics) < self.min_samples or len(all_ics) < self.min_samples:
            return 0.0

        # 计算平均 IC
        recent_ic_avg = sum(recent_ics) / len(recent_ics)
        baseline_ic_avg = sum(all_ics) / len(all_ics)

        # 计算衰减率
        if baseline_ic_avg == 0:
            return 0.0

        decay_pct = (baseline_ic_avg - recent_ic_avg) / abs(baseline_ic_avg) * 100

        # 只报告衰减（正值），不报告改善（负值归零）
        return max(0.0, decay_pct)

    def _get_low_liq_duration(
        self, current_state: MarketState, current_timestamp: int
    ) -> int:
        """
        获取低流动性持续时间

        Args:
            current_state: 当前市场状态
            current_timestamp: 当前时间戳

        Returns:
            int: 低流动性持续时间（秒）
        """
        if current_state == MarketState.LOW_LIQ:
            if self._low_liq_start_time is None:
                self._low_liq_start_time = current_timestamp
            return current_timestamp - self._low_liq_start_time
        else:
            self._low_liq_start_time = None
            return 0

    def _determine_health_status(
        self,
        ic: float,
        alpha_percentage: float,
        ic_decay_rate: float,
        market_state: MarketState,
        low_liq_duration: int,
        consecutive_losses: int,
    ) -> HealthStatus:
        """
        确定健康状态

        优先级：FAILED > DEGRADING > HEALTHY

        Args:
            ic: 当前 IC
            alpha_percentage: Alpha 占比（%）
            ic_decay_rate: IC 衰减率（%）
            market_state: 市场状态
            low_liq_duration: 低流动性持续时间（秒）
            consecutive_losses: 连续亏损次数

        Returns:
            HealthStatus: 健康状态
        """
        # 1. 优先检测 FAILED 状态
        if (
            ic < self.degrading_ic_threshold
            or alpha_percentage < self.degrading_alpha_threshold
            or ic_decay_rate > self.degrading_decay_threshold
            or consecutive_losses > self.max_consecutive_losses_failed
            or low_liq_duration > self.low_liq_duration_threshold
        ):
            return HealthStatus.FAILED

        # 2. 检测 DEGRADING 状态
        if (
            self.degrading_ic_threshold <= ic < self.healthy_ic_threshold
            or self.degrading_alpha_threshold
            <= alpha_percentage
            < self.healthy_alpha_threshold
            or self.healthy_decay_threshold <= ic_decay_rate < self.degrading_decay_threshold
            or consecutive_losses >= self.max_consecutive_losses_degrading
            or market_state in (MarketState.HIGH_VOL, MarketState.LOW_LIQ)
        ):
            return HealthStatus.DEGRADING

        # 3. 默认为 HEALTHY
        return HealthStatus.HEALTHY

    def _generate_recommendations(
        self,
        status: HealthStatus,
        ic: float,
        alpha_percentage: float,
        ic_decay_rate: float,
        market_state: MarketState,
    ) -> dict:
        """
        生成系统响应建议

        Args:
            status: 健康状态
            ic: 当前 IC
            alpha_percentage: Alpha 占比（%）
            ic_decay_rate: IC 衰减率（%）
            market_state: 市场状态

        Returns:
            dict: 系统响应建议
        """
        # 默认建议（健康状态）
        recommendations = {
            "recommend_stop_trading": False,
            "recommend_reduce_size": False,
            "recommend_increase_threshold": False,
            "recommended_size_factor": 1.0,  # 不调整
            "recommended_theta_adjustment": 0.0,  # 不调整
        }

        # FAILED 状态：停止交易
        if status == HealthStatus.FAILED:
            recommendations["recommend_stop_trading"] = True
            recommendations["recommend_reduce_size"] = True
            recommendations["recommended_size_factor"] = 0.0  # 停止
            recommendations["recommended_theta_adjustment"] = 0.2  # 大幅提高阈值

        # DEGRADING 状态：减小尺寸、提高阈值
        elif status == HealthStatus.DEGRADING:
            recommendations["recommend_reduce_size"] = True
            recommendations["recommend_increase_threshold"] = True
            recommendations["recommended_size_factor"] = 0.5  # 减半
            recommendations["recommended_theta_adjustment"] = 0.1  # 提高阈值

            # 如果 IC 衰减严重，进一步降低尺寸
            if ic_decay_rate > 30.0:
                recommendations["recommended_size_factor"] = 0.3

            # 如果市场状态不佳，也建议提高阈值
            if market_state == MarketState.LOW_LIQ:
                recommendations["recommended_theta_adjustment"] = 0.15

        return recommendations

    def update_consecutive_losses(self, is_loss: bool) -> None:
        """
        更新连续亏损计数

        Args:
            is_loss: 是否亏损
        """
        if is_loss:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

    def get_ic_history(self, window: int | None = None) -> list[tuple[int, float]]:
        """
        获取 IC 历史

        Args:
            window: 窗口大小（None = 全部）

        Returns:
            list[tuple[int, float]]: IC 历史（时间戳, IC 值）
        """
        if window is None:
            return list(self._ic_history)
        return list(self._ic_history)[-window:]

    def get_market_state_distribution(self) -> dict[MarketState, int]:
        """
        获取市场状态分布

        Returns:
            dict[MarketState, int]: 市场状态计数
        """
        distribution: dict[MarketState, int] = {
            MarketState.NORMAL: 0,
            MarketState.HIGH_VOL: 0,
            MarketState.LOW_LIQ: 0,
            MarketState.CHOPPY: 0,
        }

        for _, state in self._market_state_history:
            distribution[state] += 1

        return distribution

    def reset(self) -> None:
        """重置健康检查器状态（用于测试或重新开始）"""
        self._ic_history.clear()
        self._market_state_history.clear()
        self._consecutive_losses = 0
        self._low_liq_start_time = None
        logger.info("alpha_health_checker_reset")

    def __repr__(self) -> str:
        return (
            f"AlphaHealthChecker("
            f"healthy_ic={self.healthy_ic_threshold:.3f}, "
            f"degrading_ic={self.degrading_ic_threshold:.3f}, "
            f"healthy_alpha={self.healthy_alpha_threshold:.1f}%, "
            f"degrading_alpha={self.degrading_alpha_threshold:.1f}%)"
        )
