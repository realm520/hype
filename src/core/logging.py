"""日志系统配置

提供生产级日志功能：
- 文件日志（JSON 格式，按日轮转）
- 控制台日志（彩色格式，便于开发）
- 审计日志（关键操作记录）
- 环境变量配置支持
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

import structlog


def setup_logging(
    log_level: str | None = None,
    log_dir: str | None = None,
    retention_days: int = 30,
    enable_audit: bool = True,
) -> None:
    """
    配置完整的日志系统

    Args:
        log_level: 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
        log_dir: 日志目录路径
        retention_days: 日志保留天数
        enable_audit: 是否启用审计日志
    """
    # 从环境变量获取配置（优先级高于参数）
    log_level = os.getenv("LOG_LEVEL", log_level or "INFO").upper()
    log_dir = os.getenv("LOG_DIR", log_dir or "logs")
    retention_days = int(os.getenv("LOG_RETENTION_DAYS", str(retention_days)))
    enable_audit_env = os.getenv("ENABLE_AUDIT_LOG", "true").lower()
    enable_audit = enable_audit_env in ("true", "1", "yes") if enable_audit_env else enable_audit

    # 创建日志目录
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # 配置标准库 logging（structlog 底层依赖）
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level),
    )

    # 配置文件日志处理器（JSON 格式）
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_path / "trading.log",
        when="midnight",
        interval=1,
        backupCount=retention_days,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y%m%d"  # 文件后缀：trading.log.20251026
    file_handler.setLevel(getattr(logging, log_level))

    # 获取 root logger 并添加文件处理器
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)

    # 配置 structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            # 根据输出目标选择不同的渲染器
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 配置标准库日志格式化器
    formatter = structlog.stdlib.ProcessorFormatter(
        # 文件输出：JSON 格式
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    # 控制台输出：彩色格式
    console_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=True),
        ],
    )

    # 为文件处理器设置 JSON 格式
    file_handler.setFormatter(formatter)

    # 为控制台处理器设置彩色格式
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler) and handler.stream == sys.stdout:
            handler.setFormatter(console_formatter)

    # 配置审计日志（如果启用）
    if enable_audit:
        _setup_audit_logging(log_path, retention_days, log_level)

    # 记录日志系统启动
    logger = structlog.get_logger(__name__)
    logger.info(
        "logging_system_initialized",
        log_level=log_level,
        log_dir=str(log_path.absolute()),
        retention_days=retention_days,
        audit_enabled=enable_audit,
    )


def _setup_audit_logging(
    log_dir: Path,
    retention_days: int,
    log_level: str,
) -> None:
    """
    配置审计日志（记录关键操作）

    Args:
        log_dir: 日志目录
        retention_days: 保留天数
        log_level: 日志级别
    """
    # 创建审计日志处理器
    audit_handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_dir / "audit.log",
        when="midnight",
        interval=1,
        backupCount=retention_days,
        encoding="utf-8",
    )
    audit_handler.suffix = "%Y%m%d"
    audit_handler.setLevel(getattr(logging, log_level))

    # JSON 格式化器
    audit_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    audit_handler.setFormatter(audit_formatter)

    # 创建独立的审计 logger
    audit_logger = logging.getLogger("audit")
    audit_logger.addHandler(audit_handler)
    audit_logger.setLevel(getattr(logging, log_level))
    # 不传播到 root logger（避免重复记录）
    audit_logger.propagate = False


def get_audit_logger() -> structlog.BoundLogger:
    """
    获取审计日志记录器

    用于记录关键操作：
    - 订单执行
    - 风控触发
    - 配置变更
    - 系统启停

    Returns:
        structlog.BoundLogger: 审计日志记录器

    Example:
        >>> audit_logger = get_audit_logger()
        >>> audit_logger.info(
        ...     "order_executed",
        ...     order_id="abc123",
        ...     symbol="BTC",
        ...     side="BUY",
        ...     size=0.1,
        ... )
    """
    return structlog.get_logger("audit")


def get_logger(name: str) -> structlog.BoundLogger:
    """
    获取模块日志记录器

    Args:
        name: 模块名称（通常使用 __name__）

    Returns:
        structlog.BoundLogger: 日志记录器

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("module_started", version="1.0.0")
    """
    return structlog.get_logger(name)


# 日志级别常量
class LogLevel:
    """日志级别常量"""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
