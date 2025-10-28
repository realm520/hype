"""未来收益跟踪器

用于计算信号的 T+n 未来收益，支持信号质量（IC）计算。
"""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class SignalSnapshot:
    """信号快照

    记录信号产生时的关键信息，用于后续计算未来收益。

    Attributes:
        signal_id: 信号唯一标识
        signal_value: 信号值（-1 到 1）
        timestamp: 信号产生时间（Unix 时间戳，秒）
        symbol: 交易对符号
        price: 信号产生时的价格
    """

    signal_id: int
    signal_value: float
    timestamp: float
    symbol: str
    price: Decimal


class FutureReturnTracker:
    """未来收益跟踪器

    功能：
        1. 记录每个信号产生时的价格和时间
        2. 定期扫描已到期信号（T+n），计算实际收益
        3. 通过回调函数更新 ShadowAnalyzer 的信号记录

    使用示例：
        tracker = FutureReturnTracker(
            window_minutes=10,
            update_callback=analyzer.update_signal_future_return
        )

        # 记录信号
        tracker.record_signal(signal_id, signal_value, symbol, price)

        # 定期更新（在主循环中调用）
        tracker.update_future_returns(current_prices)
    """

    def __init__(
        self,
        window_minutes: int,
        update_callback: Callable[[int, float], None],
        price_history_window_seconds: int = 3600,
    ):
        """
        初始化跟踪器

        Args:
            window_minutes: 未来收益窗口（分钟）
            update_callback: 收益更新回调函数，签名为 (signal_id, future_return)
            price_history_window_seconds: 价格历史保留时间（秒），默认 3600（1小时）
        """
        self.window_seconds = window_minutes * 60
        self.update_callback = update_callback

        # 待处理的信号队列
        self._pending_signals: list[SignalSnapshot] = []

        # 价格历史存储（按币种分组）
        # 格式：{symbol: deque[(timestamp, price)]}
        self._price_history: dict[str, deque] = {}
        self._price_history_window = price_history_window_seconds

        # 统计信息
        self._total_recorded = 0
        self._total_updated = 0

        logger.info(
            "future_return_tracker_initialized",
            window_minutes=window_minutes,
            price_history_window_seconds=price_history_window_seconds,
        )

    def record_signal(
        self,
        signal_id: int,
        signal_value: float,
        symbol: str,
        price: Decimal,
    ) -> None:
        """
        记录新信号

        Args:
            signal_id: 信号唯一标识
            signal_value: 信号值（-1 到 1）
            symbol: 交易对符号
            price: 当前价格
        """
        current_time = time.time()

        snapshot = SignalSnapshot(
            signal_id=signal_id,
            signal_value=signal_value,
            timestamp=current_time,
            symbol=symbol,
            price=price,
        )

        self._pending_signals.append(snapshot)
        self._total_recorded += 1

        # 记录价格历史（用于测试结束后回填 IC）
        self._record_price(symbol, price, current_time)

        logger.debug(
            "signal_recorded",
            signal_id=signal_id,
            symbol=symbol,
            signal_value=signal_value,
            price=float(price),
        )

    def update_future_returns(self, current_prices: dict[str, Decimal]) -> int:
        """
        批量更新已到期信号的未来收益

        Args:
            current_prices: 当前价格字典 {symbol: price}

        Returns:
            int: 本次更新的信号数量
        """
        current_time = time.time()
        updated_count = 0
        remaining_signals = []

        for snapshot in self._pending_signals:
            # 检查是否到期
            elapsed_seconds = current_time - snapshot.timestamp

            if elapsed_seconds < self.window_seconds:
                # 未到期，保留在队列
                remaining_signals.append(snapshot)
                continue

            # 已到期，计算未来收益
            current_price = current_prices.get(snapshot.symbol)
            if current_price is None:
                # 当前价格不可用，保留等待下次更新
                remaining_signals.append(snapshot)
                logger.warning(
                    "price_unavailable_for_signal",
                    signal_id=snapshot.signal_id,
                    symbol=snapshot.symbol,
                )
                continue

            # 计算方向性收益
            future_return = self._calculate_directional_return(
                old_price=snapshot.price,
                new_price=current_price,
                signal_value=snapshot.signal_value,
            )

            # 通过回调更新 analyzer
            try:
                self.update_callback(snapshot.signal_id, future_return)
                updated_count += 1
                self._total_updated += 1

                logger.debug(
                    "signal_return_updated",
                    signal_id=snapshot.signal_id,
                    symbol=snapshot.symbol,
                    old_price=float(snapshot.price),
                    new_price=float(current_price),
                    return_pct=future_return * 100,
                )
            except Exception as e:
                logger.error(
                    "failed_to_update_signal_return",
                    signal_id=snapshot.signal_id,
                    error=str(e),
                    exc_info=True,
                )

        # 更新队列（移除已处理信号）
        self._pending_signals = remaining_signals

        # 🔍 诊断日志：显示 pending 队列状态
        if len(self._pending_signals) > 0:
            oldest_age = int(current_time - min(s.timestamp for s in self._pending_signals))
            logger.info(
                "pending_signals_status",
                pending_count=len(self._pending_signals),
                oldest_age_seconds=oldest_age,
                window_seconds=self.window_seconds,
                time_until_first_update=max(0, self.window_seconds - oldest_age),
            )

        if updated_count > 0:
            logger.info(
                "future_returns_updated",
                updated=updated_count,
                pending=len(self._pending_signals),
                total_recorded=self._total_recorded,
                total_updated=self._total_updated,
            )

        return updated_count

    def _calculate_directional_return(
        self,
        old_price: Decimal,
        new_price: Decimal,
        signal_value: float,
    ) -> float:
        """
        计算方向性收益

        公式：
            - 价格变化率 = (new_price - old_price) / old_price
            - 方向性收益 = 价格变化率 * sign(signal_value)

        这样：
            - 做多信号（signal_value > 0）+ 价格上涨 = 正收益
            - 做空信号（signal_value < 0）+ 价格下跌 = 正收益

        Args:
            old_price: 信号产生时的价格
            new_price: T+n 时刻的价格
            signal_value: 信号值（用于确定方向）

        Returns:
            float: 方向性收益率（小数形式，如 0.01 = 1%）
        """
        if old_price == 0:
            logger.warning("zero_price_in_return_calculation")
            return 0.0

        # 价格变化率
        price_return = float((new_price - old_price) / old_price)

        # 信号方向（+1 或 -1）
        signal_direction = 1.0 if signal_value > 0 else -1.0

        # 方向性收益
        directional_return = price_return * signal_direction

        return directional_return

    def get_statistics(self) -> dict:
        """
        获取跟踪器统计信息

        Returns:
            dict: 统计信息
        """
        return {
            "total_recorded": self._total_recorded,
            "total_updated": self._total_updated,
            "pending_signals": len(self._pending_signals),
            "update_rate": (
                self._total_updated / self._total_recorded
                if self._total_recorded > 0
                else 0.0
            ),
            "price_history_symbols": list(self._price_history.keys()),
            "price_history_points": sum(
                len(prices) for prices in self._price_history.values()
            ),
        }

    def _record_price(self, symbol: str, price: Decimal, timestamp: float) -> None:
        """
        记录价格历史（内部方法）

        自动清理超过窗口的旧数据，保持内存可控。

        Args:
            symbol: 交易对符号
            price: 价格
            timestamp: Unix 时间戳（秒）
        """
        # 初始化币种的价格历史队列
        if symbol not in self._price_history:
            self._price_history[symbol] = deque()

        # 添加新价格点
        self._price_history[symbol].append((timestamp, price))

        # 清理超过窗口的旧数据
        cutoff_time = timestamp - self._price_history_window
        while (
            self._price_history[symbol]
            and self._price_history[symbol][0][0] < cutoff_time
        ):
            self._price_history[symbol].popleft()

    def _get_price_at_time(
        self,
        symbol: str,
        target_time: float,
        tolerance_seconds: float = 30.0,
    ) -> Decimal | None:
        """
        获取指定时间点的价格（使用最近邻插值）

        Args:
            symbol: 交易对符号
            target_time: 目标时间（Unix 时间戳，秒）
            tolerance_seconds: 容忍时间差（秒），超过此值返回 None

        Returns:
            Decimal | None: 最接近的价格，如果无法找到则返回 None
        """
        if symbol not in self._price_history:
            return None

        # 查找最接近的价格
        closest_price = None
        min_diff = float("inf")

        for timestamp, price in self._price_history[symbol]:
            diff = abs(timestamp - target_time)
            if diff < min_diff and diff <= tolerance_seconds:
                min_diff = diff
                closest_price = price

        if closest_price is not None:
            logger.debug(
                "price_found_at_time",
                symbol=symbol,
                target_time=target_time,
                found_time_diff=min_diff,
                price=float(closest_price),
            )

        return closest_price

    def backfill_future_returns(
        self, window_minutes_list: list[int]
    ) -> dict[int, dict[int, float]]:
        """
        测试结束后回填计算多窗口未来收益

        使用存储的价格历史，对所有信号计算多个时间窗口的未来收益。
        这样可以在测试结束后验证不同窗口下的信号质量（IC）。

        Args:
            window_minutes_list: 时间窗口列表（分钟），如 [5, 10, 15, 30]

        Returns:
            dict: {signal_id: {window_minutes: future_return}}
                 例如：{1: {5: 0.001, 10: 0.002, 15: 0.003}}
        """
        results: dict[int, dict[int, float]] = {}

        # 处理所有信号（包括已处理和未处理的）
        all_signals = list(self._pending_signals)

        logger.info(
            "starting_backfill",
            total_signals=len(all_signals),
            windows=window_minutes_list,
        )

        success_count = 0
        missing_price_count = 0

        for snapshot in all_signals:
            signal_id = snapshot.signal_id
            results[signal_id] = {}

            for window_minutes in window_minutes_list:
                # 计算目标时间
                target_time = snapshot.timestamp + (window_minutes * 60)

                # 查找最接近目标时间的价格
                future_price = self._get_price_at_time(
                    snapshot.symbol, target_time, tolerance_seconds=60.0
                )

                if future_price is not None:
                    # 计算方向性收益
                    future_return = self._calculate_directional_return(
                        old_price=snapshot.price,
                        new_price=future_price,
                        signal_value=snapshot.signal_value,
                    )
                    results[signal_id][window_minutes] = future_return
                    success_count += 1
                else:
                    # 价格不可用
                    missing_price_count += 1
                    logger.warning(
                        "backfill_price_unavailable",
                        signal_id=signal_id,
                        symbol=snapshot.symbol,
                        target_time=target_time,
                        window_minutes=window_minutes,
                    )

        logger.info(
            "backfill_completed",
            total_signals=len(all_signals),
            total_calculations=len(all_signals) * len(window_minutes_list),
            successful=success_count,
            missing_prices=missing_price_count,
            success_rate=success_count
            / (len(all_signals) * len(window_minutes_list))
            if len(all_signals) > 0
            else 0.0,
        )

        return results
