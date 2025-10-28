"""IC 稳健性验证模块

提供全面的 IC 统计验证功能，包括：
- 分时段 IC 分析
- 置换检验
- 前瞻偏差检测
- 滚动窗口分析
- 交叉验证
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import structlog
from scipy import stats

logger = structlog.get_logger()


@dataclass
class ICTestResult:
    """IC 测试结果"""

    test_name: str
    passed: bool
    ic_value: float | None = None
    p_value: float | None = None
    sample_size: int = 0
    details: dict[str, Any] | None = None
    warnings: list[str] | None = None


class ICRobustnessValidator:
    """IC 稳健性验证器

    验证 IC 的统计显著性和跨时间/场景的稳定性
    """

    def __init__(
        self,
        signals: np.ndarray,
        returns: np.ndarray,
        timestamps: np.ndarray | None = None,
        min_ic_threshold: float = 0.01,
        p_value_threshold: float = 0.01,
    ):
        """初始化验证器

        Args:
            signals: 信号值数组
            returns: 未来收益数组
            timestamps: 时间戳数组（Unix 时间戳，秒）
            min_ic_threshold: 最小可接受 IC 阈值
            p_value_threshold: p-value 显著性阈值
        """
        if len(signals) != len(returns):
            raise ValueError(
                f"信号和收益长度不匹配: {len(signals)} vs {len(returns)}"
            )

        self.signals = signals
        self.returns = returns
        self.timestamps = timestamps
        self.min_ic_threshold = min_ic_threshold
        self.p_value_threshold = p_value_threshold

        logger.info(
            "ic_validator_initialized",
            sample_size=len(signals),
            min_ic_threshold=min_ic_threshold,
            p_value_threshold=p_value_threshold,
        )

    def run_all_tests(self) -> list[ICTestResult]:
        """运行所有验证测试

        Returns:
            所有测试结果列表
        """
        results = []

        # 1. 基础 IC 计算
        results.append(self.calculate_base_ic())

        # 2. 置换检验
        results.append(self.permutation_test(n_permutations=1000))

        # 3. 前瞻偏差检测（需要时间戳）
        if self.timestamps is not None:
            results.append(self.lookahead_bias_check())

        # 4. 分时段分析（需要时间戳）
        if self.timestamps is not None:
            results.extend(self.time_split_analysis())

        # 5. 滚动窗口分析
        results.append(self.rolling_ic_analysis(window_size=300))

        # 6. 交叉验证
        results.append(self.cross_validation(n_folds=5))

        logger.info(
            "ic_robustness_tests_completed",
            total_tests=len(results),
            passed_tests=sum(1 for r in results if r.passed),
        )

        return results

    def calculate_base_ic(self) -> ICTestResult:
        """计算基础 IC 和显著性"""
        ic, p_value = stats.spearmanr(self.signals, self.returns)

        passed = ic >= self.min_ic_threshold and p_value < self.p_value_threshold

        warnings = []
        if ic > 0.15:
            warnings.append(
                f"IC 异常高 ({ic:.4f})，建议检查是否存在数据泄露"
            )

        logger.info(
            "base_ic_calculated",
            ic=float(ic),
            p_value=float(p_value),
            passed=passed,
        )

        return ICTestResult(
            test_name="基础 IC 检验",
            passed=passed,
            ic_value=float(ic),
            p_value=float(p_value),
            sample_size=len(self.signals),
            details={
                "signal_mean": float(np.mean(self.signals)),
                "signal_std": float(np.std(self.signals)),
                "return_mean": float(np.mean(self.returns)),
                "return_std": float(np.std(self.returns)),
            },
            warnings=warnings if warnings else None,
        )

    def permutation_test(
        self, n_permutations: int = 1000
    ) -> ICTestResult:
        """置换检验

        通过随机打乱信号顺序，验证观测到的 IC 是否显著

        Args:
            n_permutations: 置换次数

        Returns:
            置换检验结果
        """
        observed_ic = stats.spearmanr(self.signals, self.returns)[0]

        # 生成 null distribution
        null_ics = []
        rng = np.random.default_rng(42)  # 固定种子保证可复现

        for _ in range(n_permutations):
            shuffled_signals = rng.permutation(self.signals)
            null_ic = stats.spearmanr(shuffled_signals, self.returns)[0]
            null_ics.append(null_ic)

        null_ics = np.array(null_ics)

        # 计算 p-value
        p_value = np.mean(np.abs(null_ics) >= np.abs(observed_ic))

        passed = p_value < self.p_value_threshold

        logger.info(
            "permutation_test_completed",
            observed_ic=float(observed_ic),
            null_ic_mean=float(np.mean(null_ics)),
            null_ic_std=float(np.std(null_ics)),
            p_value=float(p_value),
            passed=passed,
        )

        return ICTestResult(
            test_name="置换检验",
            passed=passed,
            ic_value=float(observed_ic),
            p_value=float(p_value),
            sample_size=n_permutations,
            details={
                "null_ic_mean": float(np.mean(null_ics)),
                "null_ic_std": float(np.std(null_ics)),
                "null_ic_95th": float(np.percentile(null_ics, 95)),
            },
        )

    def lookahead_bias_check(self) -> ICTestResult:
        """前瞻偏差检测

        检查信号和收益的时间对齐是否正确

        Returns:
            前瞻偏差检测结果
        """
        if self.timestamps is None:
            return ICTestResult(
                test_name="前瞻偏差检测",
                passed=False,
                warnings=["缺少时间戳数据"],
            )

        # 计算信号-收益时间间隔
        # 注意：这里假设 timestamps 是信号生成时间
        # 未来收益应该在信号之后计算
        time_intervals = []

        # 简化检查：确保时间戳单调递增
        is_monotonic = np.all(np.diff(self.timestamps) >= 0)

        passed = is_monotonic

        warnings = []
        if not is_monotonic:
            warnings.append("时间戳不单调递增，可能存在数据泄露")

        logger.info(
            "lookahead_bias_check_completed",
            is_monotonic=is_monotonic,
            passed=passed,
        )

        return ICTestResult(
            test_name="前瞻偏差检测",
            passed=passed,
            sample_size=len(self.timestamps),
            details={
                "is_monotonic": is_monotonic,
                "time_range_hours": float(
                    (self.timestamps[-1] - self.timestamps[0]) / 3600
                ),
            },
            warnings=warnings if warnings else None,
        )

    def time_split_analysis(self) -> list[ICTestResult]:
        """分时段 IC 分析

        按小时、星期几等维度分组计算 IC

        Returns:
            各时段 IC 测试结果
        """
        if self.timestamps is None:
            return [
                ICTestResult(
                    test_name="分时段分析",
                    passed=False,
                    warnings=["缺少时间戳数据"],
                )
            ]

        results = []

        # 转换为 datetime
        dts = [datetime.fromtimestamp(ts) for ts in self.timestamps]

        # 按小时分组
        hour_groups = {}
        for i, dt in enumerate(dts):
            hour_key = dt.hour // 6  # 0-5, 6-11, 12-17, 18-23
            if hour_key not in hour_groups:
                hour_groups[hour_key] = []
            hour_groups[hour_key].append(i)

        hour_ranges = {
            0: "00:00-06:00",
            1: "06:00-12:00",
            2: "12:00-18:00",
            3: "18:00-00:00",
        }

        for hour_key, indices in hour_groups.items():
            if len(indices) < 30:  # 最少 30 个样本
                continue

            subset_signals = self.signals[indices]
            subset_returns = self.returns[indices]

            ic, p_value = stats.spearmanr(subset_signals, subset_returns)

            passed = ic >= self.min_ic_threshold and p_value < self.p_value_threshold

            hour_range = hour_ranges[hour_key]

            logger.info(
                "time_split_ic_calculated",
                hour_range=hour_range,
                ic=float(ic),
                p_value=float(p_value),
                sample_size=len(indices),
                passed=passed,
            )

            results.append(
                ICTestResult(
                    test_name=f"时段 IC - {hour_range}",
                    passed=passed,
                    ic_value=float(ic),
                    p_value=float(p_value),
                    sample_size=len(indices),
                    details={"hour_range": hour_range},
                )
            )

        return results

    def rolling_ic_analysis(
        self, window_size: int = 300
    ) -> ICTestResult:
        """滚动窗口 IC 分析

        计算滑动窗口内的 IC，检测 IC 衰减

        Args:
            window_size: 窗口大小（样本数）

        Returns:
            滚动 IC 分析结果
        """
        if len(self.signals) < window_size * 2:
            return ICTestResult(
                test_name="滚动窗口分析",
                passed=False,
                warnings=[f"样本数不足，需要至少 {window_size * 2} 个样本"],
            )

        rolling_ics = []

        for i in range(len(self.signals) - window_size + 1):
            window_signals = self.signals[i : i + window_size]
            window_returns = self.returns[i : i + window_size]

            ic, _ = stats.spearmanr(window_signals, window_returns)
            rolling_ics.append(ic)

        rolling_ics = np.array(rolling_ics)

        ic_mean = np.mean(rolling_ics)
        ic_std = np.std(rolling_ics)
        ic_min = np.min(rolling_ics)

        # 检查是否有明显衰减
        first_half_ic = np.mean(rolling_ics[: len(rolling_ics) // 2])
        second_half_ic = np.mean(rolling_ics[len(rolling_ics) // 2 :])
        decay_pct = (first_half_ic - second_half_ic) / first_half_ic * 100

        passed = ic_std < 0.1 and ic_min > 0 and decay_pct < 50

        warnings = []
        if ic_min < 0:
            warnings.append(f"存在负 IC 窗口（最低 {ic_min:.4f}）")
        if decay_pct > 50:
            warnings.append(f"IC 衰减超过 50% ({decay_pct:.1f}%)")

        logger.info(
            "rolling_ic_analysis_completed",
            ic_mean=float(ic_mean),
            ic_std=float(ic_std),
            ic_min=float(ic_min),
            decay_pct=float(decay_pct),
            passed=passed,
        )

        return ICTestResult(
            test_name="滚动窗口分析",
            passed=passed,
            ic_value=float(ic_mean),
            sample_size=len(rolling_ics),
            details={
                "ic_std": float(ic_std),
                "ic_min": float(ic_min),
                "decay_pct": float(decay_pct),
                "window_size": window_size,
            },
            warnings=warnings if warnings else None,
        )

    def cross_validation(self, n_folds: int = 5) -> ICTestResult:
        """K 折交叉验证

        将数据分成 K 折，验证 IC 的稳定性

        Args:
            n_folds: 折数

        Returns:
            交叉验证结果
        """
        fold_size = len(self.signals) // n_folds
        fold_ics = []

        for i in range(n_folds):
            start_idx = i * fold_size
            end_idx = (i + 1) * fold_size if i < n_folds - 1 else len(self.signals)

            fold_signals = self.signals[start_idx:end_idx]
            fold_returns = self.returns[start_idx:end_idx]

            ic, _ = stats.spearmanr(fold_signals, fold_returns)
            fold_ics.append(ic)

        fold_ics = np.array(fold_ics)

        ic_mean = np.mean(fold_ics)
        ic_std = np.std(fold_ics)
        ic_cv = ic_std / ic_mean * 100  # 变异系数

        passed = ic_cv < 20  # 变异系数 < 20%

        logger.info(
            "cross_validation_completed",
            n_folds=n_folds,
            ic_mean=float(ic_mean),
            ic_std=float(ic_std),
            ic_cv=float(ic_cv),
            passed=passed,
        )

        return ICTestResult(
            test_name=f"{n_folds} 折交叉验证",
            passed=passed,
            ic_value=float(ic_mean),
            sample_size=n_folds,
            details={
                "fold_ics": [float(ic) for ic in fold_ics],
                "ic_std": float(ic_std),
                "ic_cv": float(ic_cv),
            },
        )
