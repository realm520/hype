"""分析层单元测试"""

from decimal import Decimal

from src.analytics.metrics import MetricsCollector
from src.analytics.pnl_attribution import PnLAttribution, TradeAttribution


class TestPnLAttribution:
    """测试 PnL 归因分析器"""

    def test_initialization(self):
        """测试初始化"""
        attribution = PnLAttribution(
            fee_rate=0.00045,
            alpha_threshold=0.70,
            max_history=1000,
        )

        assert attribution.fee_rate == Decimal("0.00045")
        assert attribution.alpha_threshold == 0.70
        assert len(attribution._attribution_history) == 0

    def test_attribute_buy_trade(self, sample_buy_order):
        """测试买入交易归因"""
        attribution = PnLAttribution()

        result = attribution.attribute_trade(
            order=sample_buy_order,
            signal_value=0.8,
            reference_price=Decimal("1500.0"),
            actual_fill_price=Decimal("1500.5"),
            best_price=Decimal("1500.5"),
        )

        # 检查归因结果
        assert isinstance(result, TradeAttribution)
        assert result.trade_id == sample_buy_order.id
        assert result.symbol == sample_buy_order.symbol

        # Fee 应该是负数
        assert result.fee < 0

        # Slippage 应该是负数（买入价格高于参考价）
        assert result.slippage <= 0

        # Total PnL = Alpha + Fee + Slippage + Impact + Rebate
        calculated_total = (
            result.alpha + result.fee + result.slippage + result.impact + result.rebate
        )
        assert abs(calculated_total - result.total_pnl) < Decimal("0.01")

    def test_attribute_sell_trade(self, sample_sell_order):
        """测试卖出交易归因"""
        attribution = PnLAttribution()

        result = attribution.attribute_trade(
            order=sample_sell_order,
            signal_value=-0.8,
            reference_price=Decimal("1500.0"),
            actual_fill_price=Decimal("1499.5"),
            best_price=Decimal("1499.5"),
        )

        # 检查归因结果
        assert isinstance(result, TradeAttribution)
        assert result.fee < 0  # 手续费总是负数
        assert result.rebate == 0  # Week 1 IOC 无返佣

    def test_fee_calculation(self, sample_buy_order):
        """测试手续费计算"""
        attribution = PnLAttribution(fee_rate=0.00045)

        result = attribution.attribute_trade(
            order=sample_buy_order,
            signal_value=0.8,
            reference_price=sample_buy_order.price,
            actual_fill_price=sample_buy_order.price,
            best_price=sample_buy_order.price,
        )

        # 手续费 = 交易价值 * 费率
        expected_fee = -(
            sample_buy_order.size * sample_buy_order.price * Decimal("0.00045")
        )
        assert abs(result.fee - expected_fee) < Decimal("0.001")

    def test_slippage_calculation(self, sample_buy_order):
        """测试滑点计算"""
        attribution = PnLAttribution()

        reference_price = Decimal("1500.0")
        actual_fill_price = Decimal("1502.0")  # 滑点 2 USD

        result = attribution.attribute_trade(
            order=sample_buy_order,
            signal_value=0.8,
            reference_price=reference_price,
            actual_fill_price=actual_fill_price,
            best_price=actual_fill_price,
        )

        # 买入滑点 = -(实际价格 - 参考价格) * 数量
        expected_slippage = -(actual_fill_price - reference_price) * sample_buy_order.size
        assert abs(result.slippage - expected_slippage) < Decimal("0.01")

    def test_cumulative_attribution(self, sample_buy_order):
        """测试累计归因统计"""
        attribution = PnLAttribution()

        # 执行多笔交易
        for i in range(5):
            order = sample_buy_order
            order.id = f"order_{i}"

            attribution.attribute_trade(
                order=order,
                signal_value=0.8,
                reference_price=Decimal("1500.0"),
                actual_fill_price=Decimal("1500.5"),
                best_price=Decimal("1500.5"),
            )

        cumulative = attribution.get_cumulative_attribution()

        # 应该有累计的各项数据
        assert cumulative["fee"] < 0  # 手续费应该是负数（成本）
        assert cumulative["slippage"] <= 0  # 滑点应该是非正数（成本）
        assert cumulative["alpha"] != 0  # Alpha 应该非零（修复后）
        assert cumulative["total"] != 0  # 总 PnL 应该非零
        assert len(attribution._attribution_history) == 5  # 应该记录了5笔交易

    def test_alpha_percentage(self, sample_buy_order):
        """测试 Alpha 占比计算"""
        attribution = PnLAttribution()

        result = attribution.attribute_trade(
            order=sample_buy_order,
            signal_value=0.8,
            reference_price=Decimal("1500.0"),
            actual_fill_price=Decimal("1500.5"),
            best_price=Decimal("1500.5"),
        )

        # Alpha 占比应该在合理范围内
        # 修复后：Alpha 基于信号值计算，应该大于 0
        alpha_pct = result.alpha_percentage
        assert 0 <= alpha_pct <= 200  # Alpha 占比应为正数（盈利信号）
        assert result.alpha > 0  # Alpha 应该为正（信号值为 0.8）

    def test_check_alpha_health_pass(self, sample_buy_order):
        """测试 Alpha 健康检查（通过）"""
        attribution = PnLAttribution(alpha_threshold=0.70)

        # 模拟高 Alpha 交易
        for i in range(10):
            order = sample_buy_order
            order.id = f"order_{i}"

            # 大量盈利，Alpha 占主导
            attribution.attribute_trade(
                order=order,
                signal_value=0.8,
                reference_price=Decimal("1500.0"),
                actual_fill_price=Decimal("1500.1"),  # 小滑点
                best_price=Decimal("1500.1"),
            )

        # 手动设置累计 Alpha 为主导（简化测试）
        attribution._cumulative_alpha = Decimal("1000.0")
        attribution._cumulative_fee = Decimal("-50.0")
        attribution._cumulative_slippage = Decimal("-50.0")
        attribution._cumulative_impact = Decimal("-50.0")
        attribution._cumulative_rebate = Decimal("0.0")
        attribution._cumulative_total = Decimal("850.0")

        is_healthy, message = attribution.check_alpha_health()
        assert is_healthy
        assert "PASS" in message

    def test_check_alpha_health_fail(self):
        """测试 Alpha 健康检查（失败）"""
        attribution = PnLAttribution(alpha_threshold=0.70)

        # 手动设置低 Alpha 场景（Alpha 占比 < 70%）
        # 修复后使用绝对值计算：alpha_pct = 200 / abs(-1000) * 100 = 20%
        attribution._cumulative_alpha = Decimal("200.0")  # 20%
        attribution._cumulative_fee = Decimal("-500.0")  # -50%
        attribution._cumulative_slippage = Decimal("-300.0")  # -30%
        attribution._cumulative_impact = Decimal("-200.0")  # -20%
        attribution._cumulative_rebate = Decimal("0.0")
        attribution._cumulative_total = Decimal("-800.0")  # 总亏损 -800

        is_healthy, message = attribution.check_alpha_health()
        assert not is_healthy
        assert "FAIL" in message

    def test_get_attribution_report(self, sample_buy_order):
        """测试归因报告生成"""
        attribution = PnLAttribution()

        # 执行一些交易
        for i in range(3):
            order = sample_buy_order
            order.id = f"order_{i}"

            attribution.attribute_trade(
                order=order,
                signal_value=0.8,
                reference_price=Decimal("1500.0"),
                actual_fill_price=Decimal("1500.5"),
                best_price=Decimal("1500.5"),
            )

        report = attribution.get_attribution_report()

        # 检查报告结构
        assert "cumulative" in report
        assert "percentages" in report
        assert "health_check" in report
        assert "trade_count" in report

        assert report["trade_count"] == 3


class TestMetricsCollector:
    """测试指标收集器"""

    def test_initialization(self):
        """测试初始化"""
        collector = MetricsCollector(
            ic_window=100,
            metrics_history=1000,
        )

        assert collector.ic_window == 100
        assert len(collector._signal_records) == 0
        assert len(collector._execution_records) == 0

    def test_record_signal(self, high_confidence_buy_signal):
        """测试记录信号"""
        collector = MetricsCollector()

        collector.record_signal(high_confidence_buy_signal, "ETH")

        assert len(collector._signal_records) == 1

        recent = collector.get_recent_signals(n=1)
        assert len(recent) == 1
        assert recent[0].symbol == "ETH"

    def test_record_execution(self, sample_buy_order):
        """测试记录执行"""
        collector = MetricsCollector()

        collector.record_execution(
            order=sample_buy_order,
            slippage_bps=5.0,
            latency_ms=15.0,
        )

        assert len(collector._execution_records) == 1

        recent = collector.get_recent_executions(n=1)
        assert len(recent) == 1
        assert recent[0].slippage_bps == 5.0
        assert recent[0].latency_ms == 15.0

    def test_calculate_ic_insufficient_data(self):
        """测试 IC 计算（数据不足）"""
        collector = MetricsCollector()

        # 少于 10 个样本
        for i in range(5):
            import time

            from src.core.types import ConfidenceLevel, SignalScore

            signal = SignalScore(
                value=0.5,
                confidence=ConfidenceLevel.MEDIUM,
                timestamp=int(time.time() * 1000),
                individual_scores=[0.2, 0.2, 0.1],
            )
            collector.record_signal(signal, "ETH", actual_return=0.01)

        ic = collector.calculate_ic()
        assert ic is None  # 数据不足

    def test_calculate_ic_with_data(self):
        """测试 IC 计算（有足够数据）"""
        collector = MetricsCollector()

        import time

        from src.core.types import ConfidenceLevel, SignalScore

        # 添加 20 个有实际收益的信号
        for i in range(20):
            signal_value = 0.5 if i % 2 == 0 else -0.5
            actual_return = 0.01 if i % 2 == 0 else -0.01

            signal = SignalScore(
                value=signal_value,
                confidence=ConfidenceLevel.MEDIUM,
                timestamp=int(time.time() * 1000),
                individual_scores=[0.2, 0.2, 0.1],
            )
            collector.record_signal(signal, "ETH", actual_return=actual_return)

        ic = collector.calculate_ic()

        # 应该有正相关（信号与收益方向一致）
        assert ic is not None
        assert -1.0 <= ic <= 1.0

    def test_get_signal_metrics(self):
        """测试获取信号指标"""
        collector = MetricsCollector()

        import time

        from src.core.types import ConfidenceLevel, SignalScore

        # 添加一些信号
        for i in range(10):
            signal = SignalScore(
                value=0.6,
                confidence=ConfidenceLevel.HIGH,
                timestamp=int(time.time() * 1000),
                individual_scores=[0.2, 0.3, 0.1],
            )
            collector.record_signal(signal, "ETH", actual_return=0.01)

        metrics = collector.get_signal_metrics()

        assert "ic" in metrics
        assert "hit_rate" in metrics
        assert "total_signals" in metrics
        assert "confidence_distribution" in metrics

        assert metrics["total_signals"] == 10

    def test_get_execution_metrics(self, sample_buy_order):
        """测试获取执行指标"""
        collector = MetricsCollector()

        # 添加一些执行记录
        for i in range(10):
            order = sample_buy_order
            order.id = f"order_{i}"

            collector.record_execution(
                order=order,
                slippage_bps=5.0 + i * 0.5,
                latency_ms=10.0 + i * 2.0,
            )

        metrics = collector.get_execution_metrics()

        assert "total_orders" in metrics
        assert "avg_slippage_bps" in metrics
        assert "avg_latency_ms" in metrics
        assert "success_rate" in metrics
        assert "latency_p50" in metrics
        assert "latency_p95" in metrics
        assert "latency_p99" in metrics

        assert metrics["total_orders"] == 10
        assert metrics["success_rate"] == 1.0  # 所有订单都 FILLED

    def test_get_metrics_summary(self):
        """测试获取指标摘要"""
        collector = MetricsCollector()

        import time

        from src.core.types import ConfidenceLevel, SignalScore

        # 添加一些数据
        signal = SignalScore(
            value=0.5,
            confidence=ConfidenceLevel.MEDIUM,
            timestamp=int(time.time() * 1000),
            individual_scores=[0.2, 0.2, 0.1],
        )
        collector.record_signal(signal, "ETH")

        summary = collector.get_metrics_summary()

        assert "timestamp" in summary
        assert "signal_quality" in summary
        assert "execution_quality" in summary

    def test_hit_rate_calculation(self):
        """测试命中率计算"""
        collector = MetricsCollector()

        import time

        from src.core.types import ConfidenceLevel, SignalScore

        # 添加信号：5个命中，5个未命中
        for i in range(10):
            signal_value = 0.5 if i < 5 else -0.5
            actual_return = 0.01 if i < 5 else 0.01  # 前5个方向对，后5个方向错

            signal = SignalScore(
                value=signal_value,
                confidence=ConfidenceLevel.MEDIUM,
                timestamp=int(time.time() * 1000),
                individual_scores=[0.2, 0.2, 0.1],
            )
            collector.record_signal(signal, "ETH", actual_return=actual_return)

        metrics = collector.get_signal_metrics()
        hit_rate = metrics["hit_rate"]

        # 命中率应该是 50%
        assert 0.45 <= hit_rate <= 0.55

    def test_confidence_distribution(self):
        """测试置信度分布统计"""
        collector = MetricsCollector()

        import time

        from src.core.types import ConfidenceLevel, SignalScore

        # 添加不同置信度的信号
        for _ in range(5):
            high_signal = SignalScore(
                value=0.8,
                confidence=ConfidenceLevel.HIGH,
                timestamp=int(time.time() * 1000),
                individual_scores=[0.3, 0.3, 0.2],
            )
            collector.record_signal(high_signal, "ETH")

        for _ in range(3):
            medium_signal = SignalScore(
                value=0.6,
                confidence=ConfidenceLevel.MEDIUM,
                timestamp=int(time.time() * 1000),
                individual_scores=[0.2, 0.3, 0.1],
            )
            collector.record_signal(medium_signal, "ETH")

        metrics = collector.get_signal_metrics()
        distribution = metrics["confidence_distribution"]

        assert distribution.get("HIGH", 0) == 5
        assert distribution.get("MEDIUM", 0) == 3

    def test_latency_percentiles(self, sample_buy_order):
        """测试延迟分位数计算"""
        collector = MetricsCollector()

        # 添加一系列延迟数据
        latencies = [10, 15, 20, 25, 30, 35, 40, 50, 100, 200]

        for i, latency in enumerate(latencies):
            order = sample_buy_order
            order.id = f"order_{i}"

            collector.record_execution(
                order=order,
                slippage_bps=5.0,
                latency_ms=float(latency),
            )

        metrics = collector.get_execution_metrics()

        # 使用精确分位数断言（允许小误差）
        # 输入: [10, 15, 20, 25, 30, 35, 40, 50, 100, 200]
        # NumPy 使用线性插值计算分位数：
        # P50 (中位数) = (30 + 35) / 2 = 32.5
        # P95 = 100 + 0.55 * (200 - 100) = 155
        # P99 = 100 + 0.95 * (200 - 100) = 191
        assert abs(metrics["latency_p50"] - 32.5) < 1.0  # 允许 ±1ms 误差

        assert abs(metrics["latency_p95"] - 155.0) < 1.0  # P95 应该在 155 ±1ms

        assert abs(metrics["latency_p99"] - 191.0) < 1.0  # P99 应该在 191 ±1ms
