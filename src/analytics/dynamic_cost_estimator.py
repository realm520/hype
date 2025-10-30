"""动态成本估算器

提供 Maker/Taker 混合策略的动态成本估算和跟踪功能。

核心功能：
    1. 事前成本估算：根据订单类型、市场状况预测成本
    2. 事后成本跟踪：记录实际成本，计算估算偏差
    3. 成本分解：Fee / Slippage / Impact 三维度分析
    4. 成本预测准确性验证：估算误差 < 20%

成本计算公式：
    - Maker 成本 = Fee（1.5 bps） + Slip（≈0 bps）+ Impact（1-2 bps）
    - Taker 成本 = Fee（4.5 bps） + Slip（2-3 bps） + Impact（1-2 bps）
    - 总成本 = Fee + Slippage + Impact

设计原则：
    - 复用 SlippageEstimator 进行滑点估算
    - 基于市场状态（流动性、波动率）动态调整冲击估算
    - 支持历史数据回测和实盘运行
"""

import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal

import structlog

from src.core.constants import HYPERLIQUID_MAKER_FEE_RATE, HYPERLIQUID_TAKER_FEE_RATE
from src.core.types import MarketData, Order, OrderSide, OrderType
from src.execution.slippage_estimator import SlippageEstimator

logger = structlog.get_logger()


@dataclass
class CostEstimate:
    """成本估算结果（事前预测）"""

    order_type: OrderType  # LIMIT (Maker) / IOC (Taker)
    side: OrderSide
    size: Decimal
    symbol: str

    # 成本分解（bps）
    fee_bps: float  # 1.5 (Maker) or 4.5 (Taker)
    slippage_bps: float  # 基于订单簿深度估算
    impact_bps: float  # 基于市场状态估算

    # 总成本
    total_cost_bps: float  # fee + slip + impact

    # 市场状态（用于动态调整）
    spread_bps: float  # 买卖价差
    liquidity_score: float  # 0-1，越高流动性越好
    volatility_score: float  # 0-1，越高波动越大

    timestamp: int

    def __repr__(self) -> str:
        return (
            f"CostEstimate({self.order_type.name} {self.side.name}, "
            f"total={self.total_cost_bps:.2f} bps "
            f"[fee={self.fee_bps:.2f} + slip={self.slippage_bps:.2f} + "
            f"impact={self.impact_bps:.2f}])"
        )


@dataclass
class CostActual:
    """实际成本记录（事后验证）"""

    order_id: str
    order_type: OrderType
    side: OrderSide
    size: Decimal
    symbol: str

    # 实际成本（bps）
    fee_bps: float
    slippage_bps: float
    impact_bps: float
    total_cost_bps: float

    # 估算成本（用于对比）
    estimated_total_bps: float
    estimation_error_pct: float  # (actual - estimated) / estimated * 100

    timestamp: int

    def __repr__(self) -> str:
        return (
            f"CostActual({self.order_type.name}, "
            f"actual={self.total_cost_bps:.2f} bps, "
            f"estimated={self.estimated_total_bps:.2f} bps, "
            f"error={self.estimation_error_pct:.1f}%)"
        )


@dataclass
class CostStats:
    """成本统计（按时间窗口/交易对）"""

    # 平均成本（bps）
    avg_fee_bps: float
    avg_slippage_bps: float
    avg_impact_bps: float
    avg_total_bps: float

    # Maker/Taker 分布
    maker_ratio: float  # 0-1
    taker_ratio: float  # 0-1

    # 估算准确性
    avg_estimation_error_pct: float  # 平均误差（%）
    estimation_error_std: float  # 误差标准差

    # 样本统计
    num_trades: int
    time_window: str  # "1h" / "24h" / "7d"
    symbol: str | None = None  # None = 全部交易对

    def __repr__(self) -> str:
        symbol_str = f"{self.symbol} " if self.symbol else ""
        return (
            f"CostStats({symbol_str}{self.time_window}, "
            f"n={self.num_trades}, "
            f"avg_cost={self.avg_total_bps:.2f} bps, "
            f"maker={self.maker_ratio:.1%}, "
            f"error={self.avg_estimation_error_pct:.1f}%)"
        )


class DynamicCostEstimator:
    """动态成本估算器

    支持 Maker/Taker 混合策略的成本估算和跟踪。

    核心方法：
        - estimate_cost(): 事前成本估算
        - record_actual_cost(): 事后成本跟踪
        - get_cost_stats(): 成本统计分析
        - get_estimation_accuracy(): 估算准确性报告

    性能指标：
        - 单次估算延迟 < 5ms
        - 内存占用 < 100MB（10000 条记录）
        - 估算准确性：误差 < 20%
    """

    def __init__(
        self,
        maker_fee_rate: Decimal = HYPERLIQUID_MAKER_FEE_RATE,
        taker_fee_rate: Decimal = HYPERLIQUID_TAKER_FEE_RATE,
        slippage_estimator: SlippageEstimator | None = None,
        impact_model: str = "linear",
        impact_alpha: float = 0.01,
        max_history: int = 10000,
    ):
        """
        初始化动态成本估算器

        Args:
            maker_fee_rate: Maker 费率（默认 1.5 bps）
            taker_fee_rate: Taker 费率（默认 4.5 bps）
            slippage_estimator: 滑点估算器（如果为 None 则创建默认实例）
            impact_model: 冲击模型类型（"linear" / "sqrt" / "adaptive"）
            impact_alpha: 冲击模型参数（线性模型系数）
            max_history: 最大历史记录数
        """
        self.maker_fee_rate = maker_fee_rate
        self.taker_fee_rate = taker_fee_rate
        self.slippage_estimator = slippage_estimator or SlippageEstimator()
        self.impact_model = impact_model
        self.impact_alpha = impact_alpha
        self.max_history = max_history

        # 估算历史（用于验证准确性）
        self._estimation_history: deque[CostEstimate] = deque(maxlen=max_history)

        # 实际成本历史（用于统计分析）
        self._actual_history: deque[CostActual] = deque(maxlen=max_history)

        # 成本估算缓存（order_id -> CostEstimate）
        self._estimate_cache: dict[str, CostEstimate] = {}

        logger.info(
            "dynamic_cost_estimator_initialized",
            maker_fee_rate=float(maker_fee_rate),
            taker_fee_rate=float(taker_fee_rate),
            impact_model=impact_model,
            impact_alpha=impact_alpha,
            max_history=max_history,
        )

    def estimate_cost(
        self,
        order_type: OrderType,
        side: OrderSide,
        size: Decimal,
        market_data: MarketData,
    ) -> CostEstimate:
        """
        估算订单成本（事前预测）

        流程：
            1. 计算 Fee（根据 order_type）
            2. 估算 Slippage（复用 SlippageEstimator）
            3. 估算 Impact（基于市场状态动态调整）
            4. 计算市场状态（流动性、波动率、价差）
            5. 汇总总成本

        Args:
            order_type: 订单类型（LIMIT = Maker, IOC = Taker）
            side: 订单方向
            size: 订单大小
            market_data: 市场数据（订单簿快照）

        Returns:
            CostEstimate: 成本估算结果

        性能：
            - 平均延迟 < 5ms
            - 无 I/O 操作，纯内存计算
        """
        try:
            timestamp = int(time.time() * 1000)

            # 1. 计算手续费（bps）
            fee_bps = self._estimate_fee_bps(order_type, size, market_data.mid_price)

            # 2. 估算滑点（bps）
            slippage_bps = self._estimate_slippage_bps(side, size, market_data)

            # 3. 计算市场状态
            market_state = self._calculate_market_state(market_data)

            # 4. 估算市场冲击（bps）
            impact_bps = self._estimate_impact_bps(
                side, size, market_data, market_state
            )

            # 5. 汇总总成本
            total_cost_bps = fee_bps + slippage_bps + impact_bps

            # 6. 创建估算结果
            estimate = CostEstimate(
                order_type=order_type,
                side=side,
                size=size,
                symbol=market_data.symbol,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                impact_bps=impact_bps,
                total_cost_bps=total_cost_bps,
                spread_bps=market_state["spread_bps"],
                liquidity_score=market_state["liquidity_score"],
                volatility_score=market_state["volatility_score"],
                timestamp=timestamp,
            )

            # 7. 记录到历史
            self._estimation_history.append(estimate)

            logger.debug(
                "cost_estimated",
                symbol=market_data.symbol,
                order_type=order_type.name,
                side=side.name,
                size=float(size),
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                impact_bps=impact_bps,
                total_cost_bps=total_cost_bps,
            )

            return estimate

        except Exception as e:
            logger.error(
                "cost_estimation_error",
                symbol=market_data.symbol,
                order_type=order_type.name,
                side=side.name,
                error=str(e),
                exc_info=True,
            )
            raise

    def record_actual_cost(
        self,
        order: Order,
        estimated_cost: CostEstimate,
        actual_fill_price: Decimal,
        reference_price: Decimal,
        best_price: Decimal,
    ) -> CostActual:
        """
        记录实际成本（事后验证）

        流程：
            1. 计算实际 Fee（基于 order.order_type 和 filled_size）
            2. 计算实际 Slippage（actual_fill_price - reference_price）
            3. 计算实际 Impact（actual_fill_price - best_price）
            4. 计算估算误差
            5. 更新历史统计

        Args:
            order: 订单对象（包含 filled_size 等实际执行信息）
            estimated_cost: 事前的成本估算
            actual_fill_price: 实际成交价
            reference_price: 参考价（通常是信号时刻的中间价）
            best_price: 最优价（下单时的 best_bid/best_ask）

        Returns:
            CostActual: 实际成本记录

        注意：
            - reference_price 用于计算 Slippage（相对于预期价格）
            - best_price 用于计算 Impact（相对于最优价）
            - 通常 best_price ≈ reference_price（如果下单及时）
        """
        try:
            timestamp = int(time.time() * 1000)

            # 1. 计算实际手续费（bps）
            trade_value = order.filled_size * actual_fill_price
            if trade_value == 0:
                logger.warning(
                    "actual_cost_zero_trade_value",
                    order_id=order.id,
                    filled_size=float(order.filled_size),
                )
                # 返回零成本记录
                return CostActual(
                    order_id=order.id,
                    order_type=order.order_type,
                    side=order.side,
                    size=order.filled_size,
                    symbol=order.symbol,
                    fee_bps=0.0,
                    slippage_bps=0.0,
                    impact_bps=0.0,
                    total_cost_bps=0.0,
                    estimated_total_bps=estimated_cost.total_cost_bps,
                    estimation_error_pct=0.0,
                    timestamp=timestamp,
                )

            fee_rate = (
                self.maker_fee_rate
                if order.order_type == OrderType.LIMIT
                else self.taker_fee_rate
            )
            actual_fee = trade_value * fee_rate
            fee_bps = float(actual_fee / trade_value * 10000)

            # 2. 计算实际滑点（bps）
            slippage_bps = self.slippage_estimator.calculate_actual_slippage(
                actual_fill_price, reference_price, order.side
            )

            # 3. 计算实际市场冲击（bps）
            # Impact = 实际成交价 - 最优价（归因为市场冲击）
            if best_price == 0:
                impact_bps = 0.0
            else:
                price_diff = actual_fill_price - best_price
                if order.side == OrderSide.SELL:
                    price_diff = -price_diff
                impact_bps = float(price_diff / best_price * 10000)

            # 4. 汇总实际总成本
            total_cost_bps = fee_bps + slippage_bps + impact_bps

            # 5. 计算估算误差（%）
            if estimated_cost.total_cost_bps != 0:
                estimation_error_pct = (
                    (total_cost_bps - estimated_cost.total_cost_bps)
                    / estimated_cost.total_cost_bps
                    * 100
                )
            else:
                estimation_error_pct = 0.0 if total_cost_bps == 0 else float("inf")

            # 6. 创建实际成本记录
            actual_cost = CostActual(
                order_id=order.id,
                order_type=order.order_type,
                side=order.side,
                size=order.filled_size,
                symbol=order.symbol,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                impact_bps=impact_bps,
                total_cost_bps=total_cost_bps,
                estimated_total_bps=estimated_cost.total_cost_bps,
                estimation_error_pct=estimation_error_pct,
                timestamp=timestamp,
            )

            # 7. 记录到历史
            self._actual_history.append(actual_cost)

            # 8. 清理估算缓存
            if order.id in self._estimate_cache:
                del self._estimate_cache[order.id]

            logger.debug(
                "actual_cost_recorded",
                order_id=order.id,
                symbol=order.symbol,
                order_type=order.order_type.name,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                impact_bps=impact_bps,
                total_cost_bps=total_cost_bps,
                estimated_bps=estimated_cost.total_cost_bps,
                error_pct=estimation_error_pct,
            )

            return actual_cost

        except Exception as e:
            logger.error(
                "actual_cost_recording_error",
                order_id=order.id,
                symbol=order.symbol,
                error=str(e),
                exc_info=True,
            )
            raise

    def get_cost_stats(
        self,
        symbol: str | None = None,
        time_window: str = "24h",
    ) -> CostStats | None:
        """
        获取成本统计（按交易对/时间窗口）

        Args:
            symbol: 交易对（None = 全部交易对）
            time_window: 时间窗口（"1h" / "24h" / "7d"）

        Returns:
            CostStats: 成本统计数据，如果没有数据则返回 None
        """
        # 解析时间窗口（转换为秒）
        window_seconds = {
            "1h": 3600,
            "24h": 86400,
            "7d": 604800,
        }.get(time_window, 86400)

        # 获取时间窗口内的记录
        current_time = int(time.time() * 1000)
        cutoff_time = current_time - window_seconds * 1000

        # 过滤记录
        filtered_records = [
            record
            for record in self._actual_history
            if record.timestamp >= cutoff_time
            and (symbol is None or record.symbol == symbol)
        ]

        if not filtered_records:
            logger.debug(
                "cost_stats_no_data",
                symbol=symbol,
                time_window=time_window,
            )
            return None

        # 统计 Maker/Taker 分布
        maker_count = sum(
            1 for r in filtered_records if r.order_type == OrderType.LIMIT
        )
        taker_count = sum(1 for r in filtered_records if r.order_type == OrderType.IOC)
        total_count = len(filtered_records)

        maker_ratio = maker_count / total_count if total_count > 0 else 0.0
        taker_ratio = taker_count / total_count if total_count > 0 else 0.0

        # 计算平均成本
        avg_fee = sum(r.fee_bps for r in filtered_records) / total_count
        avg_slippage = sum(r.slippage_bps for r in filtered_records) / total_count
        avg_impact = sum(r.impact_bps for r in filtered_records) / total_count
        avg_total = sum(r.total_cost_bps for r in filtered_records) / total_count

        # 计算估算误差统计
        errors = [r.estimation_error_pct for r in filtered_records if not float("inf") == r.estimation_error_pct]
        avg_error = sum(errors) / len(errors) if errors else 0.0

        # 计算标准差
        if len(errors) > 1:
            mean = avg_error
            variance = sum((e - mean) ** 2 for e in errors) / len(errors)
            error_std = variance**0.5
        else:
            error_std = 0.0

        stats = CostStats(
            avg_fee_bps=avg_fee,
            avg_slippage_bps=avg_slippage,
            avg_impact_bps=avg_impact,
            avg_total_bps=avg_total,
            maker_ratio=maker_ratio,
            taker_ratio=taker_ratio,
            avg_estimation_error_pct=avg_error,
            estimation_error_std=error_std,
            num_trades=total_count,
            time_window=time_window,
            symbol=symbol,
        )

        logger.debug(
            "cost_stats_calculated",
            symbol=symbol,
            time_window=time_window,
            num_trades=total_count,
            avg_total_bps=avg_total,
            maker_ratio=maker_ratio,
        )

        return stats

    def get_estimation_accuracy(self) -> dict:
        """
        获取估算准确性报告

        Returns:
            dict: {
                "avg_error_pct": 平均误差（%），
                "error_std": 误差标准差，
                "mae": 平均绝对误差（bps），
                "rmse": 均方根误差（bps），
                "within_10pct": 误差 < 10% 的比例，
                "within_20pct": 误差 < 20% 的比例，
                "num_samples": 样本数量，
            }
        """
        if not self._actual_history:
            return {
                "avg_error_pct": 0.0,
                "error_std": 0.0,
                "mae": 0.0,
                "rmse": 0.0,
                "within_10pct": 0.0,
                "within_20pct": 0.0,
                "num_samples": 0,
            }

        # 过滤掉无穷大误差的记录
        valid_records = [
            r for r in self._actual_history if not float("inf") == r.estimation_error_pct
        ]

        if not valid_records:
            return {
                "avg_error_pct": 0.0,
                "error_std": 0.0,
                "mae": 0.0,
                "rmse": 0.0,
                "within_10pct": 0.0,
                "within_20pct": 0.0,
                "num_samples": 0,
            }

        # 计算平均误差
        errors = [r.estimation_error_pct for r in valid_records]
        avg_error = sum(errors) / len(errors)

        # 计算标准差
        variance = sum((e - avg_error) ** 2 for e in errors) / len(errors)
        error_std = variance**0.5

        # 计算 MAE（平均绝对误差，bps）
        absolute_errors = [
            abs(r.total_cost_bps - r.estimated_total_bps) for r in valid_records
        ]
        mae = sum(absolute_errors) / len(absolute_errors)

        # 计算 RMSE（均方根误差，bps）
        squared_errors = [
            (r.total_cost_bps - r.estimated_total_bps) ** 2 for r in valid_records
        ]
        rmse = (sum(squared_errors) / len(squared_errors)) ** 0.5

        # 计算误差分布
        within_10pct = sum(1 for e in errors if abs(e) < 10) / len(errors)
        within_20pct = sum(1 for e in errors if abs(e) < 20) / len(errors)

        accuracy_report = {
            "avg_error_pct": avg_error,
            "error_std": error_std,
            "mae": mae,
            "rmse": rmse,
            "within_10pct": within_10pct,
            "within_20pct": within_20pct,
            "num_samples": len(valid_records),
        }

        logger.info(
            "estimation_accuracy_calculated",
            num_samples=len(valid_records),
            avg_error_pct=avg_error,
            mae=mae,
            within_20pct=within_20pct,
        )

        return accuracy_report

    def _estimate_fee_bps(
        self, order_type: OrderType, size: Decimal, price: Decimal
    ) -> float:
        """
        计算手续费（bps）

        Args:
            order_type: 订单类型（LIMIT = Maker, IOC = Taker）
            size: 订单大小
            price: 参考价格

        Returns:
            float: 手续费（bps）
        """
        fee_rate = (
            self.maker_fee_rate if order_type == OrderType.LIMIT else self.taker_fee_rate
        )
        return float(fee_rate * 10000)

    def _estimate_slippage_bps(
        self, side: OrderSide, size: Decimal, market_data: MarketData
    ) -> float:
        """
        估算滑点（bps）

        复用 SlippageEstimator 进行估算。

        Args:
            side: 订单方向
            size: 订单大小
            market_data: 市场数据

        Returns:
            float: 滑点（bps）
        """
        try:
            result = self.slippage_estimator.estimate(market_data, side, size)
            return float(result["slippage_bps"])
        except Exception as e:
            logger.warning(
                "slippage_estimation_fallback",
                symbol=market_data.symbol,
                side=side.name,
                error=str(e),
            )
            # 回退到默认值（Maker ≈ 0, Taker ≈ 2-3 bps）
            return 0.0  # 保守估计，假设滑点较小

    def _estimate_impact_bps(
        self, side: OrderSide, size: Decimal, market_data: MarketData, market_state: dict
    ) -> float:
        """
        估算市场冲击（bps）

        基于线性冲击模型：
            impact_bps = alpha * (size / liquidity) * 10000

        Args:
            side: 订单方向
            size: 订单大小
            market_data: 市场数据
            market_state: 市场状态（流动性评分等）

        Returns:
            float: 冲击（bps）
        """
        # 计算订单簿总流动性（前3档）
        if side == OrderSide.BUY:
            levels = market_data.asks[:3]
        else:
            levels = market_data.bids[:3]

        total_liquidity = sum(level.size for level in levels) if levels else Decimal("0")

        if total_liquidity == 0:
            # 流动性不足，使用保守估计
            return 5.0  # 5 bps

        # 计算流动性比率
        liquidity_ratio = float(size / total_liquidity)

        # 线性冲击模型
        impact_bps = self.impact_alpha * liquidity_ratio * 10000

        # 根据流动性评分调整（流动性越差，冲击越大）
        liquidity_factor = 1.0 + (1.0 - market_state["liquidity_score"])
        impact_bps *= liquidity_factor

        # 限制冲击范围（0.5 - 10 bps）
        impact_bps = max(0.5, min(impact_bps, 10.0))

        return float(impact_bps)

    def _calculate_market_state(self, market_data: MarketData) -> dict:
        """
        计算市场状态（流动性、波动率、价差）

        Args:
            market_data: 市场数据

        Returns:
            dict: {
                "spread_bps": 买卖价差（bps），
                "liquidity_score": 流动性评分（0-1），
                "volatility_score": 波动率评分（0-1），
            }
        """
        # 1. 计算价差（bps）
        if market_data.bids and market_data.asks:
            best_bid = market_data.bids[0].price
            best_ask = market_data.asks[0].price
            mid_price = (best_bid + best_ask) / 2
            spread = best_ask - best_bid
            spread_bps = float(spread / mid_price * 10000) if mid_price > 0 else 0.0
        else:
            spread_bps = float("inf")

        # 2. 计算流动性评分（0-1，基于订单簿深度）
        # 简单模型：前3档总流动性 / 参考值（100）
        total_liquidity = sum(
            level.size for level in (market_data.bids[:3] + market_data.asks[:3])
        )
        liquidity_score = min(float(total_liquidity / 100), 1.0)

        # 3. 波动率评分（暂时使用价差作为代理）
        # 简化模型：价差越大，波动率越高
        # 正常价差 < 5 bps → 低波动，价差 > 10 bps → 高波动
        volatility_score = min(spread_bps / 10.0, 1.0) if spread_bps != float("inf") else 1.0

        return {
            "spread_bps": spread_bps,
            "liquidity_score": liquidity_score,
            "volatility_score": volatility_score,
        }

    def cache_estimate(self, order_id: str, estimate: CostEstimate) -> None:
        """
        缓存成本估算（用于后续验证）

        Args:
            order_id: 订单 ID
            estimate: 成本估算
        """
        self._estimate_cache[order_id] = estimate

    def get_cached_estimate(self, order_id: str) -> CostEstimate | None:
        """
        获取缓存的成本估算

        Args:
            order_id: 订单 ID

        Returns:
            CostEstimate: 缓存的估算，如果不存在则返回 None
        """
        return self._estimate_cache.get(order_id)

    def get_history_size(self) -> dict:
        """
        获取历史记录大小

        Returns:
            dict: {"estimates": 估算记录数, "actuals": 实际记录数}
        """
        return {
            "estimates": len(self._estimation_history),
            "actuals": len(self._actual_history),
        }

    def __repr__(self) -> str:
        return (
            f"DynamicCostEstimator("
            f"maker={float(self.maker_fee_rate)*10000:.1f} bps, "
            f"taker={float(self.taker_fee_rate)*10000:.1f} bps, "
            f"model={self.impact_model}, "
            f"history={len(self._actual_history)})"
        )
