"""核心常量定义

本模块定义项目中使用的核心常量，包括费率、限制、阈值等。
"""

from decimal import Decimal

# ============================================================================
# Hyperliquid 费率配置（2025年1月，Level 0）
# ============================================================================

# Taker 费率（接盘方 / IOC 订单）
HYPERLIQUID_TAKER_FEE_RATE = Decimal("0.00045")  # 0.0450% = 4.5 bps

# Maker 费率（挂单方 / 限价单）
HYPERLIQUID_MAKER_FEE_RATE = Decimal("0.00015")  # 0.0150% = 1.5 bps

# 费率说明文档
FEE_NOTES = """
Hyperliquid 永续合约费率结构（Level 0，14天成交量 ≤ $5,000,000）:

1. Taker（接盘方/IOC）：+0.0450%（支付手续费）
   - 消耗流动性，立即成交
   - 使用场景：IOC 订单、高置信度交易

2. Maker（挂单方/限价单）：+0.0150%（支付手续费，不是 rebate）
   - 提供流动性，等待成交
   - 使用场景：浅被动限价单、中置信度交易
   - 注意：Maker 不是负费率（rebate），是正费率，只是比 Taker 便宜 3 bps

3. 做市商返佣等级（需要高成交量占比）：
   - Level 1（>0.50%）：Maker -0.001%（真正的 rebate）
   - Level 2（>1.50%）：Maker -0.002%
   - Level 3（>3.00%）：Maker -0.003%

4. VIP 等级（基于14天成交量）：
   - Level 1（>$5M）：Taker 0.0400%，Maker 0.0120%
   - Level 2（>$25M）：Taker 0.0350%，Maker 0.0080%
   - Level 3（>$100M）：Taker 0.0300%，Maker 0.0040%
   - ...（更高等级费率更低）

参考：https://hyperliquid.xyz/fees
最后更新：2025-10-28
"""

# ============================================================================
# Week 1 vs Week 2 成本对比
# ============================================================================

# Week 1（IOC-only 基线）
WEEK1_AVG_FEE_BPS = 4.5  # 100% Taker

# Week 2（混合执行模式，30% Taker + 70% Maker）
WEEK2_EXPECTED_TAKER_RATIO = 0.30
WEEK2_EXPECTED_MAKER_RATIO = 0.70
WEEK2_AVG_FEE_BPS = (
    WEEK2_EXPECTED_TAKER_RATIO * 4.5 + WEEK2_EXPECTED_MAKER_RATIO * 1.5
)  # = 2.4 bps

# 成本节省
FEE_SAVINGS_BPS = WEEK1_AVG_FEE_BPS - WEEK2_AVG_FEE_BPS  # 2.1 bps
FEE_SAVINGS_PCT = FEE_SAVINGS_BPS / WEEK1_AVG_FEE_BPS  # 46.7%

# ============================================================================
# 其他常量（预留）
# ============================================================================

# 最大滑点容忍度（bps）
MAX_SLIPPAGE_BPS = Decimal("10")  # 10 bps

# 最大单笔交易尺寸（USD）
MAX_SINGLE_TRADE_SIZE = Decimal("100000")  # $100,000
