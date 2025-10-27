"""信号聚合器

聚合多个信号生成最终交易信号，并计算置信度。
"""

import time

import structlog

from src.core.types import ConfidenceLevel, MarketData, SignalScore
from src.signals.base import BaseSignal

logger = structlog.get_logger()


class SignalAggregator:
    """信号聚合器

    聚合多个信号生成最终交易信号，根据信号强度分配置信度等级。

    置信度分级：
        - HIGH: |signal| > theta_1（强信号，执行 IOC）
        - MEDIUM: theta_2 < |signal| ≤ theta_1（中等信号，观察）
        - LOW: |signal| ≤ theta_2（弱信号，跳过）

    聚合方式：
        WeightedSignal = Σ(signal_i * weight_i) / Σ(weight_i)
    """

    def __init__(
        self,
        signals: list[BaseSignal],
        theta_1: float = 0.5,
        theta_2: float = 0.2,
    ):
        """
        初始化信号聚合器

        Args:
            signals: 信号列表
            theta_1: 高置信度阈值（默认 0.5）
            theta_2: 中置信度阈值（默认 0.2）
        """
        self.signals = signals
        self.theta_1 = theta_1
        self.theta_2 = theta_2

        # 验证信号
        for signal in self.signals:
            if not signal.validate():
                raise ValueError(f"Invalid signal configuration: {signal}")

        logger.info(
            "signal_aggregator_initialized",
            signals_count=len(signals),
            signal_types=[type(s).__name__ for s in signals],
            theta_1=theta_1,
            theta_2=theta_2,
        )

    def calculate(self, market_data: MarketData) -> SignalScore:
        """
        计算聚合信号

        Args:
            market_data: 市场数据

        Returns:
            SignalScore: 信号评分对象
        """
        start_time = time.time()

        try:
            # 计算所有子信号
            individual_scores: list[float] = []
            weighted_sum = 0.0
            weight_sum = 0.0

            for signal in self.signals:
                try:
                    score = signal.calculate(market_data)
                    weight = signal.get_weight()

                    individual_scores.append(score)
                    weighted_sum += score * weight
                    weight_sum += weight

                    logger.debug(
                        "individual_signal_calculated",
                        signal_type=type(signal).__name__,
                        score=score,
                        weight=weight,
                    )

                except Exception as e:
                    logger.error(
                        "individual_signal_error",
                        signal_type=type(signal).__name__,
                        error=str(e),
                        exc_info=True,
                    )
                    # 出错的信号贡献 0 分
                    individual_scores.append(0.0)

            # 计算加权平均
            if weight_sum == 0:
                logger.warning(
                    "zero_weight_sum",
                    symbol=market_data.symbol,
                )
                aggregated_value = 0.0
            else:
                aggregated_value = weighted_sum / weight_sum

            # 确定置信度等级
            confidence = self._determine_confidence(aggregated_value)

            # 创建 SignalScore 对象
            # 使用实时时间戳，避免使用可能过时的 market_data.timestamp
            signal_score = SignalScore(
                value=aggregated_value,
                confidence=confidence,
                individual_scores=individual_scores,
                timestamp=int(time.time() * 1000),
            )

            # 监控性能
            latency_ms = (time.time() - start_time) * 1000
            if latency_ms > 5.0:
                logger.warning(
                    "aggregator_calculation_slow",
                    symbol=market_data.symbol,
                    latency_ms=latency_ms,
                )

            logger.info(
                "signal_aggregated",
                symbol=market_data.symbol,
                value=aggregated_value,
                confidence=confidence.name,
                individual_scores=individual_scores,
                latency_ms=latency_ms,
            )

            return signal_score

        except Exception as e:
            logger.error(
                "aggregator_calculation_error",
                symbol=market_data.symbol,
                error=str(e),
                exc_info=True,
            )

            # 返回零信号
            # 使用实时时间戳，避免使用可能过时的 market_data.timestamp
            return SignalScore(
                value=0.0,
                confidence=ConfidenceLevel.LOW,
                individual_scores=[0.0] * len(self.signals),
                timestamp=int(time.time() * 1000),
            )

    def _determine_confidence(self, signal_value: float) -> ConfidenceLevel:
        """
        根据信号值确定置信度等级

        Args:
            signal_value: 信号值

        Returns:
            ConfidenceLevel: 置信度等级
        """
        abs_value = abs(signal_value)

        if abs_value > self.theta_1:
            return ConfidenceLevel.HIGH
        elif abs_value > self.theta_2:
            return ConfidenceLevel.MEDIUM
        else:
            return ConfidenceLevel.LOW

    def get_signal_weights(self) -> dict[str, float]:
        """
        获取所有信号的权重

        Returns:
            dict[str, float]: 信号类型到权重的映射
        """
        return {type(signal).__name__: signal.get_weight() for signal in self.signals}

    def validate_thresholds(self) -> bool:
        """
        验证阈值配置

        Returns:
            bool: 阈值配置是否有效
        """
        if self.theta_1 <= self.theta_2:
            logger.error(
                "invalid_thresholds",
                theta_1=self.theta_1,
                theta_2=self.theta_2,
                reason="theta_1 must be greater than theta_2",
            )
            return False

        if self.theta_1 > 1.0 or self.theta_1 < 0:
            logger.error(
                "invalid_theta_1",
                theta_1=self.theta_1,
                reason="theta_1 must be in range [0, 1]",
            )
            return False

        if self.theta_2 > 1.0 or self.theta_2 < 0:
            logger.error(
                "invalid_theta_2",
                theta_2=self.theta_2,
                reason="theta_2 must be in range [0, 1]",
            )
            return False

        return True

    def __repr__(self) -> str:
        return (
            f"SignalAggregator(signals={len(self.signals)}, "
            f"theta_1={self.theta_1}, theta_2={self.theta_2})"
        )


def create_aggregator_from_config(config: dict) -> SignalAggregator:
    """
    从配置创建信号聚合器

    Args:
        config: 配置字典，应包含 signals 和 thresholds 部分

    Returns:
        SignalAggregator: 信号聚合器实例

    示例配置：
        {
            "signals": {
                "obi": {"levels": 5, "weight": 0.4},
                "microprice": {"weight": 0.3},
                "impact": {"window_ms": 100, "weight": 0.3}
            },
            "thresholds": {
                "theta_1": 0.5,
                "theta_2": 0.2
            }
        }
    """
    from src.signals.impact import ImpactSignal
    from src.signals.microprice import MicropriceSignal
    from src.signals.obi import OBISignal

    signals_config = config.get("signals", {})
    thresholds_config = config.get("thresholds", {})

    # 创建信号实例
    signals: list[BaseSignal] = []

    # OBI 信号
    if "obi" in signals_config:
        obi_config = signals_config["obi"]
        signals.append(
            OBISignal(
                levels=obi_config.get("levels", 5),
                weight=obi_config.get("weight", 0.4),
            )
        )

    # Microprice 信号
    if "microprice" in signals_config:
        microprice_config = signals_config["microprice"]
        signals.append(
            MicropriceSignal(
                weight=microprice_config.get("weight", 0.3),
            )
        )

    # Impact 信号
    if "impact" in signals_config:
        impact_config = signals_config["impact"]
        signals.append(
            ImpactSignal(
                window_ms=impact_config.get("window_ms", 100),
                weight=impact_config.get("weight", 0.3),
            )
        )

    # 创建聚合器
    aggregator = SignalAggregator(
        signals=signals,
        theta_1=thresholds_config.get("theta_1", 0.5),
        theta_2=thresholds_config.get("theta_2", 0.2),
    )

    # 验证配置
    if not aggregator.validate_thresholds():
        raise ValueError("Invalid aggregator thresholds configuration")

    logger.info(
        "aggregator_created_from_config",
        signals_count=len(signals),
        theta_1=aggregator.theta_1,
        theta_2=aggregator.theta_2,
    )

    return aggregator
