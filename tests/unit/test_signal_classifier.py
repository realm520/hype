"""SignalClassifier 单元测试"""

import numpy as np
import pytest

from src.core.types import ConfidenceLevel
from src.execution.signal_classifier import SignalClassifier


class TestSignalClassifier:
    """SignalClassifier 测试类"""

    def test_initialization_default(self):
        """测试默认初始化"""
        classifier = SignalClassifier()

        assert classifier.theta_1 == 0.45
        assert classifier.theta_2 == 0.25

    def test_initialization_custom(self):
        """测试自定义阈值初始化"""
        classifier = SignalClassifier(theta_1=0.5, theta_2=0.3)

        assert classifier.theta_1 == 0.5
        assert classifier.theta_2 == 0.3

    def test_initialization_invalid_thresholds(self):
        """测试无效阈值初始化"""
        # theta_2 >= theta_1
        with pytest.raises(ValueError, match="must be <"):
            SignalClassifier(theta_1=0.3, theta_2=0.5)

        # 负值阈值
        with pytest.raises(ValueError, match="must be positive"):
            SignalClassifier(theta_1=-0.5, theta_2=0.3)

    def test_classify_high_confidence(self):
        """测试高置信度分级"""
        classifier = SignalClassifier(theta_1=0.5, theta_2=0.3)

        # 正值信号
        assert classifier.classify(0.6) == ConfidenceLevel.HIGH
        assert classifier.classify(0.51) == ConfidenceLevel.HIGH

        # 负值信号
        assert classifier.classify(-0.6) == ConfidenceLevel.HIGH
        assert classifier.classify(-0.51) == ConfidenceLevel.HIGH

    def test_classify_medium_confidence(self):
        """测试中置信度分级"""
        classifier = SignalClassifier(theta_1=0.5, theta_2=0.3)

        # 正值信号
        assert classifier.classify(0.4) == ConfidenceLevel.MEDIUM
        assert classifier.classify(0.31) == ConfidenceLevel.MEDIUM

        # 负值信号
        assert classifier.classify(-0.4) == ConfidenceLevel.MEDIUM
        assert classifier.classify(-0.31) == ConfidenceLevel.MEDIUM

    def test_classify_low_confidence(self):
        """测试低置信度分级"""
        classifier = SignalClassifier(theta_1=0.5, theta_2=0.3)

        # 正值信号
        assert classifier.classify(0.2) == ConfidenceLevel.LOW
        assert classifier.classify(0.1) == ConfidenceLevel.LOW

        # 负值信号
        assert classifier.classify(-0.2) == ConfidenceLevel.LOW
        assert classifier.classify(-0.1) == ConfidenceLevel.LOW

        # 零值
        assert classifier.classify(0.0) == ConfidenceLevel.LOW

    def test_classify_boundary_values(self):
        """测试边界值分级"""
        classifier = SignalClassifier(theta_1=0.5, theta_2=0.3)

        # theta_1 边界
        assert classifier.classify(0.5) == ConfidenceLevel.MEDIUM  # 等于阈值
        assert classifier.classify(0.500001) == ConfidenceLevel.HIGH  # 略大于阈值

        # theta_2 边界
        assert classifier.classify(0.3) == ConfidenceLevel.LOW  # 等于阈值
        assert classifier.classify(0.300001) == ConfidenceLevel.MEDIUM  # 略大于阈值

    def test_calibrate_thresholds_basic(self):
        """测试基础阈值校准"""
        classifier = SignalClassifier()

        # 生成正态分布信号（N(0, 1)）
        np.random.seed(42)
        signal_scores = np.random.randn(1000)

        theta_1, theta_2 = classifier.calibrate_thresholds(signal_scores)

        # 验证返回值
        assert isinstance(theta_1, float)
        assert isinstance(theta_2, float)
        assert theta_2 < theta_1

        # 验证实例阈值已更新
        assert classifier.theta_1 == theta_1
        assert classifier.theta_2 == theta_2

        # 验证阈值接近理论分位数（90th 和 70th 百分位）
        expected_theta_1 = np.quantile(np.abs(signal_scores), 0.9)
        expected_theta_2 = np.quantile(np.abs(signal_scores), 0.7)

        assert abs(theta_1 - expected_theta_1) < 0.01
        assert abs(theta_2 - expected_theta_2) < 0.01

    def test_calibrate_thresholds_custom_percentiles(self):
        """测试自定义分位数校准"""
        classifier = SignalClassifier()

        np.random.seed(42)
        signal_scores = np.random.randn(1000)

        # Top 20% 和 Top 40%
        theta_1, theta_2 = classifier.calibrate_thresholds(
            signal_scores, top_pct_high=0.2, top_pct_medium=0.4
        )

        # 验证阈值接近理论分位数
        expected_theta_1 = np.quantile(np.abs(signal_scores), 0.8)
        expected_theta_2 = np.quantile(np.abs(signal_scores), 0.6)

        assert abs(theta_1 - expected_theta_1) < 0.01
        assert abs(theta_2 - expected_theta_2) < 0.01

    def test_calibrate_thresholds_insufficient_data(self):
        """测试数据不足时校准失败"""
        classifier = SignalClassifier()

        # 数据量 < 100
        signal_scores = np.random.randn(50)

        with pytest.raises(ValueError, match="Insufficient data"):
            classifier.calibrate_thresholds(signal_scores)

    def test_calibrate_thresholds_invalid_percentiles(self):
        """测试无效分位数参数"""
        classifier = SignalClassifier()
        signal_scores = np.random.randn(1000)

        # high > medium
        with pytest.raises(ValueError, match="Invalid percentiles"):
            classifier.calibrate_thresholds(
                signal_scores, top_pct_high=0.4, top_pct_medium=0.2
            )

        # 超出 [0, 1] 范围
        with pytest.raises(ValueError, match="Invalid percentiles"):
            classifier.calibrate_thresholds(
                signal_scores, top_pct_high=1.5, top_pct_medium=0.3
            )

    def test_get_thresholds(self):
        """测试获取阈值"""
        classifier = SignalClassifier(theta_1=0.5, theta_2=0.3)

        theta_1, theta_2 = classifier.get_thresholds()

        assert theta_1 == 0.5
        assert theta_2 == 0.3

    def test_get_statistics_empty(self):
        """测试空信号列表统计"""
        classifier = SignalClassifier()

        stats = classifier.get_statistics([])

        assert stats["total"] == 0
        assert stats["high_count"] == 0
        assert stats["medium_count"] == 0
        assert stats["low_count"] == 0
        assert stats["high_pct"] == 0.0

    def test_get_statistics_basic(self):
        """测试基础统计"""
        classifier = SignalClassifier(theta_1=0.5, theta_2=0.3)

        # 构造已知分布的信号
        signal_scores = [
            0.6,
            -0.55,  # HIGH: 2
            0.4,
            -0.35,
            0.32,  # MEDIUM: 3
            0.2,
            -0.1,
            0.05,
            0.0,  # LOW: 4
        ]

        stats = classifier.get_statistics(signal_scores)

        assert stats["total"] == 9
        assert stats["high_count"] == 2
        assert stats["medium_count"] == 3
        assert stats["low_count"] == 4
        assert abs(stats["high_pct"] - 22.22) < 0.1
        assert abs(stats["medium_pct"] - 33.33) < 0.1
        assert abs(stats["low_pct"] - 44.44) < 0.1

    def test_get_statistics_with_calibration(self):
        """测试校准后的统计"""
        classifier = SignalClassifier()

        np.random.seed(42)
        signal_scores = list(np.random.randn(1000))

        # 先校准阈值（Top 10% 和 30%）
        classifier.calibrate_thresholds(signal_scores)

        # 再统计分布
        stats = classifier.get_statistics(signal_scores)

        # 验证分布接近预期（误差允许 ±2%）
        assert abs(stats["high_pct"] - 10.0) < 2.0
        assert abs(stats["medium_pct"] - 20.0) < 2.0
        assert abs(stats["low_pct"] - 70.0) < 2.0

    def test_repr(self):
        """测试字符串表示"""
        classifier = SignalClassifier(theta_1=0.5, theta_2=0.3)

        repr_str = repr(classifier)

        assert "SignalClassifier" in repr_str
        assert "theta_1=0.5000" in repr_str
        assert "theta_2=0.3000" in repr_str

    def test_real_world_workflow(self):
        """测试真实工作流程"""
        # 1. 初始化分级器（使用默认阈值）
        classifier = SignalClassifier()

        # 2. 采集历史信号数据
        np.random.seed(42)
        historical_signals = list(np.random.randn(5000))

        # 3. 校准阈值
        theta_1, theta_2 = classifier.calibrate_thresholds(historical_signals)
        assert theta_2 < theta_1

        # 4. 对新信号进行分级
        new_signals = [0.8, 0.4, 0.1, -0.6, -0.3, -0.05]
        levels = [classifier.classify(s) for s in new_signals]

        # 5. 统计分布
        stats = classifier.get_statistics(new_signals)

        # 验证工作流程正常
        assert len(levels) == len(new_signals)
        assert stats["total"] == len(new_signals)
        assert stats["high_count"] + stats["medium_count"] + stats["low_count"] == len(
            new_signals
        )
