"""
统一日志工具模块
提供简洁、一致的日志接口，适合小型项目
"""

import logging
from typing import Optional

from rich.logging import RichHandler

# ============================================================================
# 日志系统配置
# ============================================================================


def setup_logging(log_level: str = "INFO"):
    """
    配置统一的日志系统

    Args:
        log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR)
    """

    # 过滤 ping/pong 噪音日志
    class PingPongFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            message = record.getMessage().lower()
            return not any(kw in message for kw in ["ping", "pong", "keepalive"])

    # 创建 Rich 处理器
    handler = RichHandler(rich_tracebacks=True, markup=True, log_time_format="[%Y-%m-%d %H:%M:%S]")
    handler.addFilter(PingPongFilter())

    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()  # 清除现有处理器
    root_logger.addHandler(handler)

    # 同步 uvicorn 日志级别
    for logger_name in ["uvicorn.error", "uvicorn.access"]:
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(log_level)
        logger.propagate = False


# ============================================================================
# 统一日志接口
# ============================================================================


class Logger:
    """
    统一的日志记录器
    封装所有日志格式，提供简洁的调用接口

    日志级别说明：
    - INFO: 显示关键信息（ID、方向、类型），不显示具体数据
    - DEBUG: 显示完整的数据包内容
    """

    # 方向标识符
    _DIRECTIONS = {
        "api_request": "[bold yellow]▶[/bold yellow] [dim yellow]收到API请求[/dim yellow]",
        "api_response": "[bold yellow]◀[/bold yellow] [dim yellow]发送API响应[/dim yellow]",
        "ws_send": "[bold cyan]◀[/bold cyan] [dim cyan]传递至浏览器[/dim cyan]",
        "ws_receive": "[bold cyan]▶[/bold cyan] [dim cyan]接收自浏览器[/dim cyan]",
    }

    @staticmethod
    def api_request(request_id: str, message: str, **debug_data):
        """
        API请求日志

        Args:
            request_id: 请求ID
            message: INFO级别显示的消息
            **debug_data: DEBUG级别显示的详细数据
        """
        logging.info(f"{Logger._DIRECTIONS['api_request']} [bold green]{request_id}[/bold green] {message}")
        if debug_data and logging.getLogger().isEnabledFor(logging.DEBUG):
            logging.debug(f"  → 请求数据: {debug_data}")

    @staticmethod
    def api_response(request_id: str, message: str, **debug_data):
        """
        API响应日志

        Args:
            request_id: 请求ID
            message: INFO级别显示的消息
            **debug_data: DEBUG级别显示的详细数据
        """
        logging.info(f"{Logger._DIRECTIONS['api_response']} [bold green]{request_id}[/bold green] {message}")
        if debug_data and logging.getLogger().isEnabledFor(logging.DEBUG):
            logging.debug(f"  ← 响应数据: {debug_data}")

    @staticmethod
    def ws_send(request_id: str, client_id: str, command_type: Optional[str] = None, **debug_data):
        """
        WebSocket发送日志

        Args:
            request_id: 请求ID
            client_id: 客户端ID
            command_type: 命令类型
            **debug_data: DEBUG级别显示的完整数据包
        """
        msg = f"[bold green]{request_id}[/bold green] → [cyan]{client_id}[/cyan]"
        if command_type:
            msg += f" | 类型: [magenta]{command_type}[/magenta]"
        logging.info(f"{Logger._DIRECTIONS['ws_send']} {msg}")
        if debug_data and logging.getLogger().isEnabledFor(logging.DEBUG):
            logging.debug(f"  ◀ 发送数据包: {debug_data}")

    @staticmethod
    def ws_receive(
        request_id: str,
        client_id: str,
        is_stream_start: bool = False,
        is_stream_end: bool = False,
        is_stream_middle: bool = False,
        total_chunks: Optional[int] = None,
        **debug_data,
    ):
        """
        WebSocket接收日志

        Args:
            request_id: 请求ID
            client_id: 客户端ID
            is_stream_start: 是否为流式响应的第一个包
            is_stream_end: 是否为流式响应的最后一个包
            is_stream_middle: 是否为流式响应的中间包(INFO级别不显示,DEBUG显示)
            total_chunks: 流式响应总包数(仅在最后一个包时提供)
            **debug_data: DEBUG级别显示的完整数据包
        """
        msg = f"[bold green]{request_id}[/bold green] ← [cyan]{client_id}[/cyan]"
        if is_stream_start:
            msg += " | [yellow]流式开始[/yellow]"
        elif is_stream_end:
            msg += f" | [yellow]流式结束[/yellow] (共 {total_chunks} 个包)"

        # 中间包只在 DEBUG 级别显示 INFO 格式的日志
        if is_stream_middle:
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                logging.info(f"{Logger._DIRECTIONS['ws_receive']} {msg}")
        else:
            # 首包、尾包、非流式包都正常显示
            logging.info(f"{Logger._DIRECTIONS['ws_receive']} {msg}")

        if debug_data and logging.getLogger().isEnabledFor(logging.DEBUG):
            logging.debug(f"  ▶ 接收数据包: {debug_data}")

    @staticmethod
    def event(category: str, message: str, **context):
        """业务事件日志"""
        ctx = " | ".join(f"{k}: [cyan]{v}[/cyan]" for k, v in context.items())
        log_msg = f"[bold magenta][{category}][/bold magenta] {message}"
        if ctx:
            log_msg += f" | {ctx}"
        logging.info(log_msg)

    @staticmethod
    def error(message: str, exc: Optional[Exception] = None, **context):
        """错误日志（带异常栈）"""
        ctx = " | ".join(f"{k}: [yellow]{v}[/yellow]" for k, v in context.items())
        log_msg = f"[bold red]错误[/bold red] {message}"
        if ctx:
            log_msg += f" | {ctx}"

        if exc:
            logging.exception(log_msg, exc_info=exc)
        else:
            logging.error(log_msg)

    @staticmethod
    def _format_context(context: dict) -> str:
        """格式化上下文信息"""
        if not context:
            return ""
        ctx = " | ".join(f"{k}: [cyan]{v}[/cyan]" for k, v in context.items())
        return f" | {ctx}"

    @staticmethod
    def info(message: str, **context):
        """普通信息日志"""
        logging.info(f"{message}{Logger._format_context(context)}")

    @staticmethod
    def debug(message: str, **context):
        """调试日志"""
        logging.debug(f"{message}{Logger._format_context(context)}")

    @staticmethod
    def warning(message: str, **context):
        """警告日志"""
        log_msg = f"[bold orange]警告[/bold orange] {message}{Logger._format_context(context)}"
        logging.warning(log_msg)
