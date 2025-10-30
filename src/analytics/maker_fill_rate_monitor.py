"""Maker 成交率监控器

Week 1.5 混合策略健康度监控：实时追踪 Maker 订单成交率。
"""

from collections import deque

import structlog

from src.core.types import ConfidenceLevel, Order

logger = structlog.get_logger(__name__)


class MakerFillRateMonitor:
    """Maker 成交率监控器

    滑动窗口统计 Maker 订单成交率，分置信度级别监控：
        - HIGH 置信度目标成交率：≥ 80%
        - MEDIUM 置信度目标成交率：≥ 75%

    告警机制：
        - 成交率低于告警阈值 → WARNING 日志
        - 成交率低于严重阈值 → CRITICAL 日志 + 风控触发

    用途：
        1. 动态调整超时参数
        2. 决定是否降级为纯 IOC 策略
        3. 评估 Maker 策略有效性
    """

    def __init__(
        self,
        window_size: int = 100,
        alert_threshold_high: float = 0.80,
        alert_threshold_medium: float = 0.75,
        critical_threshold: float = 0.60,
    ):
        """
        初始化 Maker 成交率监控器

        Args:
            window_size: 滑动窗口大小（最近 N 次尝试）
            alert_threshold_high: HIGH 置信度告警阈值（默认 80%）
            alert_threshold_medium: MEDIUM 置信度告警阈值（默认 75%）
            critical_threshold: 严重告警阈值（触发风控，默认 60%）
        """
        self.window_size = window_size
        self.alert_threshold_high = alert_threshold_high
        self.alert_threshold_medium = alert_threshold_medium
        self.critical_threshold = critical_threshold

        # 滑动窗口（分置信度级别存储）
        # 格式：deque[(order_id, filled: bool), ...]
        self._high_window: deque = deque(maxlen=window_size)
        self._medium_window: deque = deque(maxlen=window_size)

        # 累计统计（全局，不受窗口限制）
        self._total_stats = {
            "high_attempts": 0,
            "high_filled": 0,
            "medium_attempts": 0,
            "medium_filled": 0,
        }

        logger.info(
            "maker_fill_rate_monitor_initialized",
            window_size=window_size,
            alert_threshold_high=alert_threshold_high,
            alert_threshold_medium=alert_threshold_medium,
            critical_threshold=critical_threshold,
        )

    def record_maker_attempt(
        self,
        order: Order,
        confidence: ConfidenceLevel,
        filled: bool,
    ) -> None:
        """
        记录一次 Maker 订单尝试

        Args:
            order: 订单对象
            confidence: 信号置信度
            filled: 是否成交（True = 成交，False = 超时/取消）
        """
        record = (order.id, filled)

        if confidence == ConfidenceLevel.HIGH:
            self._high_window.append(record)
            self._total_stats["high_attempts"] += 1
            if filled:
                self._total_stats["high_filled"] += 1
        elif confidence == ConfidenceLevel.MEDIUM:
            self._medium_window.append(record)
            self._total_stats["medium_attempts"] += 1
            if filled:
                self._total_stats["medium_filled"] += 1

        logger.debug(
            "maker_attempt_recorded",
            order_id=order.id,
            confidence=confidence.name,
            filled=filled,
            symbol=order.symbol,
        )

        # 检查告警
        self._check_alert(confidence)

    def get_fill_rate(
        self, confidence: ConfidenceLevel, window_based: bool = True
    ) -> float | None:
        """
        获取 Maker 成交率

        Args:
            confidence: 置信度级别
            window_based: 是否基于滑动窗口（True = 窗口，False = 全局）

        Returns:
            Optional[float]: 成交率（0.0 ~ 1.0），数据不足则返回 None
        """
        if window_based:
            # 基于滑动窗口
            if confidence == ConfidenceLevel.HIGH:
                window = self._high_window
            elif confidence == ConfidenceLevel.MEDIUM:
                window = self._medium_window
            else:
                return None

            if len(window) == 0:
                return None

            filled_count = sum(1 for _, filled in window if filled)
            return filled_count / len(window)

        else:
            # 基于全局统计
            if confidence == ConfidenceLevel.HIGH:
                attempts = self._total_stats["high_attempts"]
                filled = self._total_stats["high_filled"]
            elif confidence == ConfidenceLevel.MEDIUM:
                attempts = self._total_stats["medium_attempts"]
                filled = self._total_stats["medium_filled"]
            else:
                return None

            if attempts == 0:
                return None

            return filled / attempts

    def get_statistics(self) -> dict:
        """
        获取详细统计数据

        Returns:
            dict: 统计信息，包含窗口和全局数据
        """
        # HIGH 置信度统计
        high_fill_rate_window = self.get_fill_rate(
            ConfidenceLevel.HIGH, window_based=True
        )
        high_fill_rate_total = self.get_fill_rate(
            ConfidenceLevel.HIGH, window_based=False
        )

        # MEDIUM 置信度统计
        medium_fill_rate_window = self.get_fill_rate(
            ConfidenceLevel.MEDIUM, window_based=True
        )
        medium_fill_rate_total = self.get_fill_rate(
            ConfidenceLevel.MEDIUM, window_based=False
        )

        return {
            # HIGH 置信度
            "high": {
                "window_fill_rate": (
                    high_fill_rate_window if high_fill_rate_window is not None else 0.0
                ),
                "total_fill_rate": (
                    high_fill_rate_total if high_fill_rate_total is not None else 0.0
                ),
                "window_size": len(self._high_window),
                "total_attempts": self._total_stats["high_attempts"],
                "total_filled": self._total_stats["high_filled"],
                "alert_threshold": self.alert_threshold_high,
            },
            # MEDIUM 置信度
            "medium": {
                "window_fill_rate": (
                    medium_fill_rate_window
                    if medium_fill_rate_window is not None
                    else 0.0
                ),
                "total_fill_rate": (
                    medium_fill_rate_total if medium_fill_rate_total is not None else 0.0
                ),
                "window_size": len(self._medium_window),
                "total_attempts": self._total_stats["medium_attempts"],
                "total_filled": self._total_stats["medium_filled"],
                "alert_threshold": self.alert_threshold_medium,
            },
            # 全局
            "overall": {
                "critical_threshold": self.critical_threshold,
                "window_max_size": self.window_size,
            },
        }

    def is_healthy(self, confidence: ConfidenceLevel) -> bool:
        """
        检查成交率是否健康

        Args:
            confidence: 置信度级别

        Returns:
            bool: 是否健康（True = 健康，False = 不健康）
        """
        fill_rate = self.get_fill_rate(confidence, window_based=True)

        if fill_rate is None:
            # 数据不足，暂时认为健康
            return True

        threshold = (
            self.alert_threshold_high
            if confidence == ConfidenceLevel.HIGH
            else self.alert_threshold_medium
        )

        return fill_rate >= threshold

    def is_critical(self, confidence: ConfidenceLevel) -> bool:
        """
        检查是否触发严重告警（需要风控介入）

        Args:
            confidence: 置信度级别

        Returns:
            bool: 是否严重（True = 严重，False = 正常）
        """
        fill_rate = self.get_fill_rate(confidence, window_based=True)

        if fill_rate is None:
            # 数据不足，不触发严重告警
            return False

        return fill_rate < self.critical_threshold

    def reset_statistics(self) -> None:
        """重置所有统计数据"""
        self._high_window.clear()
        self._medium_window.clear()

        for key in self._total_stats:
            self._total_stats[key] = 0

        logger.info("maker_fill_rate_monitor_reset")

    def _check_alert(self, confidence: ConfidenceLevel) -> None:
        """
        检查告警条件（内部方法）

        Args:
            confidence: 置信度级别
        """
        fill_rate = self.get_fill_rate(confidence, window_based=True)

        if fill_rate is None:
            # 数据不足，不告警
            return

        threshold = (
            self.alert_threshold_high
            if confidence == ConfidenceLevel.HIGH
            else self.alert_threshold_medium
        )

        if fill_rate < self.critical_threshold:
            # 严重告警
            logger.critical(
                "maker_fill_rate_critical",
                confidence=confidence.name,
                fill_rate=fill_rate,
                critical_threshold=self.critical_threshold,
                window_size=len(
                    self._high_window
                    if confidence == ConfidenceLevel.HIGH
                    else self._medium_window
                ),
            )
        elif fill_rate < threshold:
            # 普通告警
            logger.warning(
                "maker_fill_rate_below_threshold",
                confidence=confidence.name,
                fill_rate=fill_rate,
                threshold=threshold,
                window_size=len(
                    self._high_window
                    if confidence == ConfidenceLevel.HIGH
                    else self._medium_window
                ),
            )

    def __repr__(self) -> str:
        stats = self.get_statistics()
        return (
            f"MakerFillRateMonitor("
            f"HIGH={stats['high']['window_fill_rate']:.2%}, "
            f"MEDIUM={stats['medium']['window_fill_rate']:.2%}, "
            f"window={self.window_size})"
        )
