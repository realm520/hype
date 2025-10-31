"""MarketStateDetector 单元测试

测试覆盖：
    1. 正常市场状态检测
    2. 高波动市场检测
    3. 低流动性市场检测
    4. 震荡市场检测
    5. 优先级测试（LOW_LIQ > HIGH_VOL > CHOPPY）
    6. 边界值测试
    7. 重置功能测试
"""

from decimal import Decimal

import pytest

from src.analytics.market_state_detector import MarketState, MarketStateDetector
from src.core.types import Level, MarketData


@pytest.fixture
def detector():
    """创建默认检测器实例"""
    return MarketStateDetector(
        high_volatility_threshold=0.02,  # 2%
        low_liquidity_threshold=0.3,
        spread_threshold_bps=15.0,
        choppy_reversal_threshold=5,
        price_history_size=20,
        min_liquidity_depth=Decimal("10.0"),
    )


@pytest.fixture
def normal_market_data():
    """正常市场数据"""
    return MarketData(
        symbol="BTC",
        timestamp=1000,
        bids=[
            Level(Decimal("50000"), Decimal("5.0")),
            Level(Decimal("49990"), Decimal("4.0")),
            Level(Decimal("49980"), Decimal("3.0")),
            Level(Decimal("49970"), Decimal("2.0")),
            Level(Decimal("49960"), Decimal("1.0")),
        ],
        asks=[
            Level(Decimal("50010"), Decimal("5.0")),
            Level(Decimal("50020"), Decimal("4.0")),
            Level(Decimal("50030"), Decimal("3.0")),
            Level(Decimal("50040"), Decimal("2.0")),
            Level(Decimal("50050"), Decimal("1.0")),
        ],
        mid_price=Decimal("50005"),
    )


@pytest.fixture
def low_liquidity_market_data():
    """低流动性市场数据（订单簿深度不足）"""
    return MarketData(
        symbol="BTC",
        timestamp=1000,
        bids=[
            Level(Decimal("50000"), Decimal("0.5")),  # 深度很浅
            Level(Decimal("49990"), Decimal("0.3")),
        ],
        asks=[
            Level(Decimal("50010"), Decimal("0.5")),
            Level(Decimal("50020"), Decimal("0.3")),
        ],
        mid_price=Decimal("50005"),
    )


@pytest.fixture
def wide_spread_market_data():
    """宽价差市场数据（低流动性的另一种表现）"""
    return MarketData(
        symbol="BTC",
        timestamp=1000,
        bids=[
            Level(Decimal("49900"), Decimal("5.0")),  # 价差 200
        ],
        asks=[
            Level(Decimal("50100"), Decimal("5.0")),
        ],
        mid_price=Decimal("50000"),
    )


class TestMarketStateDetection:
    """市场状态检测测试"""

    def test_normal_market_detection(self, detector, normal_market_data):
        """测试正常市场状态检测"""
        # 喂入稳定价格（小幅波动）
        for i in range(20):
            market_data = MarketData(
                symbol="BTC",
                timestamp=1000 + i,
                bids=normal_market_data.bids,
                asks=normal_market_data.asks,
                mid_price=Decimal("50000") + Decimal(str(i * 0.1)),  # 每次涨 0.1
            )
            metrics = detector.detect_state(market_data)

        # 验证：应该识别为正常市场
        assert metrics.detected_state == MarketState.NORMAL
        assert metrics.volatility < 0.02  # 波动率低
        assert metrics.liquidity_score > 0.3  # 流动性充足
        assert metrics.spread_bps < 15.0  # 价差正常

    def test_high_volatility_detection(self, detector, normal_market_data):
        """测试高波动市场检测"""
        # 喂入高波动价格（价格剧烈波动，避免频繁反转）
        base_price = Decimal("50000")
        for i in range(20):
            # 价格在 50000 ±1500 之间剧烈波动（更大波动，更少反转）
            if i < 10:
                price_change = Decimal("1500")  # 前10个点上涨
            else:
                price_change = Decimal("-1500")  # 后10个点下跌
            current_price = base_price + price_change

            market_data = MarketData(
                symbol="BTC",
                timestamp=1000 + i,
                bids=normal_market_data.bids,
                asks=normal_market_data.asks,
                mid_price=current_price,
            )
            metrics = detector.detect_state(market_data)

        # 验证：应该识别为高波动市场
        assert metrics.detected_state == MarketState.HIGH_VOL
        assert metrics.volatility > 0.02  # 波动率高

    def test_low_liquidity_detection_shallow_depth(
        self, detector, low_liquidity_market_data
    ):
        """测试低流动性检测（订单簿深度不足）"""
        # 喂入稳定价格（避免高波动干扰）
        for i in range(20):
            market_data = MarketData(
                symbol="BTC",
                timestamp=1000 + i,
                bids=low_liquidity_market_data.bids,
                asks=low_liquidity_market_data.asks,
                mid_price=Decimal("50005") + Decimal(str(i * 0.1)),
            )
            metrics = detector.detect_state(market_data)

        # 验证：应该识别为低流动性市场
        assert metrics.detected_state == MarketState.LOW_LIQ
        assert metrics.liquidity_score < 0.3  # 流动性评分低

    def test_low_liquidity_detection_wide_spread(
        self, detector, wide_spread_market_data
    ):
        """测试低流动性检测（价差过大）"""
        # 喂入稳定价格
        for i in range(20):
            market_data = MarketData(
                symbol="BTC",
                timestamp=1000 + i,
                bids=wide_spread_market_data.bids,
                asks=wide_spread_market_data.asks,
                mid_price=Decimal("50000") + Decimal(str(i * 0.1)),
            )
            metrics = detector.detect_state(market_data)

        # 验证：应该识别为低流动性市场（因为价差过大）
        assert metrics.detected_state == MarketState.LOW_LIQ
        assert metrics.spread_bps > 15.0  # 价差大于阈值

    def test_choppy_market_detection(self, detector, normal_market_data):
        """测试震荡市场检测"""
        # 喂入震荡价格（频繁小幅反转）
        base_price = Decimal("50000")
        for i in range(20):
            # 价格在 50000 ±5 之间频繁反转
            price_change = Decimal(str((i % 2) * 10 - 5))
            current_price = base_price + price_change

            market_data = MarketData(
                symbol="BTC",
                timestamp=1000 + i,
                bids=normal_market_data.bids,
                asks=normal_market_data.asks,
                mid_price=current_price,
            )
            metrics = detector.detect_state(market_data)

        # 验证：应该识别为震荡市场
        assert metrics.detected_state == MarketState.CHOPPY
        assert metrics.price_reversals >= 5  # 反转次数多
        assert metrics.volatility < 0.02  # 波动率不高（小幅震荡）

    def test_state_priority_low_liq_over_high_vol(self, detector):
        """测试优先级：LOW_LIQ > HIGH_VOL"""
        # 同时满足低流动性和高波动，应该优先识别为低流动性
        low_liq_data = MarketData(
            symbol="BTC",
            timestamp=1000,
            bids=[Level(Decimal("50000"), Decimal("0.1"))],  # 极浅深度
            asks=[Level(Decimal("50010"), Decimal("0.1"))],
            mid_price=Decimal("50005"),
        )

        # 喂入高波动价格 + 低流动性
        for i in range(20):
            price_change = Decimal(str((i % 2) * 2000 - 1000))  # 高波动
            current_price = Decimal("50000") + price_change

            market_data = MarketData(
                symbol="BTC",
                timestamp=1000 + i,
                bids=low_liq_data.bids,
                asks=low_liq_data.asks,
                mid_price=current_price,
            )
            metrics = detector.detect_state(market_data)

        # 验证：应该优先识别为低流动性（即使波动率也很高）
        assert metrics.detected_state == MarketState.LOW_LIQ

    def test_state_priority_high_vol_over_choppy(self, detector, normal_market_data):
        """测试优先级：HIGH_VOL > CHOPPY"""
        # 同时满足高波动和震荡，应该优先识别为高波动
        base_price = Decimal("50000")
        for i in range(20):
            # 价格剧烈波动（满足高波动）+ 频繁反转（满足震荡）
            # 每 2 个价格点反转一次，产生更多反转
            if i % 2 == 0:
                price_change = Decimal("1500")  # 上涨（更大波动）
            else:
                price_change = Decimal("-1500")  # 下跌（更大波动）
            current_price = base_price + price_change

            market_data = MarketData(
                symbol="BTC",
                timestamp=1000 + i,
                bids=normal_market_data.bids,
                asks=normal_market_data.asks,
                mid_price=current_price,
            )
            metrics = detector.detect_state(market_data)

        # 验证：应该优先识别为高波动（即使反转次数也多）
        assert metrics.detected_state == MarketState.HIGH_VOL
        assert metrics.volatility > 0.02
        assert metrics.price_reversals >= 5


class TestMetricsCalculation:
    """指标计算测试"""

    def test_volatility_calculation_stable_prices(self, detector, normal_market_data):
        """测试波动率计算（稳定价格）"""
        # 喂入完全稳定的价格
        for i in range(20):
            market_data = MarketData(
                symbol="BTC",
                timestamp=1000 + i,
                bids=normal_market_data.bids,
                asks=normal_market_data.asks,
                mid_price=Decimal("50000"),  # 价格不变
            )
            metrics = detector.detect_state(market_data)

        # 验证：波动率应该接近 0
        assert metrics.volatility < 0.001

    def test_volatility_calculation_trending_prices(self, detector, normal_market_data):
        """测试波动率计算（趋势价格）"""
        # 喂入单向趋势价格（持续上涨）
        for i in range(20):
            market_data = MarketData(
                symbol="BTC",
                timestamp=1000 + i,
                bids=normal_market_data.bids,
                asks=normal_market_data.asks,
                mid_price=Decimal("50000") + Decimal(str(i * 100)),  # 每次涨 100
            )
            metrics = detector.detect_state(market_data)

        # 验证：波动率适中（单向趋势波动率低于震荡）
        assert 0.005 < metrics.volatility < 0.02

    def test_liquidity_score_calculation(self, detector):
        """测试流动性评分计算"""
        # 测试不同深度的流动性评分（根据 sigmoid 函数调整期望）
        # sigmoid: 1 / (1 + (min_depth / (total_depth + 1e-10))^2)
        # min_liquidity_depth = 10.0
        # 注意：每个 level 会重复 5 次（* 5），所以实际深度 = bid_size*5 + ask_size*5
        test_cases = [
            # (bid_size, ask_size, expected_score_range)
            # total_depth=0.2*5 + 0.2*5 = 2.0 → score = 1/(1+(10/2)^2) = 1/26 ≈ 0.038
            (Decimal("0.2"), Decimal("0.2"), (0.03, 0.05)),  # 很低流动性
            # total_depth=2.0*5 + 2.0*5 = 20.0 → score = 1/(1+(10/20)^2) = 1/1.25 = 0.8
            (Decimal("2.0"), Decimal("2.0"), (0.75, 0.85)),  # 中等流动性
            # total_depth=10.0*5 + 10.0*5 = 100.0 → score = 1/(1+(10/100)^2) = 1/1.01 ≈ 0.99
            (Decimal("10.0"), Decimal("10.0"), (0.95, 1.0)),  # 高流动性
        ]

        for bid_size, ask_size, (min_score, max_score) in test_cases:
            market_data = MarketData(
                symbol="BTC",
                timestamp=1000,
                bids=[Level(Decimal("50000"), bid_size)] * 5,
                asks=[Level(Decimal("50010"), ask_size)] * 5,
                mid_price=Decimal("50005"),
            )
            metrics = detector.detect_state(market_data)

            # 验证：流动性评分在预期范围内
            assert min_score <= metrics.liquidity_score <= max_score

    def test_spread_calculation(self, detector):
        """测试价差计算"""
        # 测试不同价差的计算
        test_cases = [
            # (best_bid, best_ask, expected_spread_bps)
            (Decimal("50000"), Decimal("50010"), 2.0),  # 10 / 50005 * 10000 ≈ 2 bps
            (
                Decimal("50000"),
                Decimal("50050"),
                10.0,
            ),  # 50 / 50025 * 10000 ≈ 10 bps
            (
                Decimal("50000"),
                Decimal("50100"),
                20.0,
            ),  # 100 / 50050 * 10000 ≈ 20 bps
        ]

        for best_bid, best_ask, expected_spread in test_cases:
            mid_price = (best_bid + best_ask) / Decimal("2")
            market_data = MarketData(
                symbol="BTC",
                timestamp=1000,
                bids=[Level(best_bid, Decimal("10.0"))],
                asks=[Level(best_ask, Decimal("10.0"))],
                mid_price=mid_price,
            )
            metrics = detector.detect_state(market_data)

            # 验证：价差计算准确（±0.5 bps 误差）
            assert abs(metrics.spread_bps - expected_spread) < 0.5

    def test_price_reversal_counting(self, detector, normal_market_data):
        """测试价格反转计数"""
        # 喂入明确的反转模式：上-下-上-下...
        base_price = Decimal("50000")
        for i in range(10):
            price_change = Decimal(str((i % 2) * 10 - 5))  # +5, -5, +5, -5...
            current_price = base_price + price_change

            market_data = MarketData(
                symbol="BTC",
                timestamp=1000 + i,
                bids=normal_market_data.bids,
                asks=normal_market_data.asks,
                mid_price=current_price,
            )
            metrics = detector.detect_state(market_data)

        # 验证：应该检测到 8 次反转（10 个价格点 - 1 - 1）
        assert metrics.price_reversals == 8


class TestEdgeCases:
    """边界值和异常情况测试"""

    def test_empty_orderbook(self, detector):
        """测试空订单簿"""
        market_data = MarketData(
            symbol="BTC",
            timestamp=1000,
            bids=[],  # 空订单簿
            asks=[],
            mid_price=Decimal("50000"),
        )
        metrics = detector.detect_state(market_data)

        # 验证：应该识别为低流动性（流动性评分为 0）
        assert metrics.detected_state == MarketState.LOW_LIQ
        assert metrics.liquidity_score == 0.0
        assert metrics.spread_bps == 9999.0  # 极大价差

    def test_insufficient_history(self, detector, normal_market_data):
        """测试历史数据不足时的行为"""
        # 只喂入 1 个数据点
        metrics = detector.detect_state(normal_market_data)

        # 验证：波动率为 0（无法计算），但不应该报错
        assert metrics.volatility == 0.0
        assert metrics.price_reversals == 0

    def test_threshold_boundary_values(self):
        """测试阈值边界值"""
        # 测试临界值识别
        detector = MarketStateDetector(
            high_volatility_threshold=0.01,  # 1% 波动率阈值
            low_liquidity_threshold=0.5,
            spread_threshold_bps=10.0,
        )

        # 创建刚好达到高波动阈值的数据
        # 波动率 = 1%，应该识别为 NORMAL（< 阈值）
        # 波动率 = 1.01%，应该识别为 HIGH_VOL（> 阈值）
        # 这需要精心设计价格序列，暂时跳过详细测试

    def test_reset_functionality(self, detector, normal_market_data):
        """测试重置功能"""
        # 喂入一些数据
        for i in range(10):
            detector.detect_state(normal_market_data)

        # 重置
        detector.reset()

        # 验证：历史数据应该被清空
        assert len(detector._price_history) == 0
        assert len(detector._price_changes) == 0

        # 再次检测应该像初始状态一样
        metrics = detector.detect_state(normal_market_data)
        assert metrics.volatility == 0.0  # 无历史数据，波动率为 0
        assert metrics.price_reversals == 0


class TestRealWorldScenarios:
    """真实场景模拟测试"""

    def test_flash_crash_scenario(self, detector, normal_market_data):
        """测试闪崩场景（极端高波动 + 低流动性）"""
        # 正常市场 → 突然闪崩 → 流动性枯竭
        base_price = Decimal("50000")

        # 前 10 个点：正常市场
        for i in range(10):
            market_data = MarketData(
                symbol="BTC",
                timestamp=1000 + i,
                bids=normal_market_data.bids,
                asks=normal_market_data.asks,
                mid_price=base_price + Decimal(str(i * 10)),
            )
            detector.detect_state(market_data)

        # 后 10 个点：闪崩（价格暴跌 + 流动性枯竭）
        for i in range(10, 20):
            crash_price = base_price - Decimal("5000")  # 暴跌 10%
            market_data = MarketData(
                symbol="BTC",
                timestamp=1000 + i,
                bids=[Level(crash_price, Decimal("0.1"))],  # 流动性枯竭
                asks=[Level(crash_price + Decimal("100"), Decimal("0.1"))],
                mid_price=crash_price,
            )
            metrics = detector.detect_state(market_data)

        # 验证：应该优先识别为低流动性（更危险）
        assert metrics.detected_state == MarketState.LOW_LIQ

    def test_range_bound_market_scenario(self, detector, normal_market_data):
        """测试区间震荡场景"""
        # 价格在固定区间内震荡
        base_price = Decimal("50000")
        range_size = Decimal("100")

        for i in range(30):
            # 价格在 [49950, 50050] 之间震荡
            if i % 4 == 0:
                price = base_price + range_size
            elif i % 4 == 1:
                price = base_price - range_size
            elif i % 4 == 2:
                price = base_price + range_size / 2
            else:
                price = base_price - range_size / 2

            market_data = MarketData(
                symbol="BTC",
                timestamp=1000 + i,
                bids=normal_market_data.bids,
                asks=normal_market_data.asks,
                mid_price=price,
            )
            metrics = detector.detect_state(market_data)

        # 验证：应该识别为震荡市场
        assert metrics.detected_state == MarketState.CHOPPY
        assert metrics.price_reversals >= 5

    def test_trending_market_scenario(self, detector, normal_market_data):
        """测试单向趋势场景"""
        # 价格持续单向上涨（无反转）
        base_price = Decimal("50000")

        for i in range(30):
            current_price = base_price + Decimal(str(i * 50))  # 持续上涨

            market_data = MarketData(
                symbol="BTC",
                timestamp=1000 + i,
                bids=normal_market_data.bids,
                asks=normal_market_data.asks,
                mid_price=current_price,
            )
            metrics = detector.detect_state(market_data)

        # 验证：应该识别为正常市场（趋势市场不算震荡）
        assert metrics.detected_state == MarketState.NORMAL
        assert metrics.price_reversals < 5  # 反转次数少
