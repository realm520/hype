"""Analytics layer module

Provides PnL attribution and metrics collection.
"""

from src.analytics.metrics import ExecutionRecord, MetricsCollector, SignalRecord
from src.analytics.pnl_attribution import PnLAttribution, TradeAttribution

__all__ = [
    "PnLAttribution",
    "TradeAttribution",
    "MetricsCollector",
    "SignalRecord",
    "ExecutionRecord",
]
