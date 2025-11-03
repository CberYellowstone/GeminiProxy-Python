"""
日志工具模块 - 定义清晰的网络包方向标识符
"""

# 定义四种网络包方向的标识符
# 使用 rich 的颜色标记来增强可读性


class LogDirection:
    """日志方向标识符"""

    # 1. 调用者 → 后端：外部API调用者发送请求到后端
    CALLER_TO_BACKEND = "[bold yellow]◀[/bold yellow] [dim yellow]调用者→后端[/dim yellow]"

    # 2. 后端 → 调用者：后端响应给外部API调用者
    BACKEND_TO_CALLER = "[bold yellow]▶[/bold yellow] [dim yellow]后端→调用者[/dim yellow]"

    # 3. 后端 → 浏览器：后端通过WebSocket发送到浏览器前端
    BACKEND_TO_BROWSER = "[bold cyan]▶[/bold cyan] [dim cyan]后端→浏览器[/dim cyan]"

    # 4. 浏览器 → 后端：浏览器前端通过WebSocket发送到后端
    BROWSER_TO_BACKEND = "[bold cyan]◀[/bold cyan] [dim cyan]浏览器→后端[/dim cyan]"


# 快捷方法
def log_direction(direction: str) -> str:
    """
    根据方向类型返回对应的标识符

    Args:
        direction: 方向类型 ('caller_to_backend', 'backend_to_caller',
                           'backend_to_browser', 'browser_to_backend')

    Returns:
        格式化的方向标识符字符串
    """
    direction_map = {
        "caller_to_backend": LogDirection.CALLER_TO_BACKEND,
        "backend_to_caller": LogDirection.BACKEND_TO_CALLER,
        "backend_to_browser": LogDirection.BACKEND_TO_BROWSER,
        "browser_to_backend": LogDirection.BROWSER_TO_BACKEND,
    }
    return direction_map.get(direction, "")


def format_request_log(direction: str, request_id: str, details: str = "") -> str:
    """
    格式化请求日志

    Args:
        direction: 方向类型
        request_id: 请求ID
        details: 额外的详细信息

    Returns:
        格式化的日志字符串
    """
    dir_marker = log_direction(direction)
    log_msg = f"{dir_marker} [bold]请求[/bold] [bold green]{request_id}[/bold green]"
    if details:
        log_msg += f" {details}"
    return log_msg


def format_response_log(direction: str, request_id: str, details: str = "") -> str:
    """
    格式化响应日志

    Args:
        direction: 方向类型
        request_id: 请求ID
        details: 额外的详细信息

    Returns:
        格式化的日志字符串
    """
    dir_marker = log_direction(direction)
    log_msg = f"{dir_marker} [bold]响应[/bold] [bold green]{request_id}[/bold green]"
    if details:
        log_msg += f" {details}"
    return log_msg
