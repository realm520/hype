"""信号基类

所有信号必须继承此基类并实现 calculate 方法。
"""

from abc import ABC, abstractmethod

from src.core.types import MarketData


class BaseSignal(ABC):
    """信号基类"""

    def __init__(self, weight: float = 1.0):
        """
        初始化信号

        Args:
            weight: 信号权重
        """
        self.weight = weight
        self._last_value: float | None = None

    @abstractmethod
    def calculate(self, market_data: MarketData) -> float:
        """
        计算信号值

        Args:
            market_data: 市场数据

        Returns:
            float: 信号值（-1 到 1）
        """
        pass

    def validate(self) -> bool:
        """
        验证信号是否有效

        Returns:
            bool: 信号是否有效
        """
        return True

    def get_weight(self) -> float:
        """获取信号权重"""
        return self.weight

    @property
    def last_value(self) -> float | None:
        """获取上次计算的信号值"""
        return self._last_value

    def _normalize(self, value: float, min_val: float = -1.0, max_val: float = 1.0) -> float:
        """
        归一化信号值到指定范围

        Args:
            value: 原始值
            min_val: 最小值
            max_val: 最大值

        Returns:
            float: 归一化后的值
        """
        return max(min_val, min(max_val, value))

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(weight={self.weight})"
