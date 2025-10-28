"""日志系统测试"""

import json
import logging
import time

from src.core.logging import LogLevel, get_audit_logger, get_logger, setup_logging


class TestLoggingSetup:
    """日志系统配置测试"""

    def test_setup_logging_creates_log_directory(self, tmp_path):
        """测试日志目录创建"""
        log_dir = tmp_path / "test_logs"

        setup_logging(log_dir=str(log_dir), enable_audit=False)

        assert log_dir.exists()
        assert log_dir.is_dir()

    def test_setup_logging_creates_log_files(self, tmp_path):
        """测试日志文件创建"""
        log_dir = tmp_path / "test_logs"

        setup_logging(log_dir=str(log_dir), enable_audit=True)

        # 生成一些日志
        logger = get_logger(__name__)
        logger.info("test_message", key="value")

        audit_logger = get_audit_logger()
        audit_logger.info("test_audit", action="test")

        # 等待文件写入
        time.sleep(0.1)

        # 检查文件是否存在
        log_files = list(log_dir.glob("*.log*"))
        assert len(log_files) >= 2  # trading.log 和 audit.log

        # 检查文件名
        file_names = [f.name for f in log_files]
        assert any("trading.log" in name for name in file_names)
        assert any("audit.log" in name for name in file_names)

    def test_log_level_from_env(self, tmp_path, monkeypatch, isolated_logging):
        """测试从环境变量读取日志级别"""
        log_dir = isolated_logging  # 使用隔离的日志目录
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("LOG_DIR", str(log_dir))

        setup_logging(log_dir=str(log_dir), enable_audit=False)

        # 验证日志级别
        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG

    def test_retention_days_configuration(self, tmp_path, isolated_logging):
        """测试日志保留天数配置"""
        log_dir = isolated_logging  # 使用隔离的日志目录
        retention_days = 10

        setup_logging(
            log_dir=str(log_dir), retention_days=retention_days, enable_audit=False
        )

        # 检查文件处理器的配置
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if isinstance(handler, logging.handlers.TimedRotatingFileHandler):
                assert handler.backupCount == retention_days


class TestLogging:
    """日志记录功能测试"""

    def test_logger_info_message(self, tmp_path):
        """测试 INFO 级别日志"""
        log_dir = tmp_path / "test_logs"
        setup_logging(log_dir=str(log_dir), enable_audit=False)

        logger = get_logger(__name__)
        logger.info("test_event", param1="value1", param2=123)

        # 强制刷新所有处理器
        for handler in logging.getLogger().handlers:
            handler.flush()
        time.sleep(0.3)  # 延长等待时间

        # 读取日志文件
        log_file = log_dir / "trading.log"
        assert log_file.exists()

        with open(log_file) as f:
            content = f.read()
            assert "test_event" in content
            assert "value1" in content
            assert "123" in content

    def test_logger_warning_message(self, tmp_path):
        """测试 WARNING 级别日志"""
        log_dir = tmp_path / "test_logs"
        setup_logging(log_dir=str(log_dir), enable_audit=False)

        logger = get_logger(__name__)
        logger.warning("test_warning", reason="test_reason")

        time.sleep(0.1)

        log_file = log_dir / "trading.log"
        with open(log_file) as f:
            content = f.read()
            assert "test_warning" in content
            assert "test_reason" in content

    def test_logger_error_message(self, tmp_path):
        """测试 ERROR 级别日志"""
        log_dir = tmp_path / "test_logs"
        setup_logging(log_dir=str(log_dir), enable_audit=False)

        logger = get_logger(__name__)
        logger.error("test_error", error="test_error_message")

        time.sleep(0.1)

        log_file = log_dir / "trading.log"
        with open(log_file) as f:
            content = f.read()
            assert "test_error" in content
            assert "test_error_message" in content

    def test_json_format_in_file(self, tmp_path):
        """测试日志文件使用 JSON 格式"""
        log_dir = tmp_path / "test_logs"
        setup_logging(log_dir=str(log_dir), enable_audit=False)

        logger = get_logger(__name__)
        logger.info("json_test", field1="value1", field2=42, field3=True)

        # 强制刷新所有处理器
        for handler in logging.getLogger().handlers:
            handler.flush()
        time.sleep(0.3)  # 延长等待时间

        log_file = log_dir / "trading.log"
        with open(log_file) as f:
            lines = f.readlines()
            assert len(lines) >= 1  # 至少有一行日志

            # 解析最后一行（我们的测试日志）
            last_line = lines[-1].strip()
            log_data = json.loads(last_line)

            # 验证 JSON 结构
            assert "event" in log_data
            assert log_data["event"] == "json_test"
            assert log_data["field1"] == "value1"
            assert log_data["field2"] == 42
            assert log_data["field3"] is True
            assert "timestamp" in log_data
            assert "level" in log_data


class TestAuditLogging:
    """审计日志测试"""

    def test_audit_logger_creation(self, tmp_path):
        """测试审计日志创建"""
        log_dir = tmp_path / "test_logs"
        setup_logging(log_dir=str(log_dir), enable_audit=True)

        audit_logger = get_audit_logger()
        audit_logger.info("audit_event", action="test_action", user="test_user")

        time.sleep(0.1)

        audit_file = log_dir / "audit.log"
        assert audit_file.exists()

        with open(audit_file) as f:
            content = f.read()
            assert "audit_event" in content
            assert "test_action" in content
            assert "test_user" in content

    def test_audit_logger_independence(self, tmp_path):
        """测试审计日志独立性（不传播到 root logger）"""
        log_dir = tmp_path / "test_logs"
        setup_logging(log_dir=str(log_dir), enable_audit=True)

        # 记录审计日志
        audit_logger = get_audit_logger()
        audit_logger.info("audit_only_event", data="sensitive")

        time.sleep(0.1)

        # 审计日志应该只在 audit.log 中
        audit_file = log_dir / "audit.log"
        with open(audit_file) as f:
            audit_content = f.read()
            assert "audit_only_event" in audit_content

        # 主日志文件应该不包含审计日志（因为 propagate=False）
        trading_file = log_dir / "trading.log"
        if trading_file.exists():
            with open(trading_file) as f:
                trading_content = f.read()
                # 审计事件不应该在主日志中（除非是系统启动日志）
                # 这里我们检查 "audit_only_event" 具体内容
                assert "audit_only_event" not in trading_content

    def test_audit_logger_json_format(self, tmp_path):
        """测试审计日志 JSON 格式"""
        log_dir = tmp_path / "test_logs"
        setup_logging(log_dir=str(log_dir), enable_audit=True)

        audit_logger = get_audit_logger()
        audit_logger.info(
            "order_executed",
            order_id="test123",
            symbol="BTC",
            side="BUY",
            size=0.1,
        )

        time.sleep(0.1)

        audit_file = log_dir / "audit.log"
        with open(audit_file) as f:
            lines = f.readlines()
            last_line = lines[-1].strip()
            log_data = json.loads(last_line)

            assert log_data["event"] == "order_executed"
            assert log_data["order_id"] == "test123"
            assert log_data["symbol"] == "BTC"
            assert log_data["side"] == "BUY"
            assert log_data["size"] == 0.1

    def test_disable_audit_logging(self, tmp_path, isolated_logging):
        """测试禁用审计日志"""
        log_dir = isolated_logging  # 使用隔离的日志目录
        setup_logging(log_dir=str(log_dir), enable_audit=False)

        # 强制刷新所有处理器
        for handler in logging.getLogger().handlers:
            handler.flush()
        time.sleep(0.3)

        # 审计日志文件不应该创建
        audit_file = log_dir / "audit.log"
        assert not audit_file.exists()


class TestLogRotation:
    """日志轮转测试"""

    def test_log_file_suffix_format(self, tmp_path):
        """测试日志文件后缀格式"""
        log_dir = tmp_path / "test_logs"
        setup_logging(log_dir=str(log_dir), enable_audit=False)

        # 检查文件处理器的后缀配置
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if isinstance(handler, logging.handlers.TimedRotatingFileHandler):
                assert handler.suffix == "%Y%m%d"


class TestEnvironmentVariables:
    """环境变量配置测试"""

    def test_log_level_env_override(self, tmp_path, monkeypatch, isolated_logging):
        """测试环境变量覆盖日志级别"""
        log_dir = isolated_logging  # 使用隔离的日志目录
        monkeypatch.setenv("LOG_LEVEL", "ERROR")
        monkeypatch.setenv("LOG_DIR", str(log_dir))

        setup_logging(log_level="INFO", log_dir=str(log_dir), enable_audit=False)

        root_logger = logging.getLogger()
        assert root_logger.level == logging.ERROR

    def test_log_dir_env_override(self, tmp_path, monkeypatch):
        """测试环境变量覆盖日志目录"""
        custom_log_dir = tmp_path / "custom_logs"
        monkeypatch.setenv("LOG_DIR", str(custom_log_dir))

        setup_logging(log_dir="default_logs", enable_audit=False)

        assert custom_log_dir.exists()

    def test_enable_audit_env_override(self, tmp_path, monkeypatch):
        """测试环境变量控制审计日志"""
        log_dir = tmp_path / "test_logs"
        monkeypatch.setenv("ENABLE_AUDIT_LOG", "false")

        setup_logging(log_dir=str(log_dir), enable_audit=True)

        time.sleep(0.1)

        audit_file = log_dir / "audit.log"
        assert not audit_file.exists()


class TestLogLevelConstants:
    """日志级别常量测试"""

    def test_log_level_constants_exist(self):
        """测试日志级别常量"""
        assert LogLevel.DEBUG == "DEBUG"
        assert LogLevel.INFO == "INFO"
        assert LogLevel.WARNING == "WARNING"
        assert LogLevel.ERROR == "ERROR"
        assert LogLevel.CRITICAL == "CRITICAL"
