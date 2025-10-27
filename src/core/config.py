"""配置加载器

从 YAML 文件和环境变量加载配置。
"""

from pathlib import Path
from typing import Any, cast

import structlog
import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger()


class RiskConfig(BaseModel):
    """风控配置

    所有百分比参数使用小数形式（0.008 表示 0.8%）
    """

    max_single_loss_pct: float = Field(
        default=0.008,
        description="单笔最大亏损比例（小数，0.008 = 0.8%）",
        gt=0,
        lt=1,
    )
    max_daily_drawdown_pct: float = Field(
        default=0.05,
        description="日最大回撤比例（小数，0.05 = 5%）",
        gt=0,
        lt=1,
    )
    max_position_size_usd: float = Field(
        default=10000,
        description="最大持仓（USD）",
        gt=0,
    )

    @field_validator("max_single_loss_pct", "max_daily_drawdown_pct")
    @classmethod
    def validate_percentage(cls, v: float, info) -> float:
        """验证百分比参数范围

        确保所有百分比参数在 (0, 1) 范围内
        """
        if not (0 < v < 1):
            raise ValueError(
                f"{info.field_name} must be between 0 and 1 (exclusive), "
                f"got {v}. Use decimal form: 0.008 for 0.8%"
            )
        return v


class SignalThresholdsConfig(BaseModel):
    """信号阈值配置"""

    theta_1: float = Field(
        default=0.5,
        description="高置信度阈值",
        ge=0,
        le=1,
    )
    theta_2: float = Field(
        default=0.2,
        description="中置信度阈值",
        ge=0,
        le=1,
    )

    @field_validator("theta_2")
    @classmethod
    def validate_threshold_order(cls, v: float, info) -> float:
        """验证阈值顺序

        确保 theta_2 < theta_1
        """
        # 注意：这里无法直接访问 theta_1，需要在模型级别验证
        return v

    def model_post_init(self, __context) -> None:
        """模型后验证：确保阈值顺序正确"""
        if self.theta_2 >= self.theta_1:
            raise ValueError(
                f"theta_2 ({self.theta_2}) must be less than theta_1 ({self.theta_1})"
            )


class SignalConfig(BaseModel):
    """信号配置"""

    thresholds: SignalThresholdsConfig = Field(default_factory=lambda: SignalThresholdsConfig())
    obi_levels: int = Field(default=5, description="OBI 档位数", ge=1, le=20)
    obi_weight: float = Field(default=0.4, description="OBI 权重", ge=0, le=1)
    microprice_weight: float = Field(default=0.3, description="Microprice 权重", ge=0, le=1)
    impact_window_ms: int = Field(default=100, description="Impact 窗口（毫秒）", ge=10, le=10000)
    impact_weight: float = Field(default=0.3, description="Impact 权重", ge=0, le=1)

    def model_post_init(self, __context) -> None:
        """模型后验证：确保权重总和接近 1.0"""
        total_weight = self.obi_weight + self.microprice_weight + self.impact_weight
        if not (0.99 <= total_weight <= 1.01):
            raise ValueError(
                f"Signal weights must sum to ~1.0, got {total_weight:.3f} "
                f"(obi={self.obi_weight}, microprice={self.microprice_weight}, impact={self.impact_weight})"
            )


class ExecutionConfig(BaseModel):
    """执行配置"""

    order_timeout: float = Field(
        default=1.0,
        description="订单超时（秒）",
        gt=0,
        le=60,
    )
    max_slippage_bps: float = Field(
        default=20.0,
        description="最大可接受滑点（基点，20 bps = 0.2%）",
        ge=0,
        le=1000,
    )


class HyperliquidConfig(BaseModel):
    """Hyperliquid 配置"""

    wallet_address: str = Field(..., description="钱包地址")
    private_key: str = Field(..., description="私钥")
    use_mainnet: bool = Field(default=True, description="使用 mainnet")
    symbols: list[str] = Field(default_factory=lambda: ["BTC", "ETH"])


class Config(BaseModel):
    """主配置

    提供完整的配置验证，确保所有参数在合理范围内
    """

    hyperliquid: HyperliquidConfig
    risk: RiskConfig = Field(default_factory=lambda: RiskConfig())
    signals: SignalConfig = Field(default_factory=lambda: SignalConfig())
    execution: ExecutionConfig = Field(default_factory=lambda: ExecutionConfig())
    initial_nav: float = Field(
        default=100000,
        description="初始净值（USD）",
        gt=0,
    )


class EnvironmentSettings(BaseSettings):
    """环境变量配置"""

    hyperliquid_wallet_address: str = ""
    hyperliquid_private_key: str = ""
    environment: str = "mainnet"
    initial_nav: float = 100000
    max_single_loss_pct: float = 0.008
    max_daily_drawdown_pct: float = 0.05
    theta_1: float = 0.5
    theta_2: float = 0.2

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )


def load_yaml_config(config_path: str) -> dict[str, Any]:
    """
    加载 YAML 配置文件

    Args:
        config_path: 配置文件路径

    Returns:
        Dict[str, Any]: 配置字典
    """
    config_file = Path(config_path)

    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_file, encoding="utf-8") as f:
        config = cast(dict[str, Any], yaml.safe_load(f))

    logger.info("yaml_config_loaded", path=config_path)

    # 处理配置继承（extends 字段）
    if "extends" in config:
        base_config_path = config_file.parent / config["extends"]
        if base_config_path.exists():
            with open(base_config_path, encoding="utf-8") as f:
                base_config = cast(dict[str, Any], yaml.safe_load(f))

            # 深度合并配置
            config = merge_configs(base_config, config)
            logger.info("merged_with_base_config", base=str(base_config_path))

    return config


def merge_configs(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """
    深度合并配置字典

    Args:
        base: 基础配置
        override: 覆盖配置

    Returns:
        Dict[str, Any]: 合并后的配置
    """
    merged = base.copy()

    for key, value in override.items():
        if key == "extends":
            continue

        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_configs(merged[key], value)
        else:
            merged[key] = value

    return merged


def load_config(config_path: str = "config/week1_ioc.yaml") -> Config:
    """
    加载完整配置（YAML + 环境变量）

    Args:
        config_path: YAML 配置文件路径

    Returns:
        Config: 配置对象
    """
    # 加载 YAML 配置
    yaml_config = load_yaml_config(config_path)

    # 加载环境变量
    env_settings = EnvironmentSettings()

    # 构建 Hyperliquid 配置
    hyperliquid_config = HyperliquidConfig(
        wallet_address=env_settings.hyperliquid_wallet_address,
        private_key=env_settings.hyperliquid_private_key,
        use_mainnet=env_settings.environment.lower() == "mainnet",
        symbols=yaml_config.get("hyperliquid", {}).get("symbols", ["BTC", "ETH"]),
    )

    # 构建风控配置
    risk_config_data = yaml_config.get("risk", {}).get("hard_limits", {})
    risk_config = RiskConfig(
        max_single_loss_pct=risk_config_data.get(
            "max_single_loss_pct", env_settings.max_single_loss_pct
        ),
        max_daily_drawdown_pct=risk_config_data.get(
            "max_daily_drawdown_pct", env_settings.max_daily_drawdown_pct
        ),
        max_position_size_usd=risk_config_data.get("max_position_size_usd", 10000),
    )

    # 构建信号配置
    signals_yaml = yaml_config.get("signals", {})
    thresholds_yaml = signals_yaml.get("thresholds", {})

    signal_thresholds = SignalThresholdsConfig(
        theta_1=thresholds_yaml.get("theta_1", env_settings.theta_1),
        theta_2=thresholds_yaml.get("theta_2", env_settings.theta_2),
    )

    signal_config = SignalConfig(
        thresholds=signal_thresholds,
        obi_levels=signals_yaml.get("obi", {}).get("levels", 5),
        obi_weight=signals_yaml.get("obi", {}).get("weight", 0.4),
        microprice_weight=signals_yaml.get("microprice", {}).get("weight", 0.3),
        impact_window_ms=signals_yaml.get("impact", {}).get("window_ms", 100),
        impact_weight=signals_yaml.get("impact", {}).get("weight", 0.3),
    )

    # 构建执行配置
    execution_yaml = yaml_config.get("execution", {})
    execution_config = ExecutionConfig(
        order_timeout=execution_yaml.get("order_timeout", 1.0),
        max_slippage_bps=execution_yaml.get("slippage", {}).get(
            "max_acceptable_bps", 20.0
        ),
    )

    # 构建完整配置
    config = Config(
        hyperliquid=hyperliquid_config,
        risk=risk_config,
        signals=signal_config,
        execution=execution_config,
        initial_nav=env_settings.initial_nav,
    )

    logger.info(
        "config_loaded",
        network="mainnet" if hyperliquid_config.use_mainnet else "testnet",
        symbols=hyperliquid_config.symbols,
    )

    return config
