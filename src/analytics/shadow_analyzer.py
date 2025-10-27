"""影子交易分析器

实时监控和分析影子交易的所有关键指标。
用于验证策略是否满足上线标准。
"""

import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import structlog
from scipy import stats

from src.core.types import SignalScore
from src.execution.shadow_executor import ShadowExecutionRecord
from src.risk.shadow_position_manager import ShadowPositionManager

logger = structlog.get_logger()


@dataclass
class SignalQualityMetrics:
    """信号质量指标"""

    ic: float  # Information Coefficient (Spearman)
    ic_p_value: float  # IC 显著性 p 值
    top_quintile_return: float  # Top 20% 平均收益
    bottom_quintile_return: float  # Bottom 20% 平均收益
    signal_std: float  # 信号标准差
    signal_mean: float  # 信号均值
    sample_size: int  # 样本数量


@dataclass
class ExecutionEfficiencyMetrics:
    """执行效率指标"""

    avg_signal_latency_ms: float  # 平均信号延迟
    avg_decision_latency_ms: float  # 平均决策延迟
    avg_total_latency_ms: float  # 平均总延迟
    p99_total_latency_ms: float  # p99 总延迟
    fill_rate: float  # 成交率 (%)
    partial_fill_rate: float  # 部分成交率 (%)
    avg_slippage_bps: float  # 平均滑点（基点）
    p99_slippage_bps: float  # p99 滑点（基点）
    sample_count: int = 0  # 样本数量（用于延迟告警阈值检查）


@dataclass
class RiskMetrics:
    """风控指标"""

    max_drawdown: Decimal  # 最大回撤
    max_drawdown_pct: float  # 最大回撤百分比
    max_single_loss: Decimal  # 最大单笔亏损
    consecutive_losses: int  # 最大连续亏损次数
    current_drawdown: Decimal  # 当前回撤
    peak_nav: Decimal  # 历史最高 NAV
    sharpe_ratio: float  # 夏普比率（年化）  # 历史最高 NAV


@dataclass
class PnLAttribution:
    """PnL 归因"""

    total_pnl: Decimal
    alpha: Decimal  # 方向性收益
    fee: Decimal  # 手续费
    slippage: Decimal  # 滑点
    alpha_percentage: float  # Alpha 占比 (%)
    cost_percentage: float  # 成本占比 (%)
    num_trades: int
    win_rate: float  # 胜率 (%)


@dataclass
class ShadowTradingReport:
    """影子交易综合报告"""

    signal_quality: SignalQualityMetrics
    execution_efficiency: ExecutionEfficiencyMetrics
    risk_metrics: RiskMetrics
    pnl_attribution: PnLAttribution
    runtime_hours: float
    system_uptime_pct: float
    ready_for_launch: bool  # 改名：meets_launch_criteria → ready_for_launch
    launch_score: float  # 改名：launch_readiness_score → launch_score  # 0-100


class ShadowAnalyzer:
    """影子交易分析器

    职责：
        1. 实时收集和分析所有执行记录
        2. 计算信号质量指标（IC、分层收益）
        3. 计算执行效率指标（延迟、成交率、滑点）
        4. 计算风控指标（回撤、连续亏损）
        5. 进行 PnL 归因分析
        6. 生成综合报告并判断是否满足上线标准
    """

    def __init__(
        self,
        position_manager: ShadowPositionManager,
        initial_nav: Decimal,
        ic_window_hours: int = 1,
        launch_criteria: dict[str, float] | None = None,
    ):
        """
        初始化影子交易分析器

        Args:
            position_manager: 影子持仓管理器
            initial_nav: 初始净值
            ic_window_hours: IC 计算窗口（小时）
            launch_criteria: 上线标准
        """
        self.position_manager = position_manager
        self.initial_nav = initial_nav
        self.ic_window_hours = ic_window_hours

        # 默认上线标准
        self.launch_criteria = launch_criteria or {
            "ic_min": 0.03,
            "alpha_pct_min": 70.0,
            "cost_pct_max": 25.0,
            "uptime_pct_min": 99.9,
            "p99_latency_ms_max": 150.0,
        }

        # 数据收集
        self._execution_records: list[ShadowExecutionRecord] = []
        self._signal_history: deque = deque(
            maxlen=int(ic_window_hours * 3600)
        )  # 最多保留 N 小时

        # 性能指标
        self._peak_nav = initial_nav
        self._max_drawdown = Decimal("0")
        self._max_single_loss = Decimal("0")
        self._consecutive_losses = 0
        self._current_consecutive_losses = 0

        # 系统监控
        self._start_time = time.time()
        self._total_downtime_seconds = 0.0
        
        # NAV 历史（用于计算夏普比率）
        self._nav_history: list[tuple[float, Decimal]] = []  # [(timestamp, nav), ...]

        logger.info(
            "shadow_analyzer_initialized",
            initial_nav=float(initial_nav),
            ic_window_hours=ic_window_hours,
            launch_criteria=self.launch_criteria,
        )

    def record_execution(self, record: ShadowExecutionRecord) -> None:
        """
        记录执行记录

        Args:
            record: 影子执行记录
        """
        self._execution_records.append(record)
        
        # 记录 NAV 历史（用于夏普比率计算）
        current_nav = self.initial_nav + self.position_manager.get_total_pnl()
        self._nav_history.append((time.time(), current_nav))

        # 更新风控指标
        if record.execution_result and not record.skipped:
            # 计算盈亏
            pnl = self._calculate_trade_pnl(record)

            # 更新连续亏损
            if pnl < 0:
                self._current_consecutive_losses += 1
                self._consecutive_losses = max(
                    self._consecutive_losses, self._current_consecutive_losses
                )

                # 更新最大单笔亏损
                if pnl < self._max_single_loss:
                    self._max_single_loss = pnl
            else:
                self._current_consecutive_losses = 0

        logger.debug(
            "execution_recorded",
            order_id=record.order.id,
            skipped=record.skipped,
            filled=record.execution_result is not None,
        )

    def record_signal(self, signal: SignalScore, future_return: float | None = None) -> None:
        """
        记录信号（用于 IC 计算）

        Args:
            signal: 信号评分
            future_return: 未来收益（T+n 收益率，用于计算 IC）
        """
        self._signal_history.append({
            "timestamp": signal.timestamp,
            "signal_value": signal.value,
            "future_return": future_return,
        })

    def calculate_signal_quality(self) -> SignalQualityMetrics:
        """
        计算信号质量指标

        Returns:
            SignalQualityMetrics: 信号质量指标
        """
        # 过滤有未来收益的信号
        valid_signals = [
            s for s in self._signal_history if s.get("future_return") is not None
        ]

        if len(valid_signals) < 30:
            logger.warning(
                "insufficient_signals_for_ic",
                count=len(valid_signals),
                min_required=30,
            )
            return SignalQualityMetrics(
                ic=0.0,
                ic_p_value=1.0,
                top_quintile_return=0.0,
                bottom_quintile_return=0.0,
                signal_std=0.0,
                signal_mean=0.0,
                sample_size=len(valid_signals),
            )

        signals = np.array([s["signal_value"] for s in valid_signals])
        returns = np.array([s["future_return"] for s in valid_signals])

        # 计算 IC (Spearman 相关系数)
        ic, p_value = stats.spearmanr(signals, returns)

        # 分层收益（Top 20% vs Bottom 20%)
        sorted_indices = np.argsort(signals)
        quintile_size = max(1, len(signals) // 5)  # 确保至少有 1 个样本

        if quintile_size > 0 and len(signals) >= 5:
            top_quintile_return = float(np.mean(returns[sorted_indices[-quintile_size:]]))
            bottom_quintile_return = float(
                np.mean(returns[sorted_indices[:quintile_size]])
            )
        else:
            # 样本数量不足，使用全部数据的平均值
            logger.warning(
                "insufficient_signals_for_quintile",
                count=len(signals),
                min_required=5,
            )
            top_quintile_return = float(np.mean(returns))
            bottom_quintile_return = float(np.mean(returns))

        return SignalQualityMetrics(
            ic=float(ic),
            ic_p_value=float(p_value),
            top_quintile_return=top_quintile_return,
            bottom_quintile_return=bottom_quintile_return,
            signal_std=float(np.std(signals)),
            signal_mean=float(np.mean(signals)),
            sample_size=len(valid_signals),
        )

    def calculate_execution_efficiency(self) -> ExecutionEfficiencyMetrics:
        """
        计算执行效率指标

        Returns:
            ExecutionEfficiencyMetrics: 执行效率指标
        """
        if not self._execution_records:
            return ExecutionEfficiencyMetrics(
                avg_signal_latency_ms=0.0,
                avg_decision_latency_ms=0.0,
                avg_total_latency_ms=0.0,
                p99_total_latency_ms=0.0,
                fill_rate=0.0,
                partial_fill_rate=0.0,
                avg_slippage_bps=0.0,
                p99_slippage_bps=0.0,
                sample_count=0,
            )

        # 延迟统计
        total_latencies = [r.total_latency_ms for r in self._execution_records]
        signal_latencies = [r.signal_latency_ms for r in self._execution_records]
        decision_latencies = [r.decision_latency_ms for r in self._execution_records]

        # 成交统计
        filled_records = [
            r for r in self._execution_records if r.fill_result is not None
        ]
        partial_fills = [
            r for r in filled_records if r.fill_result.partial_fill
        ]

        total_orders = len([r for r in self._execution_records if not r.skipped])
        fill_rate = (
            (len(filled_records) / total_orders * 100) if total_orders > 0 else 0.0
        )
        partial_fill_rate = (
            (len(partial_fills) / len(filled_records) * 100)
            if filled_records
            else 0.0
        )

        # 滑点统计
        slippages = [
            r.fill_result.slippage_bps
            for r in filled_records
            if r.fill_result
        ]

        # 计算延迟分位数（先检查是否为空）
        p99_latency = (
            float(np.percentile(total_latencies, 99))
            if total_latencies and len(total_latencies) >= 2
            else 0.0
        )

        # 计算滑点分位数（先检查是否为空）
        p99_slip = (
            float(np.percentile(slippages, 99))
            if slippages and len(slippages) >= 2
            else 0.0
        )

        return ExecutionEfficiencyMetrics(
            avg_signal_latency_ms=float(np.mean(signal_latencies))
            if signal_latencies
            else 0.0,
            avg_decision_latency_ms=float(np.mean(decision_latencies))
            if decision_latencies
            else 0.0,
            avg_total_latency_ms=float(np.mean(total_latencies)) if total_latencies else 0.0,
            p99_total_latency_ms=p99_latency,
            fill_rate=fill_rate,
            partial_fill_rate=partial_fill_rate,
            avg_slippage_bps=float(np.mean(slippages)) if slippages else 0.0,
            p99_slippage_bps=p99_slip,
            sample_count=len(total_latencies),  # 记录样本数量
        )

    def calculate_risk_metrics(self) -> RiskMetrics:
        """
        计算风控指标

        Returns:
            RiskMetrics: 风控指标
        """
        current_nav = self.initial_nav + self.position_manager.get_total_pnl()

        # 更新峰值
        if current_nav > self._peak_nav:
            self._peak_nav = current_nav

        # 当前回撤
        current_drawdown = self._peak_nav - current_nav

        # 最大回撤
        if current_drawdown > self._max_drawdown:
            self._max_drawdown = current_drawdown

        max_drawdown_pct = (
            float(self._max_drawdown / self._peak_nav * Decimal("100"))
            if self._peak_nav > 0
            else 0.0
        )

        # 计算夏普比率
        sharpe_ratio = self._calculate_sharpe_ratio()
        
        return RiskMetrics(
            max_drawdown=self._max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            max_single_loss=self._max_single_loss,
            consecutive_losses=self._consecutive_losses,
            current_drawdown=current_drawdown,
            peak_nav=self._peak_nav,
            sharpe_ratio=sharpe_ratio,
        )

    def _calculate_sharpe_ratio(self) -> float:
        """计算年化夏普比率
        
        夏普比率 = (平均收益率 - 无风险利率) / 收益率标准差 × √(年化因子)
        
        Returns:
            年化夏普比率，无足够数据时返回 0.0
        """
        if len(self._nav_history) < 2:
            return 0.0
        
        # 计算收益率序列
        returns = []
        for i in range(1, len(self._nav_history)):
            prev_nav = self._nav_history[i-1][1]
            curr_nav = self._nav_history[i][1]
            
            if prev_nav > 0:
                ret = float((curr_nav - prev_nav) / prev_nav)
                returns.append(ret)
        
        if not returns:
            return 0.0
        
        # 计算统计量
        mean_return = float(np.mean(returns))
        std_return = float(np.std(returns))
        
        if std_return == 0:
            return 0.0
        
        # 年化因子
        # 假设每次执行间隔约 100ms（高频交易）
        # 每天交易 8 小时 = 8 * 3600 = 28800 秒
        # 每秒约 10 次执行 = 每天 288000 次
        # 一年 252 个交易日
        executions_per_day = 8 * 3600 * 10
        annualization_factor = np.sqrt(executions_per_day * 252)
        
        # 无风险利率假设为 0（加密货币）
        sharpe = mean_return / std_return * annualization_factor
        
        return float(sharpe)

    def calculate_pnl_attribution(self) -> PnLAttribution:
        """
        计算 PnL 归因

        Returns:
            PnLAttribution: PnL 归因
        """
        total_pnl = self.position_manager.get_total_pnl()

        # 统计费用和滑点
        fee_total = Decimal("0")
        slippage_total = Decimal("0")
        num_trades = 0
        wins = 0

        for record in self._execution_records:
            if record.execution_result and not record.skipped:
                num_trades += 1

                # 手续费（Taker 费率 5 bps，负数表示成本）
                fill_value = (
                    record.fill_result.filled_size * record.fill_result.avg_fill_price
                )
                fee_total -= fill_value * Decimal("0.0005")

                # 滑点（负数表示成本）
                slippage_total -= abs(record.fill_result.slippage) * record.fill_result.filled_size

                # 胜率统计
                pnl = self._calculate_trade_pnl(record)
                if pnl > 0:
                    wins += 1

        # Alpha = Total PnL - Fee - Slippage
        # (因为 fee_total 和 slippage_total 已经是负数，所以用减法)
        alpha = total_pnl - fee_total - slippage_total

        # 计算占比（使用绝对值确保语义清晰）
        if total_pnl != 0:
            base = abs(total_pnl)
            alpha_pct = float(alpha / base * Decimal("100"))
            cost_pct = float((fee_total + slippage_total) / base * Decimal("100"))
        else:
            alpha_pct = 0.0
            cost_pct = 0.0

        win_rate = (wins / num_trades * 100) if num_trades > 0 else 0.0

        return PnLAttribution(
            total_pnl=total_pnl,
            alpha=alpha,
            fee=fee_total,
            slippage=slippage_total,
            alpha_percentage=alpha_pct,
            cost_percentage=cost_pct,
            num_trades=num_trades,
            win_rate=win_rate,
        )

    def generate_report(self) -> ShadowTradingReport:
        """
        生成综合报告

        Returns:
            ShadowTradingReport: 综合报告
        """
        signal_quality = self.calculate_signal_quality()
        execution_efficiency = self.calculate_execution_efficiency()
        risk_metrics = self.calculate_risk_metrics()
        pnl_attribution = self.calculate_pnl_attribution()

        # 计算运行时间
        runtime_hours = (time.time() - self._start_time) / 3600
        total_time = time.time() - self._start_time
        uptime_pct = (
            ((total_time - self._total_downtime_seconds) / total_time * 100)
            if total_time > 0
            else 0.0
        )

        # 判断是否满足上线标准
        meets_criteria = self._check_launch_criteria(
            signal_quality, execution_efficiency, risk_metrics, pnl_attribution, uptime_pct
        )

        # 计算准备度评分
        readiness_score = self._calculate_readiness_score(
            signal_quality, execution_efficiency, pnl_attribution, uptime_pct
        )

        return ShadowTradingReport(
            signal_quality=signal_quality,
            execution_efficiency=execution_efficiency,
            risk_metrics=risk_metrics,
            pnl_attribution=pnl_attribution,
            runtime_hours=runtime_hours,
            system_uptime_pct=uptime_pct,
            ready_for_launch=meets_criteria,
            launch_score=readiness_score,
        )

    def _calculate_trade_pnl(self, record: ShadowExecutionRecord) -> Decimal:
        """计算单笔交易盈亏（简化版）"""
        if not record.execution_result:
            return Decimal("0")

        # 这里简化为滑点造成的损失
        # 实际盈亏需要等待平仓才能确定
        return -abs(record.execution_result.slippage) * record.execution_result.fill_size

    def _check_launch_criteria(
        self,
        signal_quality: SignalQualityMetrics,
        execution_efficiency: ExecutionEfficiencyMetrics,
        risk_metrics: RiskMetrics,
        pnl_attribution: PnLAttribution,
        uptime_pct: float,
    ) -> bool:
        """检查是否满足上线标准"""
        checks = {
            "ic": signal_quality.ic >= self.launch_criteria["ic_min"],
            "alpha_pct": pnl_attribution.alpha_percentage
            >= self.launch_criteria["alpha_pct_min"],
            "cost_pct": pnl_attribution.cost_percentage
            <= self.launch_criteria["cost_pct_max"],
            "uptime": uptime_pct >= self.launch_criteria["uptime_pct_min"],
            "latency": execution_efficiency.p99_total_latency_ms
            <= self.launch_criteria["p99_latency_ms_max"],
        }

        logger.info("launch_criteria_check", checks=checks, all_passed=all(checks.values()))

        return all(checks.values())

    def _calculate_readiness_score(
        self,
        signal_quality: SignalQualityMetrics,
        execution_efficiency: ExecutionEfficiencyMetrics,
        pnl_attribution: PnLAttribution,
        uptime_pct: float,
    ) -> float:
        """计算准备度评分（0-100）

        评分规则：
            - IC 评分：0-25 分（IC >= 0.05 满分）
            - Alpha 占比评分：0-25 分（Alpha >= 100% 满分）
            - 延迟评分：0-25 分（p99 <= 100ms 满分）
            - 稳定性评分：0-25 分（在线率 100% 满分）
        """
        scores = []

        # IC 评分（0-25 分），确保非负
        ic_score = max(0, min(signal_quality.ic / 0.05 * 25, 25))
        scores.append(ic_score)

        # Alpha 占比评分（0-25 分），确保非负
        alpha_score = max(0, min(pnl_attribution.alpha_percentage / 100 * 25, 25))
        scores.append(alpha_score)

        # 延迟评分（0-25 分），确保非负
        latency_score = max(
            0, min(25 - (execution_efficiency.p99_total_latency_ms - 100) / 10, 25)
        )
        scores.append(latency_score)

        # 稳定性评分（0-25 分），确保非负
        uptime_score = max(0, min(uptime_pct / 100 * 25, 25))
        scores.append(uptime_score)

        return sum(scores)
