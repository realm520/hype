"""信号去重器

Week 2 核心模块：防止过度交易，提升信号质量。

去重机制：
    1. 时间窗口去重（5秒冷却）
    2. 信号变化阈值（15% 变化才执行）
    3. 持仓状态去重（同方向不重复开仓）
    4. 信号衰减机制（连续同方向信号强度衰减）
"""

import time
from decimal import Decimal

import structlog

from src.core.types import MarketData, OrderSide, Position, SignalScore

logger = structlog.get_logger()


class SignalDeduplicator:
    """信号去重器

    Week 2 防止过度交易：
        - 避免高频重复信号
        - 确保信号强度真正变化
        - 防止同方向累积开仓
        - 惩罚连续同方向交易

    未来扩展（Week 3）：
        - 自适应冷却时间（基于波动率）
        - 动态变化阈值（基于历史信号分布）
        - 多时间尺度去重
    """

    def __init__(
        self,
        cooldown_seconds: float = 5.0,
        change_threshold: float = 0.15,
        decay_factor: float = 0.85,
        max_same_direction: int = 3,
    ):
        """
        初始化信号去重器

        Args:
            cooldown_seconds: 冷却时间（秒），默认 5.0
            change_threshold: 信号变化阈值（绝对值），默认 0.15
            decay_factor: 信号衰减系数，默认 0.85
            max_same_direction: 最大连续同方向次数，默认 3

        说明：
            - cooldown_seconds: 信号间隔 < 此值 → 拒绝
            - change_threshold: |new_signal - last_signal| < 此值 → 拒绝
            - decay_factor: 第 N 次同方向信号 *= decay_factor^(N-1)
            - max_same_direction: 同方向信号 > 此值 → 拒绝
        """
        self.cooldown_seconds = cooldown_seconds
        self.change_threshold = change_threshold
        self.decay_factor = decay_factor
        self.max_same_direction = max_same_direction

        # 每个 symbol 的信号历史
        self._last_signal: dict[str, SignalScore] = {}
        self._last_trade_time: dict[str, float] = {}
        self._consecutive_direction_count: dict[str, int] = {}
        self._last_direction: dict[str, OrderSide | None] = {}

        logger.info(
            "signal_deduplicator_initialized",
            cooldown_seconds=cooldown_seconds,
            change_threshold=change_threshold,
            decay_factor=decay_factor,
            max_same_direction=max_same_direction,
        )

    def filter(
        self,
        signal_score: SignalScore,
        market_data: MarketData,
        current_position: Position | None,
    ) -> SignalScore | None:
        """
        过滤信号，返回去重后的信号或 None

        Args:
            signal_score: 原始信号评分
            market_data: 市场数据
            current_position: 当前持仓

        Returns:
            SignalScore | None:
                - 通过所有去重检查 → 返回信号（可能经过衰减调整）
                - 被任一检查拒绝 → 返回 None

        去重逻辑：
            1. 时间窗口检查 → 未通过冷却期 → 拒绝
            2. 信号变化检查 → 变化不足 → 拒绝
            3. 持仓状态检查 → 同方向重复开仓 → 拒绝
            4. 衰减机制 → 连续同方向 → 强度衰减
        """
        symbol = market_data.symbol
        current_time = time.time()

        # 1. 时间窗口去重
        if symbol in self._last_trade_time:
            time_since_last = current_time - self._last_trade_time[symbol]
            if time_since_last < self.cooldown_seconds:
                logger.debug(
                    "signal_rejected_cooldown",
                    symbol=symbol,
                    time_since_last=time_since_last,
                    cooldown_required=self.cooldown_seconds,
                    signal_value=signal_score.value,
                )
                return None

        # 2. 信号变化阈值去重
        if symbol in self._last_signal:
            last_value = self._last_signal[symbol].value
            value_change = abs(signal_score.value - last_value)

            if value_change < self.change_threshold:
                logger.debug(
                    "signal_rejected_no_change",
                    symbol=symbol,
                    last_value=last_value,
                    new_value=signal_score.value,
                    value_change=value_change,
                    threshold=self.change_threshold,
                )
                return None

        # 3. 持仓状态去重（防止同方向累积开仓）
        signal_direction = self._get_signal_direction(signal_score.value)

        if current_position is not None and current_position.size != 0:
            position_direction = (
                OrderSide.BUY if current_position.size > 0 else OrderSide.SELL
            )

            # 如果信号方向与持仓方向相同 → 拒绝
            if signal_direction == position_direction:
                logger.debug(
                    "signal_rejected_same_direction_position",
                    symbol=symbol,
                    position_size=float(current_position.size),
                    position_direction=position_direction.name,
                    signal_direction=signal_direction.name if signal_direction else None,
                    signal_value=signal_score.value,
                )
                return None

        # 4. 信号衰减机制（惩罚连续同方向）
        if signal_direction is not None:
            # 检查是否是连续同方向
            if (
                symbol in self._last_direction
                and self._last_direction[symbol] == signal_direction
            ):
                # 增加连续计数
                self._consecutive_direction_count[symbol] = (
                    self._consecutive_direction_count.get(symbol, 0) + 1
                )

                # 检查是否超过最大连续次数
                if (
                    self._consecutive_direction_count[symbol]
                    > self.max_same_direction
                ):
                    logger.warning(
                        "signal_rejected_max_consecutive",
                        symbol=symbol,
                        direction=signal_direction.name,
                        consecutive_count=self._consecutive_direction_count[symbol],
                        max_allowed=self.max_same_direction,
                    )
                    return None

                # 应用衰减
                decay_power = self._consecutive_direction_count[symbol] - 1
                decay_multiplier = self.decay_factor**decay_power
                decayed_value = signal_score.value * decay_multiplier

                logger.info(
                    "signal_decayed",
                    symbol=symbol,
                    original_value=signal_score.value,
                    decayed_value=decayed_value,
                    decay_multiplier=decay_multiplier,
                    consecutive_count=self._consecutive_direction_count[symbol],
                )

                # 创建衰减后的信号
                signal_score = SignalScore(
                    value=decayed_value,
                    confidence=signal_score.confidence,
                    individual_scores=signal_score.individual_scores,
                    timestamp=signal_score.timestamp,
                )
            else:
                # 方向改变，重置计数
                self._consecutive_direction_count[symbol] = 1
                self._last_direction[symbol] = signal_direction

        # 通过所有检查，更新状态
        self._last_signal[symbol] = signal_score
        self._last_trade_time[symbol] = current_time

        logger.info(
            "signal_accepted",
            symbol=symbol,
            signal_value=signal_score.value,
            confidence=signal_score.confidence.name,
            time_since_last=current_time - self._last_trade_time.get(symbol, 0),
        )

        return signal_score

    def reset_symbol(self, symbol: str) -> None:
        """
        重置 symbol 的去重状态

        Args:
            symbol: 交易对

        使用场景：
            - 持仓平仓后重置状态
            - 市场状态发生重大变化
            - 手动干预需要清空历史
        """
        if symbol in self._last_signal:
            del self._last_signal[symbol]
        if symbol in self._last_trade_time:
            del self._last_trade_time[symbol]
        if symbol in self._consecutive_direction_count:
            del self._consecutive_direction_count[symbol]
        if symbol in self._last_direction:
            del self._last_direction[symbol]

        logger.info("signal_deduplicator_reset", symbol=symbol)

    def _get_signal_direction(self, signal_value: float) -> OrderSide | None:
        """
        获取信号方向

        Args:
            signal_value: 信号值

        Returns:
            OrderSide | None: BUY（正值）、SELL（负值）、None（零）
        """
        if signal_value > 0:
            return OrderSide.BUY
        elif signal_value < 0:
            return OrderSide.SELL
        else:
            return None

    def get_stats(self, symbol: str) -> dict:
        """
        获取去重统计信息

        Args:
            symbol: 交易对

        Returns:
            dict: 统计信息
        """
        return {
            "last_signal_value": (
                self._last_signal[symbol].value if symbol in self._last_signal else None
            ),
            "last_trade_time": self._last_trade_time.get(symbol, None),
            "consecutive_direction_count": self._consecutive_direction_count.get(
                symbol, 0
            ),
            "last_direction": (
                self._last_direction[symbol].name
                if symbol in self._last_direction and self._last_direction[symbol]
                else None
            ),
        }

    def __repr__(self) -> str:
        return (
            f"SignalDeduplicator(cooldown={self.cooldown_seconds}s, "
            f"change_threshold={self.change_threshold}, "
            f"decay={self.decay_factor}, "
            f"max_consecutive={self.max_same_direction})"
        )
