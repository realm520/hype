"""实时监控器

实时输出关键指标并触发异常告警。
用于影子交易系统的运行时监控。
"""

import time
from typing import Any

import structlog

from src.analytics.shadow_analyzer import ShadowAnalyzer

logger = structlog.get_logger()


class LiveMonitor:
    """实时监控器

    职责：
        1. 定期（如每分钟）输出关键指标
        2. 检测异常（延迟突增、成交率骤降）
        3. 触发告警（日志 + 文件记录）
        4. 生成实时监控日志
    """

    def __init__(
        self,
        analyzer: ShadowAnalyzer,
        update_interval_seconds: int = 60,
        alert_thresholds: dict[str, Any] = None,
    ):
        """
        初始化实时监控器

        Args:
            analyzer: 影子交易分析器
            update_interval_seconds: 更新间隔（秒）
            alert_thresholds: 告警阈值
        """
        self.analyzer = analyzer
        self.update_interval_seconds = update_interval_seconds

        # 默认告警阈值
        # 注意：百分比值的命名约定
        # - *_pct 后缀：表示百分数值（80 表示 80%）
        # - *_ms 后缀：表示毫秒值
        self.alert_thresholds = alert_thresholds or {
            "latency_ms": 200,  # 延迟超过 200ms 告警
            "fill_rate_pct": 80,  # 成交率低于 80%（百分数）告警
            "drawdown_pct": 3.0,  # 回撤超过 3.0%（百分数）告警
            "consecutive_losses": 5,  # 连续亏损 5 次告警
        }

        self._last_update_time = time.time()
        self._alert_count = 0

        logger.info(
            "live_monitor_initialized",
            update_interval_seconds=update_interval_seconds,
            alert_thresholds=self.alert_thresholds,
        )

    async def update(self) -> None:
        """更新监控指标（异步）"""
        current_time = time.time()

        # 检查是否到达更新时间
        if current_time - self._last_update_time < self.update_interval_seconds:
            return

        try:
            # 计算最新指标
            signal_quality = self.analyzer.calculate_signal_quality()
            execution_efficiency = self.analyzer.calculate_execution_efficiency()
            risk_metrics = self.analyzer.calculate_risk_metrics()
            pnl_attribution = self.analyzer.calculate_pnl_attribution()

            # 输出监控日志
            logger.info(
                "live_monitor_update",
                # 信号质量
                ic=signal_quality.ic,
                ic_p_value=signal_quality.ic_p_value,
                # 执行效率
                avg_latency_ms=execution_efficiency.avg_total_latency_ms,
                p99_latency_ms=execution_efficiency.p99_total_latency_ms,
                fill_rate_pct=execution_efficiency.fill_rate,
                avg_slippage_bps=execution_efficiency.avg_slippage_bps,
                # 风控
                max_drawdown_pct=risk_metrics.max_drawdown_pct,
                consecutive_losses=risk_metrics.consecutive_losses,
                # PnL
                total_pnl=float(pnl_attribution.total_pnl),
                alpha_pct=pnl_attribution.alpha_percentage,
                cost_pct=pnl_attribution.cost_percentage,
                win_rate_pct=pnl_attribution.win_rate,
            )

            # 异常检测和告警
            self._check_alerts(
                execution_efficiency, risk_metrics, pnl_attribution
            )

            self._last_update_time = current_time

        except Exception as e:
            logger.error("live_monitor_update_error", error=str(e), exc_info=True)

    def _check_alerts(
        self, execution_efficiency, risk_metrics, pnl_attribution
    ) -> None:
        """检查异常并触发告警"""

        # 1. 延迟告警（至少需要 20 个样本才能可靠计算 p99）
        # 获取执行记录数量，确保样本充足
        sample_count = getattr(execution_efficiency, 'sample_count', 0)

        if (
            execution_efficiency.p99_total_latency_ms
            > self.alert_thresholds["latency_ms"]
            and sample_count >= 20  # 样本数量检查
        ):
            self._trigger_alert(
                "HIGH_LATENCY",
                f"p99 延迟 {execution_efficiency.p99_total_latency_ms:.1f}ms "
                f"超过阈值 {self.alert_thresholds['latency_ms']}ms "
                f"(样本数: {sample_count})",
            )

        # 2. 成交率告警
        if execution_efficiency.fill_rate < self.alert_thresholds["fill_rate_pct"]:
            self._trigger_alert(
                "LOW_FILL_RATE",
                f"成交率 {execution_efficiency.fill_rate:.1f}% "
                f"低于阈值 {self.alert_thresholds['fill_rate_pct']}%",
            )

        # 3. 回撤告警
        if risk_metrics.max_drawdown_pct > self.alert_thresholds["drawdown_pct"]:
            self._trigger_alert(
                "HIGH_DRAWDOWN",
                f"最大回撤 {risk_metrics.max_drawdown_pct:.2f}% "
                f"超过阈值 {self.alert_thresholds['drawdown_pct']}%",
            )

        # 4. 连续亏损告警
        if (
            risk_metrics.consecutive_losses
            > self.alert_thresholds["consecutive_losses"]
        ):
            self._trigger_alert(
                "CONSECUTIVE_LOSSES",
                f"连续亏损 {risk_metrics.consecutive_losses} 次 "
                f"超过阈值 {self.alert_thresholds['consecutive_losses']} 次",
            )

    def _trigger_alert(self, alert_type: str, message: str) -> None:
        """触发告警"""
        self._alert_count += 1

        logger.warning(
            "alert_triggered",
            alert_type=alert_type,
            message=message,
            alert_count=self._alert_count,
        )

    def get_statistics(self) -> dict[str, Any]:
        """获取监控统计"""
        return {
            "update_interval_seconds": self.update_interval_seconds,
            "last_update_time": self._last_update_time,
            "alert_count": self._alert_count,
            "alert_thresholds": self.alert_thresholds,
        }
