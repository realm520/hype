"""指标收集器

收集和聚合系统性能指标。
"""

import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

import numpy as np
import structlog
from scipy import stats

from src.core.types import ConfidenceLevel, Order, OrderStatus, SignalScore

logger = structlog.get_logger()


@dataclass
class SignalRecord:
    """信号记录"""

    timestamp: int
    symbol: str
    signal_value: float
    confidence: str
    actual_return: float | None = None  # 实际收益率（事后填充）


@dataclass
class ExecutionRecord:
    """执行记录"""

    timestamp: int
    symbol: str
    order_id: str
    side: str
    size: Decimal
    price: Decimal
    slippage_bps: float
    latency_ms: float
    status: str


class MetricsCollector:
    """指标收集器

    职责：
        1. 收集信号、执行、风控指标
        2. 计算 IC（信息系数）
        3. 聚合统计数据
        4. 生成指标报告
    """

    def __init__(
        self,
        ic_window: int = 100,  # IC 计算窗口
        metrics_history: int = 10000,  # 指标历史容量
    ):
        """
        初始化指标收集器

        Args:
            ic_window: IC 计算窗口大小
            metrics_history: 指标历史记录数
        """
        self.ic_window = ic_window
        self.metrics_history = metrics_history

        # 信号记录
        self._signal_records: deque = deque(maxlen=metrics_history)

        # 执行记录
        self._execution_records: deque = deque(maxlen=metrics_history)

        # 延迟统计（毫秒）
        self._latencies: deque = deque(maxlen=1000)

        # 信号命中统计
        self._signal_hits = 0  # 信号方向正确
        self._signal_total = 0  # 总信号数

        logger.info(
            "metrics_collector_initialized",
            ic_window=ic_window,
            metrics_history=metrics_history,
        )

    def record_signal(
        self,
        signal_score: SignalScore,
        symbol: str,
        actual_return: float | None = None,
    ) -> None:
        """
        记录信号

        Args:
            signal_score: 信号评分
            symbol: 交易对
            actual_return: 实际收益率（可选，事后填充）
        """
        record = SignalRecord(
            timestamp=signal_score.timestamp,
            symbol=symbol,
            signal_value=signal_score.value,
            confidence=signal_score.confidence.name,
            actual_return=actual_return,
        )

        self._signal_records.append(record)

        # 更新命中统计
        if actual_return is not None:
            self._signal_total += 1
            if (signal_score.value > 0 and actual_return > 0) or (
                signal_score.value < 0 and actual_return < 0
            ):
                self._signal_hits += 1

        logger.debug(
            "signal_recorded",
            symbol=symbol,
            signal_value=signal_score.value,
            confidence=signal_score.confidence.name,
        )

    def record_execution(
        self,
        order: Order,
        slippage_bps: float,
        latency_ms: float,
    ) -> None:
        """
        记录执行

        Args:
            order: 订单对象
            slippage_bps: 滑点（基点）
            latency_ms: 执行延迟（毫秒）
        """
        record = ExecutionRecord(
            timestamp=order.created_at,
            symbol=order.symbol,
            order_id=order.id,
            side=order.side.name,
            size=order.size,
            price=order.price,
            slippage_bps=slippage_bps,
            latency_ms=latency_ms,
            status=order.status.name,
        )

        self._execution_records.append(record)
        self._latencies.append(latency_ms)

        logger.debug(
            "execution_recorded",
            order_id=order.id,
            symbol=order.symbol,
            slippage_bps=slippage_bps,
            latency_ms=latency_ms,
        )

    def calculate_ic(self) -> float | None:
        """
        计算信息系数（IC）

        使用 Spearman 秩相关计算信号与实际收益的相关性。

        Returns:
            Optional[float]: IC 值，如果数据不足返回 None
        """
        # 获取最近窗口内有实际收益的信号
        valid_records = [
            r for r in list(self._signal_records)[-self.ic_window :]
            if r.actual_return is not None
        ]

        if len(valid_records) < 10:  # 最少需要10个样本
            logger.debug("ic_calculation_skipped_insufficient_data", count=len(valid_records))
            return None

        # 提取信号值和实际收益
        signals = [r.signal_value for r in valid_records]
        returns = [r.actual_return for r in valid_records]

        # 计算 Spearman 秩相关
        try:
            correlation, p_value = stats.spearmanr(signals, returns)

            logger.info(
                "ic_calculated",
                ic=correlation,
                p_value=p_value,
                sample_size=len(valid_records),
            )

            return cast(float, correlation)

        except Exception as e:
            logger.error("ic_calculation_error", error=str(e), exc_info=True)
            return None

    def get_signal_metrics(self) -> dict:
        """
        获取信号质量指标

        Returns:
            dict: 信号指标
        """
        ic = self.calculate_ic()

        # 计算命中率
        hit_rate = (
            self._signal_hits / self._signal_total if self._signal_total > 0 else 0.0
        )

        # 统计置信度分布
        confidence_counts: dict[ConfidenceLevel, int] = {}
        for record in self._signal_records:
            confidence = record.confidence
            confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1

        return {
            "ic": ic,
            "hit_rate": hit_rate,
            "total_signals": self._signal_total,
            "signal_hits": self._signal_hits,
            "confidence_distribution": confidence_counts,
        }

    def get_execution_metrics(self) -> dict:
        """
        获取执行质量指标

        Returns:
            dict: 执行指标
        """
        if not self._execution_records:
            return {
                "total_orders": 0,
                "avg_slippage_bps": 0.0,
                "avg_latency_ms": 0.0,
                "success_rate": 0.0,
            }

        # 计算平均滑点
        slippages = [r.slippage_bps for r in self._execution_records]
        avg_slippage = sum(slippages) / len(slippages) if slippages else 0.0

        # 计算成功率
        total_orders = len(self._execution_records)
        successful_orders = sum(
            1 for r in self._execution_records if r.status == OrderStatus.FILLED.name
        )
        success_rate = successful_orders / total_orders if total_orders > 0 else 0.0

        # 延迟统计（直接使用 deque，避免不必要的 list 转换）
        if self._latencies and len(self._latencies) >= 2:
            # 至少需要2个样本才能计算分位数
            avg_latency = sum(self._latencies) / len(self._latencies)
            percentiles = np.percentile(list(self._latencies), [50, 95, 99])
            p50, p95, p99 = float(percentiles[0]), float(percentiles[1]), float(percentiles[2])
        else:
            avg_latency = 0.0
            p50, p95, p99 = 0.0, 0.0, 0.0

        return {
            "total_orders": total_orders,
            "successful_orders": successful_orders,
            "avg_slippage_bps": avg_slippage,
            "avg_latency_ms": avg_latency,
            "success_rate": success_rate,
            "latency_p50": p50,
            "latency_p95": p95,
            "latency_p99": p99,
        }

    def get_metrics_summary(self, risk_status: dict | None = None) -> dict:
        """
        生成指标摘要

        Args:
            risk_status: 风控状态（可选）

        Returns:
            dict: 指标摘要
        """
        signal_metrics = self.get_signal_metrics()
        execution_metrics = self.get_execution_metrics()

        summary = {
            "timestamp": int(time.time() * 1000),
            "signal_quality": signal_metrics,
            "execution_quality": execution_metrics,
        }

        # 添加风控状态
        if risk_status:
            summary["risk_status"] = risk_status

        return summary

    def get_ic_stats(self) -> dict:
        """
        获取 IC 统计信息（供 AlphaHealthChecker 使用）

        计算信号值与实际收益的 Spearman 相关性。

        Returns:
            dict: IC 统计信息
                - ic: float - 信息系数（Spearman 相关性）
                - p_value: float - 显著性 p 值
                - sample_size: int - 样本数量
        """
        # 筛选有效记录（有实际收益的记录）
        valid_records = [
            r
            for r in list(self._signal_records)[-self.ic_window :]
            if r.actual_return is not None
        ]

        # 样本数不足
        if len(valid_records) < 10:
            return {"ic": 0.0, "p_value": 1.0, "sample_size": len(valid_records)}

        # 提取信号值和实际收益
        signals = [r.signal_value for r in valid_records]
        returns = [r.actual_return for r in valid_records]

        # 计算 Spearman 相关性
        try:
            correlation, p_value = stats.spearmanr(signals, returns)
            return {
                "ic": float(correlation) if not np.isnan(correlation) else 0.0,
                "p_value": float(p_value) if not np.isnan(p_value) else 1.0,
                "sample_size": len(valid_records),
            }
        except Exception:
            return {"ic": 0.0, "p_value": 1.0, "sample_size": len(valid_records)}

    def get_recent_signals(self, n: int = 10) -> list[SignalRecord]:
        """
        获取最近 N 个信号记录

        Args:
            n: 记录数量

        Returns:
            List[SignalRecord]: 信号记录列表（最新在前）
        """
        records = list(self._signal_records)
        records.reverse()
        return records[:n]

    def get_recent_executions(self, n: int = 10) -> list[ExecutionRecord]:
        """
        获取最近 N 个执行记录

        Args:
            n: 记录数量

        Returns:
            List[ExecutionRecord]: 执行记录列表（最新在前）
        """
        records = list(self._execution_records)
        records.reverse()
        return records[:n]

    def __repr__(self) -> str:
        signal_metrics = self.get_signal_metrics()
        execution_metrics = self.get_execution_metrics()

        return (
            f"MetricsCollector("
            f"IC={signal_metrics.get('ic', 0):.3f}, "
            f"hit_rate={signal_metrics['hit_rate']*100:.1f}%, "
            f"avg_latency={execution_metrics['avg_latency_ms']:.1f}ms)"
        )
