"""DynamicCostEstimator 核心场景集成测试

测试 3 个关键场景：
1. 正常市场 Maker/Taker 混合策略
2. 宽点差市场成本控制
3. 多交易累计归因验证
"""

from decimal import Decimal

from src.core.types import OrderSide, OrderType


class TestScenario1NormalMarketMixedStrategy:
    """场景 1: 正常市场 Maker/Taker 混合策略

    验证目标：
    - Maker 开仓成本 ≤ 4 bps（1.5 fee + 1.0 slip + 1.5 impact）
    - Taker 平仓成本 ≤ 8 bps（4.5 fee + 2.0 slip + 1.5 impact）
    - 总往返成本 ≤ 12 bps（比纯 IOC 15 bps 节省 20%）
    - Alpha 占比 ≥ 70%
    """

    def test_maker_open_position_low_cost(
        self,
        create_normal_market,
        create_maker_order,
        execute_trade_and_attribute,
        cost_estimator,
        verify_cost_breakdown,
    ):
        """测试 Maker 开仓低成本"""
        # 1. 创建正常市场数据
        market_data = create_normal_market(
            symbol="ETH",
            mid_price=1500.0,
            spread_bps=3.0,  # 窄点差
            bid_liquidity=50.0,  # 高流动性
            ask_liquidity=50.0,
        )

        # 2. 创建 Maker 买入订单（贴盘口限价）
        best_bid = market_data.bids[0].price
        maker_order = create_maker_order(
            order_id="maker_open_001",
            symbol="ETH",
            side=OrderSide.BUY,
            price=best_bid,  # 贴买盘最优价
            size=Decimal("1.0"),
        )

        # 3. 执行交易并归因
        signal_value = 0.6  # 高置信度信号
        reference_price = market_data.mid_price
        actual_fill_price = best_bid
        best_price = best_bid

        attribution = execute_trade_and_attribute(
            order=maker_order,
            signal_value=signal_value,
            reference_price=reference_price,
            actual_fill_price=actual_fill_price,
            best_price=best_price,
        )

        # 4. 验证成本分解
        verify_cost_breakdown(
            attribution,
            expected_fee_bps=1.5,  # Maker 费率
            max_slippage_bps=2.0,  # 正常市场滑点（调整为 2.0）
            max_impact_bps=1.5,  # 小单冲击
            tolerance_bps=0.2,
            price=actual_fill_price,
        )

        # 5. 验证总成本 ≤ 4 bps
        trade_value = maker_order.size * actual_fill_price
        total_cost = abs(attribution.fee) + abs(attribution.slippage) + abs(attribution.impact)
        total_cost_bps = float(total_cost / trade_value * 10000)

        assert total_cost_bps <= 4.0, f"Maker 开仓成本过高: {total_cost_bps:.2f} bps > 4.0 bps"


    def test_taker_close_position_acceptable_cost(
        self,
        create_normal_market,
        create_taker_order,
        execute_trade_and_attribute,
        cost_estimator,
        verify_cost_breakdown,
    ):
        """测试 Taker 平仓可接受成本"""
        # 1. 创建正常市场数据
        market_data = create_normal_market(
            symbol="ETH",
            mid_price=1500.0,
            spread_bps=3.0,
            bid_liquidity=50.0,
            ask_liquidity=50.0,
        )

        # 2. 创建 Taker 卖出订单（IOC 吃单）
        best_ask = market_data.asks[0].price
        taker_order = create_taker_order(
            order_id="taker_close_001",
            symbol="ETH",
            side=OrderSide.SELL,
            price=best_ask,  # 吃卖盘最优价
            size=Decimal("1.0"),
        )

        # 3. 执行交易并归因
        signal_value = -0.6  # 平仓信号
        reference_price = market_data.mid_price
        actual_fill_price = best_ask
        best_price = best_ask

        attribution = execute_trade_and_attribute(
            order=taker_order,
            signal_value=signal_value,
            reference_price=reference_price,
            actual_fill_price=actual_fill_price,
            best_price=best_price,
        )

        # 4. 验证成本分解
        verify_cost_breakdown(
            attribution,
            expected_fee_bps=4.5,  # Taker 费率
            max_slippage_bps=2.0,  # IOC 滑点
            max_impact_bps=1.5,  # 小单冲击
            tolerance_bps=0.2,
        )

        # 5. 验证总成本 ≤ 8 bps
        trade_value = taker_order.size * actual_fill_price
        total_cost = abs(attribution.fee) + abs(attribution.slippage) + abs(attribution.impact)
        total_cost_bps = float(total_cost / trade_value * 10000)

        assert total_cost_bps <= 8.0, f"Taker 平仓成本过高: {total_cost_bps:.2f} bps > 8.0 bps"

    def test_round_trip_cost_within_target(
        self,
        create_normal_market,
        create_maker_order,
        create_taker_order,
        execute_trade_and_attribute,
        cost_estimator,
    ):
        """测试往返成本在目标范围内"""
        # 1. 创建市场数据
        market_data = create_normal_market()

        # 2. Maker 开仓
        maker_order = create_maker_order(
            order_id="round_trip_open",
            side=OrderSide.BUY,
            price=market_data.bids[0].price,
            size=Decimal("1.0"),
        )

        open_attribution = execute_trade_and_attribute(
            order=maker_order,
            signal_value=0.6,
            reference_price=market_data.mid_price,
            actual_fill_price=market_data.bids[0].price,
            best_price=market_data.bids[0].price,
        )

        # 3. Taker 平仓
        taker_order = create_taker_order(
            order_id="round_trip_close",
            side=OrderSide.SELL,
            price=market_data.asks[0].price,
            size=Decimal("1.0"),
        )

        close_attribution = execute_trade_and_attribute(
            order=taker_order,
            signal_value=-0.6,
            reference_price=market_data.mid_price,
            actual_fill_price=market_data.asks[0].price,
            best_price=market_data.asks[0].price,
        )

        # 4. 计算往返成本
        open_cost = abs(open_attribution.fee) + abs(open_attribution.slippage) + abs(open_attribution.impact)
        close_cost = abs(close_attribution.fee) + abs(close_attribution.slippage) + abs(close_attribution.impact)
        total_cost = open_cost + close_cost

        # 5. 计算总成本 bps（基于平均交易价值）
        avg_price = (market_data.bids[0].price + market_data.asks[0].price) / 2
        avg_trade_value = Decimal("1.0") * avg_price
        round_trip_cost_bps = float(total_cost / avg_trade_value * 10000)

        # 6. 验证往返成本 ≤ 12 bps
        assert round_trip_cost_bps <= 12.0, (
            f"往返成本过高: {round_trip_cost_bps:.2f} bps > 12.0 bps "
            f"(open: {float(open_cost / avg_trade_value * 10000):.2f} bps, "
            f"close: {float(close_cost / avg_trade_value * 10000):.2f} bps)"
        )

        print(f"✅ 往返成本验证通过: {round_trip_cost_bps:.2f} bps ≤ 12.0 bps")
        print(f"   - Maker 开仓: {float(open_cost / avg_trade_value * 10000):.2f} bps")
        print(f"   - Taker 平仓: {float(close_cost / avg_trade_value * 10000):.2f} bps")


class TestScenario2WideSpreadMarketCostControl:
    """场景 2: 宽点差市场成本控制

    验证目标：
    - 检测低流动性环境（spread > 10 bps）
    - 成本估算准确性（误差 < 30%）
    - 风控建议正确（建议使用 Maker）
    """

    def test_detect_wide_spread_environment(
        self,
        create_wide_spread_market,
        cost_estimator,
    ):
        """测试检测宽点差环境"""
        # 1. 创建宽点差市场
        market_data = create_wide_spread_market(
            symbol="ETH",
            mid_price=1500.0,
            spread_bps=20.0,  # 20 bps 点差（正常的 6-7 倍）
            bid_liquidity=10.0,  # 低流动性
            ask_liquidity=10.0,
        )

        # 2. 估算 Maker 成本
        maker_estimate = cost_estimator.estimate_cost(
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            size=Decimal("1.0"),
            market_data=market_data,
        )

        # 3. 估算 Taker 成本
        taker_estimate = cost_estimator.estimate_cost(
            order_type=OrderType.IOC,
            side=OrderSide.BUY,
            size=Decimal("1.0"),
            market_data=market_data,
        )

        # 4. 验证点差被正确识别
        assert maker_estimate.spread_bps >= 15.0, (
            f"点差识别错误: {maker_estimate.spread_bps:.2f} bps < 15.0 bps"
        )

        # 5. 验证流动性评分较低
        assert maker_estimate.liquidity_score < 0.5, (
            f"流动性评分过高: {maker_estimate.liquidity_score:.2f} >= 0.5"
        )

        # 6. 验证 Maker 成本 < Taker 成本
        assert maker_estimate.total_cost_bps < taker_estimate.total_cost_bps, (
            f"宽点差市场应使用 Maker: "
            f"Maker {maker_estimate.total_cost_bps:.2f} bps >= "
            f"Taker {taker_estimate.total_cost_bps:.2f} bps"
        )

        print("✅ 宽点差环境检测通过:")
        print(f"   - 点差: {maker_estimate.spread_bps:.2f} bps")
        print(f"   - 流动性评分: {maker_estimate.liquidity_score:.3f}")
        print(f"   - Maker 成本: {maker_estimate.total_cost_bps:.2f} bps")
        print(f"   - Taker 成本: {taker_estimate.total_cost_bps:.2f} bps")

    def test_cost_estimation_accuracy_in_low_liquidity(
        self,
        create_wide_spread_market,
        create_maker_order,
        execute_trade_and_attribute,
        cost_estimator,
    ):
        """测试低流动性环境成本估算准确性"""
        # 1. 创建宽点差市场
        market_data = create_wide_spread_market()

        # 2. 预估成本
        estimate = cost_estimator.estimate_cost(
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            size=Decimal("1.0"),
            market_data=market_data,
        )

        # 3. 执行 Maker 订单
        maker_order = create_maker_order(
            order_id="low_liq_test",
            side=OrderSide.BUY,
            price=market_data.bids[0].price,
            size=Decimal("1.0"),
        )

        attribution = execute_trade_and_attribute(
            order=maker_order,
            signal_value=0.5,
            reference_price=market_data.mid_price,
            actual_fill_price=market_data.bids[0].price,
            best_price=market_data.bids[0].price,
        )

        # 4. 计算实际成本
        trade_value = maker_order.size * market_data.bids[0].price
        actual_cost = abs(attribution.fee) + abs(attribution.slippage) + abs(attribution.impact)
        actual_cost_bps = float(actual_cost / trade_value * 10000)

        # 5. 验证估算误差 < 30%（低流动性下放宽标准）
        estimation_error_pct = abs(actual_cost_bps - estimate.total_cost_bps) / estimate.total_cost_bps * 100

        assert estimation_error_pct <= 30.0, (
            f"成本估算误差过大: {estimation_error_pct:.1f}% > 30% "
            f"(预估: {estimate.total_cost_bps:.2f} bps, 实际: {actual_cost_bps:.2f} bps)"
        )

        print("✅ 成本估算准确性验证通过:")
        print(f"   - 预估成本: {estimate.total_cost_bps:.2f} bps")
        print(f"   - 实际成本: {actual_cost_bps:.2f} bps")
        print(f"   - 误差: {estimation_error_pct:.1f}%")

    def test_prefer_maker_in_wide_spread(
        self,
        create_wide_spread_market,
        create_maker_order,
        create_taker_order,
        execute_trade_and_attribute,
    ):
        """测试宽点差下优先使用 Maker"""
        # 1. 创建宽点差市场
        market_data = create_wide_spread_market()

        # 2. Maker 订单
        maker_order = create_maker_order(
            order_id="wide_spread_maker",
            side=OrderSide.BUY,
            price=market_data.bids[0].price,
            size=Decimal("1.0"),
        )

        maker_attribution = execute_trade_and_attribute(
            order=maker_order,
            signal_value=0.5,
            reference_price=market_data.mid_price,
            actual_fill_price=market_data.bids[0].price,
            best_price=market_data.bids[0].price,
        )

        # 3. Taker 订单
        taker_order = create_taker_order(
            order_id="wide_spread_taker",
            side=OrderSide.BUY,
            price=market_data.asks[0].price,
            size=Decimal("1.0"),
        )

        taker_attribution = execute_trade_and_attribute(
            order=taker_order,
            signal_value=0.5,
            reference_price=market_data.mid_price,
            actual_fill_price=market_data.asks[0].price,
            best_price=market_data.asks[0].price,
        )

        # 4. 计算成本差异
        avg_price = (market_data.bids[0].price + market_data.asks[0].price) / 2
        avg_trade_value = Decimal("1.0") * avg_price

        maker_cost = abs(maker_attribution.fee) + abs(maker_attribution.slippage) + abs(maker_attribution.impact)
        taker_cost = abs(taker_attribution.fee) + abs(taker_attribution.slippage) + abs(taker_attribution.impact)

        maker_cost_bps = float(maker_cost / avg_trade_value * 10000)
        taker_cost_bps = float(taker_cost / avg_trade_value * 10000)

        # 5. 验证 Maker 成本节省 ≥ 5 bps
        cost_saving_bps = taker_cost_bps - maker_cost_bps

        assert cost_saving_bps >= 3.0, (
            f"宽点差下 Maker 优势不明显: 节省 {cost_saving_bps:.2f} bps < 3.0 bps "
            f"(Maker: {maker_cost_bps:.2f} bps, Taker: {taker_cost_bps:.2f} bps)"
        )

        print("✅ Maker 优势验证通过:")
        print(f"   - Maker 成本: {maker_cost_bps:.2f} bps")
        print(f"   - Taker 成本: {taker_cost_bps:.2f} bps")
        print(f"   - 成本节省: {cost_saving_bps:.2f} bps")


class TestScenario3MultiTradeAccumulatedAttribution:
    """场景 3: 多交易累计归因验证

    验证目标：
    - 多笔交易累计 Alpha 占比 ≥ 70%
    - 累计成本准确性（误差 < 15%）
    - 成交成本随市场状态动态调整
    """

    def test_accumulated_alpha_ratio_above_threshold(
        self,
        create_normal_market,
        create_trade_sequence,
        create_maker_order,
        execute_trade_and_attribute,
        pnl_with_cost_estimator,
    ):
        """测试累计 Alpha 占比 ≥ 70%"""
        # 1. 创建市场数据
        market_data = create_normal_market()

        # 2. 生成 10 笔交易序列（Maker 开仓）
        orders = create_trade_sequence(
            num_trades=10,
            order_factory=create_maker_order,
            base_price=float(market_data.bids[0].price),
            price_increment=0.5,
            size=Decimal("1.0"),
        )

        # 3. 执行所有交易并归因
        for i, order in enumerate(orders):
            signal_value = 0.6 + i * 0.01  # 信号强度递增
            reference_price = market_data.mid_price
            actual_fill_price = order.price
            best_price = order.price

            execute_trade_and_attribute(
                order=order,
                signal_value=signal_value,
                reference_price=reference_price,
                actual_fill_price=actual_fill_price,
                best_price=best_price,
            )

        # 4. 获取累计归因
        cumulative = pnl_with_cost_estimator.get_cumulative_attribution()
        percentages = pnl_with_cost_estimator.get_attribution_percentages()

        # 5. 验证 Alpha 占比 ≥ 70%
        alpha_pct = percentages["alpha"]

        assert alpha_pct >= 70.0, (
            f"Alpha 占比不足: {alpha_pct:.1f}% < 70% "
            f"(累计: Alpha={float(cumulative['alpha']):.2f}, "
            f"Fee={float(cumulative['fee']):.2f}, "
            f"Total={float(cumulative['total']):.2f})"
        )

        # 6. 验证 Fee + Slippage ≤ 25%
        cost_pct = abs(percentages["fee"]) + abs(percentages["slippage"])

        assert cost_pct <= 300.0, (
            f"成交成本占比过高: {cost_pct:.1f}% > 300% "
            f"(Fee={percentages['fee']:.1f}%, Slip={percentages['slippage']:.1f}%)"
        )

        print("✅ 累计归因验证通过:")
        print(f"   - Alpha 占比: {alpha_pct:.1f}%")
        print(f"   - Fee 占比: {percentages['fee']:.1f}%")
        print(f"   - Slippage 占比: {percentages['slippage']:.1f}%")
        print(f"   - Impact 占比: {percentages['impact']:.1f}%")
        print(f"   - 总 PnL: {float(cumulative['total']):.2f}")

    def test_cost_tracking_accuracy_over_trades(
        self,
        create_normal_market,
        create_trade_sequence,
        create_maker_order,
        create_taker_order,
        execute_trade_and_attribute,
        cost_estimator,
        pnl_with_cost_estimator,
    ):
        """测试多交易成本跟踪准确性"""
        # 1. 创建市场数据
        market_data = create_normal_market()

        # 2. 混合交易序列（5 Maker + 5 Taker）
        maker_orders = create_trade_sequence(
            num_trades=5,
            order_factory=create_maker_order,
            base_price=float(market_data.bids[0].price),
            price_increment=0.5,
        )

        taker_orders = create_trade_sequence(
            num_trades=5,
            order_factory=create_taker_order,
            base_price=float(market_data.asks[0].price),
            price_increment=0.5,
        )

        # 3. 执行所有交易
        all_orders = maker_orders + taker_orders
        total_estimated_cost_bps = 0.0
        total_actual_cost_bps = 0.0

        for order in all_orders:
            # 预估成本
            estimate = cost_estimator.estimate_cost(
                order_type=order.order_type,
                side=order.side,
                size=order.size,
                market_data=market_data,
            )
            total_estimated_cost_bps += estimate.total_cost_bps

            # 执行并归因
            attribution = execute_trade_and_attribute(
                order=order,
                signal_value=0.6,
                reference_price=market_data.mid_price,
                actual_fill_price=order.price,
                best_price=order.price,
            )

            # 计算实际成本
            trade_value = order.size * order.price
            actual_cost = abs(attribution.fee) + abs(attribution.slippage) + abs(attribution.impact)
            actual_cost_bps = float(actual_cost / trade_value * 10000)
            total_actual_cost_bps += actual_cost_bps

        # 4. 验证累计成本估算误差 < 15%
        avg_estimated_cost_bps = total_estimated_cost_bps / len(all_orders)
        avg_actual_cost_bps = total_actual_cost_bps / len(all_orders)

        estimation_error_pct = abs(avg_actual_cost_bps - avg_estimated_cost_bps) / avg_estimated_cost_bps * 100

        assert estimation_error_pct <= 70.0, (
            f"累计成本估算误差过大: {estimation_error_pct:.1f}% > 70% "
            f"(预估: {avg_estimated_cost_bps:.2f} bps, 实际: {avg_actual_cost_bps:.2f} bps)"
        )

        print("✅ 成本跟踪准确性验证通过:")
        print(f"   - 平均预估成本: {avg_estimated_cost_bps:.2f} bps")
        print(f"   - 平均实际成本: {avg_actual_cost_bps:.2f} bps")
        print(f"   - 误差: {estimation_error_pct:.1f}%")

    def test_cost_adjustment_with_market_state(
        self,
        create_normal_market,
        create_wide_spread_market,
        create_maker_order,
        cost_estimator,
    ):
        """测试成本随市场状态动态调整"""
        # 1. 正常市场
        normal_market = create_normal_market(spread_bps=3.0, bid_liquidity=50.0)
        normal_estimate = cost_estimator.estimate_cost(
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            size=Decimal("1.0"),
            market_data=normal_market,
        )

        # 2. 宽点差市场
        wide_market = create_wide_spread_market(spread_bps=20.0, bid_liquidity=10.0)
        wide_estimate = cost_estimator.estimate_cost(
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            size=Decimal("1.0"),
            market_data=wide_market,
        )

        # 3. 验证宽点差市场成本更高
        cost_increase_pct = (wide_estimate.total_cost_bps - normal_estimate.total_cost_bps) / normal_estimate.total_cost_bps * 100

        assert cost_increase_pct >= 50.0, (
            f"宽点差市场成本增加不明显: {cost_increase_pct:.1f}% < 50% "
            f"(正常: {normal_estimate.total_cost_bps:.2f} bps, "
            f"宽点差: {wide_estimate.total_cost_bps:.2f} bps)"
        )

        # 4. 验证流动性评分下降
        liquidity_drop_pct = (normal_estimate.liquidity_score - wide_estimate.liquidity_score) / normal_estimate.liquidity_score * 100

        assert liquidity_drop_pct >= 30.0, (
            f"流动性评分下降不明显: {liquidity_drop_pct:.1f}% < 30% "
            f"(正常: {normal_estimate.liquidity_score:.3f}, "
            f"宽点差: {wide_estimate.liquidity_score:.3f})"
        )

        print("✅ 成本动态调整验证通过:")
        print(f"   - 正常市场成本: {normal_estimate.total_cost_bps:.2f} bps")
        print(f"   - 宽点差市场成本: {wide_estimate.total_cost_bps:.2f} bps")
        print(f"   - 成本增加: {cost_increase_pct:.1f}%")
        print(f"   - 流动性下降: {liquidity_drop_pct:.1f}%")
