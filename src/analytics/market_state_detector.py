"""市场状态检测器

Week 2 Phase 3 - Day 1

检测 4 种市场状态用于调整成本估计：
    - NORMAL: 正常市场（默认状态）
    - HIGH_VOL: 高波动市场（波动率 > 阈值）
    - LOW_LIQ: 低流动性市场（订单簿深度 < 阈值）
    - CHOPPY: 震荡市场（频繁小幅波动，方向不明确）
"""

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

import structlog

from src.core.types import MarketData

logger = structlog.get_logger(__name__)


class MarketState(Enum):
    """市场状态枚举"""

    NORMAL = "normal"
    HIGH_VOL = "high_volatility"
    LOW_LIQ = "low_liquidity"
    CHOPPY = "choppy"


@dataclass
class MarketMetrics:
    """市场度量指标"""

    volatility: float  # 近期价格波动率（标准差）
    liquidity_score: float  # 流动性评分（0-1）
    spread_bps: float  # 价差（基点）
    price_reversals: int  # 价格反转次数
    detected_state: MarketState  # 检测到的市场状态


class MarketStateDetector:
    """市场状态检测器

    检测逻辑：
        1. 优先级顺序：LOW_LIQ > HIGH_VOL > CHOPPY > NORMAL
        2. LOW_LIQ：流动性评分 < low_liquidity_threshold
        3. HIGH_VOL：波动率 > high_volatility_threshold
        4. CHOPPY：价格反转次数 > choppy_reversal_threshold
        5. NORMAL：默认状态
    """

    def __init__(
        self,
        high_volatility_threshold: float = 0.02,  # 2% 波动率阈值
        low_liquidity_threshold: float = 0.3,  # 流动性评分阈值（0-1）
        spread_threshold_bps: float = 15.0,  # 价差阈值（基点）
        choppy_reversal_threshold: int = 5,  # 震荡市场反转次数阈值
        price_history_size: int = 20,  # 价格历史窗口大小
        min_liquidity_depth: Decimal = Decimal("10.0"),  # 最小流动性深度（单位：币）
    ):
        """初始化市场状态检测器

        Args:
            high_volatility_threshold: 高波动率阈值（相对标准差）
            low_liquidity_threshold: 低流动性阈值（流动性评分）
            spread_threshold_bps: 价差阈值（基点）
            choppy_reversal_threshold: 震荡市场价格反转次数阈值
            price_history_size: 价格历史窗口大小
            min_liquidity_depth: 最小流动性深度（单位：币）
        """
        self.high_volatility_threshold = high_volatility_threshold
        self.low_liquidity_threshold = low_liquidity_threshold
        self.spread_threshold_bps = spread_threshold_bps
        self.choppy_reversal_threshold = choppy_reversal_threshold
        self.min_liquidity_depth = min_liquidity_depth

        # 价格历史（用于波动率计算）
        self._price_history: deque[Decimal] = deque(maxlen=price_history_size)

        # 价格变化历史（用于反转检测）
        self._price_changes: deque[int] = deque(maxlen=price_history_size - 1)

    def detect_state(self, market_data: MarketData) -> MarketMetrics:
        """检测当前市场状态

        Args:
            market_data: 市场数据（订单簿 + 最新价格）

        Returns:
            MarketMetrics: 市场度量指标和检测到的状态
        """
        # 1. 更新价格历史
        current_price = market_data.mid_price
        self._update_price_history(current_price)

        # 2. 计算各项指标
        volatility = self._calculate_volatility()
        liquidity_score = self._calculate_liquidity_score(market_data)
        spread_bps = self._calculate_spread_bps(market_data)
        price_reversals = self._count_price_reversals()

        # 3. 根据优先级确定状态
        state = self._determine_state(
            volatility=volatility,
            liquidity_score=liquidity_score,
            spread_bps=spread_bps,
            price_reversals=price_reversals,
        )

        # 4. 记录日志
        logger.info(
            "market_state_detected",
            state=state.value,
            volatility=volatility,
            liquidity_score=liquidity_score,
            spread_bps=spread_bps,
            price_reversals=price_reversals,
        )

        return MarketMetrics(
            volatility=volatility,
            liquidity_score=liquidity_score,
            spread_bps=spread_bps,
            price_reversals=price_reversals,
            detected_state=state,
        )

    def _update_price_history(self, price: Decimal) -> None:
        """更新价格历史并记录价格变化方向"""
        if len(self._price_history) > 0:
            # 记录价格变化方向（+1: 上涨, -1: 下跌, 0: 不变）
            price_change = price - self._price_history[-1]
            if price_change > 0:
                self._price_changes.append(1)
            elif price_change < 0:
                self._price_changes.append(-1)
            else:
                self._price_changes.append(0)

        self._price_history.append(price)

    def _calculate_volatility(self) -> float:
        """计算近期价格波动率（标准差 / 均值）

        Returns:
            float: 相对波动率（0 表示无波动，> 0.02 表示高波动）
        """
        if len(self._price_history) < 2:
            return 0.0

        # 转换为 float 便于计算
        prices = [float(p) for p in self._price_history]

        # 计算均值和标准差
        mean = sum(prices) / len(prices)
        variance = sum((p - mean) ** 2 for p in prices) / len(prices)
        std_dev = variance**0.5

        # 相对波动率（标准差 / 均值）
        if mean > 0:
            return std_dev / mean
        return 0.0

    def _calculate_liquidity_score(self, market_data: MarketData) -> float:
        """计算流动性评分（0-1）

        评分逻辑：
            - 考虑买卖双方订单簿深度（前 5 档）
            - 深度越大，评分越高
            - 评分范围：0.0（极低流动性）- 1.0（高流动性）

        Returns:
            float: 流动性评分（0-1）
        """
        if not market_data.bids or not market_data.asks:
            return 0.0

        # 计算前 5 档买卖深度总和
        bid_depth = sum(level.size for level in market_data.bids[:5])
        ask_depth = sum(level.size for level in market_data.asks[:5])
        total_depth = bid_depth + ask_depth

        # 使用 sigmoid 函数将深度映射到 0-1
        # depth >= min_liquidity_depth → score ≈ 0.5
        # depth >= 2 * min_liquidity_depth → score ≈ 0.73
        # depth >= 5 * min_liquidity_depth → score ≈ 0.93
        min_depth = float(self.min_liquidity_depth)
        if min_depth > 0:
            score = 1.0 / (1.0 + (min_depth / (float(total_depth) + 1e-10)) ** 2)
        else:
            score = 1.0

        return min(score, 1.0)

    def _calculate_spread_bps(self, market_data: MarketData) -> float:
        """计算价差（基点）

        Args:
            market_data: 市场数据

        Returns:
            float: 价差（基点，1 bps = 0.01%）
        """
        if not market_data.bids or not market_data.asks:
            return 9999.0  # 无订单簿时返回极大值

        best_bid = market_data.bids[0].price
        best_ask = market_data.asks[0].price

        # 价差（基点）= (ask - bid) / mid_price * 10000
        spread = (best_ask - best_bid) / market_data.mid_price * Decimal("10000")
        return float(spread)

    def _count_price_reversals(self) -> int:
        """统计价格反转次数

        反转定义：价格变化方向从 +1 变为 -1，或从 -1 变为 +1

        Returns:
            int: 反转次数
        """
        if len(self._price_changes) < 2:
            return 0

        reversals = 0
        for i in range(1, len(self._price_changes)):
            prev_change = self._price_changes[i - 1]
            curr_change = self._price_changes[i]

            # 检测方向反转（忽略 0 变化）
            if prev_change != 0 and curr_change != 0:
                if prev_change * curr_change < 0:  # 符号相反
                    reversals += 1

        return reversals

    def _determine_state(
        self,
        volatility: float,
        liquidity_score: float,
        spread_bps: float,
        price_reversals: int,
    ) -> MarketState:
        """根据指标确定市场状态

        优先级：LOW_LIQ > HIGH_VOL > CHOPPY > NORMAL

        Args:
            volatility: 波动率
            liquidity_score: 流动性评分
            spread_bps: 价差（基点）
            price_reversals: 价格反转次数

        Returns:
            MarketState: 检测到的市场状态
        """
        # 1. 优先检测低流动性（最危险）
        if (
            liquidity_score < self.low_liquidity_threshold
            or spread_bps > self.spread_threshold_bps
        ):
            return MarketState.LOW_LIQ

        # 2. 检测高波动性
        if volatility > self.high_volatility_threshold:
            return MarketState.HIGH_VOL

        # 3. 检测震荡市场
        if price_reversals >= self.choppy_reversal_threshold:
            return MarketState.CHOPPY

        # 4. 默认为正常市场
        return MarketState.NORMAL

    def reset(self) -> None:
        """重置检测器状态（用于测试或重新开始）"""
        self._price_history.clear()
        self._price_changes.clear()
        logger.info("market_state_detector_reset")
