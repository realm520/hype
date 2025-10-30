"""核心数据类型定义

Week 1 核心数据模型，包括订单簿、信号、执行结果等。
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class ConfidenceLevel(Enum):
    """信号置信度等级"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OrderSide(Enum):
    """订单方向"""

    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """订单类型"""

    IOC = "ioc"  # Immediate-Or-Cancel
    LIMIT = "limit"  # 限价单（Week 2）
    MARKET = "market"  # 市价单（不使用）


class OrderStatus(Enum):
    """订单状态"""

    PENDING = "pending"
    CREATED = "created"
    SUBMITTED = "submitted"
    PARTIAL_FILLED = "partial_filled"
    PARTIALLY_FILLED = "partial_filled"  # 别名，向后兼容
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Level:
    """订单簿档位"""

    price: Decimal
    size: Decimal

    def __post_init__(self) -> None:
        """确保类型正确"""
        if not isinstance(self.price, Decimal):
            self.price = Decimal(str(self.price))
        if not isinstance(self.size, Decimal):
            self.size = Decimal(str(self.size))


@dataclass
class OrderBookSnapshot:
    """订单簿快照"""

    symbol: str
    timestamp: int  # Unix timestamp (ms)
    bids: list[Level]
    asks: list[Level]
    mid_price: Decimal

    @property
    def spread(self) -> Decimal:
        """计算买卖价差"""
        if self.bids and self.asks:
            return self.asks[0].price - self.bids[0].price
        return Decimal("0")

    @property
    def spread_bps(self) -> float:
        """计算买卖价差（bps）"""
        if self.mid_price > 0:
            return float(self.spread / self.mid_price * 10000)
        return 0.0


@dataclass
class Trade:
    """成交记录"""

    symbol: str
    timestamp: int
    price: Decimal
    size: Decimal
    side: OrderSide


@dataclass
class MarketData:
    """市场数据（订单簿 + 最近成交）"""

    symbol: str
    timestamp: int
    bids: list[Level]
    asks: list[Level]
    mid_price: Decimal
    trades: list[Trade] = field(default_factory=list)

    @property
    def best_bid(self) -> Level | None:
        """最优买价"""
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Level | None:
        """最优卖价"""
        return self.asks[0] if self.asks else None


@dataclass
class SignalScore:
    """信号评分"""

    value: float  # 信号值（-1 到 1）
    confidence: ConfidenceLevel  # 置信度等级
    individual_scores: list[float]  # 各信号分值
    timestamp: int

    def __post_init__(self) -> None:
        """验证信号值范围"""
        if not -1.0 <= self.value <= 1.0:
            raise ValueError(f"Signal value {self.value} out of range [-1, 1]")


@dataclass
class Position:
    """持仓信息

    Week 2 扩展：
        - open_timestamp: 开仓时间戳（用于超时平仓检测）
        - side: 持仓方向（用于平仓逻辑和审计日志）
        - current_price: 当前价格（用于 PnL 计算和 TP/SL 检测）
    """

    symbol: str
    size: Decimal  # 正数=多头，负数=空头
    entry_price: Decimal | None = None
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")

    # Week 2 Phase 2 新增字段
    open_timestamp: int | None = None  # 开仓时间戳（毫秒）
    side: "OrderSide | None" = None  # 持仓方向（BUY/SELL）
    current_price: Decimal = Decimal("0")  # 当前价格

    @property
    def position_value_usd(self) -> Decimal:
        """持仓价值（USD）"""
        return abs(self.size) * self.current_price

    @property
    def is_long(self) -> bool:
        """是否多头"""
        return self.size > 0

    @property
    def is_short(self) -> bool:
        """是否空头"""
        return self.size < 0

    @property
    def is_flat(self) -> bool:
        """是否平仓"""
        return self.size == 0


@dataclass
class Order:
    """订单"""

    id: str
    symbol: str
    side: OrderSide
    size: Decimal
    price: Decimal
    order_type: OrderType
    status: OrderStatus
    created_at: int
    filled_size: Decimal = Decimal("0")
    avg_fill_price: Decimal | None = None
    error_message: str | None = None


@dataclass
class ExecutionResult:
    """执行结果"""

    order_id: str
    fill_price: Decimal
    fill_size: Decimal
    expected_price: Decimal
    slippage: Decimal
    timestamp: int

    @property
    def slippage_bps(self) -> float:
        """计算滑点（bps）"""
        if self.expected_price > 0:
            return float(
                abs(self.fill_price - self.expected_price) / self.expected_price * 10000
            )
        return 0.0


@dataclass
class Attribution:
    """PnL 归因"""

    alpha: Decimal  # 方向性收益
    fee: Decimal  # 手续费
    slippage: Decimal  # 滑点
    impact: Decimal  # 冲击
    rebate: Decimal  # 回扣
    total_pnl: Decimal  # 总盈亏

    @property
    def alpha_percentage(self) -> float:
        """Alpha 占比（%）

        使用绝对值计算，确保盈利和亏损时语义一致
        """
        if self.total_pnl != 0:
            return float(self.alpha / abs(self.total_pnl) * 100)
        return 0.0

    @property
    def cost_percentage(self) -> float:
        """成本占比（%）

        使用绝对值计算，确保盈利和亏损时语义一致
        """
        if self.total_pnl != 0:
            total_cost = self.fee + self.slippage + self.impact
            return float(total_cost / abs(self.total_pnl) * 100)
        return 0.0


@dataclass
class AttributionSummary:
    """PnL 归因汇总"""

    alpha: Decimal
    fee: Decimal
    slippage: Decimal
    impact: Decimal
    rebate: Decimal
    total_pnl: Decimal
    alpha_percentage: float
    cost_percentage: float
    num_trades: int


@dataclass
class RiskCheckResult:
    """风控检查结果"""

    approved: bool
    reason: str | None = None
    severity: str = "info"  # info | warning | critical
