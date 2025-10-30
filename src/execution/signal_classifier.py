"""信号强度分级器

根据信号评分值对信号进行分级（HIGH/MEDIUM/LOW），用于混合执行策略。
"""


import numpy as np
import structlog

from src.core.types import ConfidenceLevel

logger = structlog.get_logger(__name__)


class SignalClassifier:
    """信号强度分级器

    基于历史信号分布校准阈值，将信号评分分为三个置信度等级：
    - HIGH: Top 10% 信号（|score| > θ₁）
    - MEDIUM: Top 30% 信号（θ₂ < |score| ≤ θ₁）
    - LOW: 其他信号（|score| ≤ θ₂）
    """

    def __init__(
        self,
        theta_1: float | None = None,
        theta_2: float | None = None,
    ):
        """初始化信号分级器

        Args:
            theta_1: 高置信度阈值（Top 10%），默认 0.45
            theta_2: 中置信度阈值（Top 30%），默认 0.25
        """
        self.theta_1 = theta_1 if theta_1 is not None else 0.45
        self.theta_2 = theta_2 if theta_2 is not None else 0.25

        # 验证阈值合理性（先验证正值，再验证大小关系）
        if self.theta_1 <= 0 or self.theta_2 <= 0:
            raise ValueError("Thresholds must be positive")

        if self.theta_2 >= self.theta_1:
            raise ValueError(
                f"theta_2 ({self.theta_2}) must be < theta_1 ({self.theta_1})"
            )

        logger.info(
            "signal_classifier_initialized",
            theta_1=self.theta_1,
            theta_2=self.theta_2,
        )

    def calibrate_thresholds(
        self,
        signal_scores: list[float] | np.ndarray,
        top_pct_high: float = 0.10,
        top_pct_medium: float = 0.30,
    ) -> tuple[float, float]:
        """基于历史信号分布校准阈值

        Args:
            signal_scores: 历史信号评分列表
            top_pct_high: 高置信度分位数（默认 Top 10%）
            top_pct_medium: 中置信度分位数（默认 Top 30%）

        Returns:
            tuple[float, float]: (theta_1, theta_2)

        Raises:
            ValueError: 如果信号数据不足或参数无效
        """
        if len(signal_scores) < 100:
            raise ValueError(
                f"Insufficient data for calibration: {len(signal_scores)} < 100"
            )

        if not (0 < top_pct_high < top_pct_medium < 1.0):
            raise ValueError(
                f"Invalid percentiles: high={top_pct_high}, medium={top_pct_medium}"
            )

        # 使用绝对值进行分位数计算（因为信号可正可负）
        abs_scores = np.abs(signal_scores)

        # 计算分位数（1 - top_pct 因为我们要的是 Top X%）
        theta_1 = float(np.quantile(abs_scores, 1 - top_pct_high))
        theta_2 = float(np.quantile(abs_scores, 1 - top_pct_medium))

        # 更新实例阈值
        self.theta_1 = theta_1
        self.theta_2 = theta_2

        logger.info(
            "thresholds_calibrated",
            theta_1=theta_1,
            theta_2=theta_2,
            sample_size=len(signal_scores),
            top_pct_high=top_pct_high,
            top_pct_medium=top_pct_medium,
        )

        return theta_1, theta_2

    def classify(self, signal_score: float) -> ConfidenceLevel:
        """对信号评分进行分级

        Args:
            signal_score: 信号评分值（可正可负）

        Returns:
            ConfidenceLevel: 置信度等级（HIGH/MEDIUM/LOW）
        """
        abs_score = abs(signal_score)

        if abs_score > self.theta_1:
            level = ConfidenceLevel.HIGH
        elif abs_score > self.theta_2:
            level = ConfidenceLevel.MEDIUM
        else:
            level = ConfidenceLevel.LOW

        logger.debug(
            "signal_classified",
            signal_score=signal_score,
            abs_score=abs_score,
            confidence=level.value,
        )

        return level

    def get_thresholds(self) -> tuple[float, float]:
        """获取当前阈值

        Returns:
            tuple[float, float]: (theta_1, theta_2)
        """
        return self.theta_1, self.theta_2

    def get_statistics(self, signal_scores: list[float] | np.ndarray) -> dict:
        """获取信号分布统计

        Args:
            signal_scores: 信号评分列表

        Returns:
            dict: 统计信息，包含各等级占比和阈值
        """
        if len(signal_scores) == 0:
            return {
                "total": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "high_pct": 0.0,
                "medium_pct": 0.0,
                "low_pct": 0.0,
                "theta_1": self.theta_1,
                "theta_2": self.theta_2,
            }

        # 对所有信号进行分级
        levels = [self.classify(score) for score in signal_scores]

        # 统计各等级数量
        high_count = sum(1 for level in levels if level == ConfidenceLevel.HIGH)
        medium_count = sum(1 for level in levels if level == ConfidenceLevel.MEDIUM)
        low_count = sum(1 for level in levels if level == ConfidenceLevel.LOW)

        total = len(signal_scores)

        return {
            "total": total,
            "high_count": high_count,
            "medium_count": medium_count,
            "low_count": low_count,
            "high_pct": high_count / total * 100,
            "medium_pct": medium_count / total * 100,
            "low_pct": low_count / total * 100,
            "theta_1": self.theta_1,
            "theta_2": self.theta_2,
        }

    def __repr__(self) -> str:
        return (
            f"SignalClassifier(theta_1={self.theta_1:.4f}, "
            f"theta_2={self.theta_2:.4f})"
        )
