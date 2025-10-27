"""Signal layer module

Provides signal calculation and aggregation.
"""

from src.signals.aggregator import SignalAggregator, create_aggregator_from_config
from src.signals.base import BaseSignal
from src.signals.impact import ImpactSignal
from src.signals.microprice import MicropriceSignal
from src.signals.obi import OBISignal

__all__ = [
    "BaseSignal",
    "OBISignal",
    "MicropriceSignal",
    "ImpactSignal",
    "SignalAggregator",
    "create_aggregator_from_config",
]
