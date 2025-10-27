"""Execution layer module

Provides IOC order execution and management.
"""

from src.execution.ioc_executor import IOCExecutor
from src.execution.order_manager import OrderManager
from src.execution.slippage_estimator import SlippageEstimator

__all__ = [
    "IOCExecutor",
    "SlippageEstimator",
    "OrderManager",
]
