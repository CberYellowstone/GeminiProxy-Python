"""后台任务模块

管理应用生命周期内的后台任务，例如缓存清理、异步文件复制等。
"""

import asyncio
import logging

from app.core.log_utils import Logger

# 存储后台任务的引用，以便在应用关闭时能够安全地取消
background_tasks = set()


def create_background_task(coro):
    """
    创建一个新的后台任务，并将其加入管理集合。
    """
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    # 当任务完成时，自动从集合中移除，避免内存泄漏
    task.add_done_callback(background_tasks.discard)
    Logger.event("TASK_CREATE", f"后台任务已创建: {coro.__name__}")


async def start_background_tasks():
    """
    启动所有需要的后台任务。
    在应用启动时调用。
    """
    Logger.event("INIT", "启动后台任务...")
    # 在这里添加需要启动的后台任务
    from app.core.file_manager import file_manager

    create_background_task(file_manager.periodic_cleanup_task())


async def stop_background_tasks():
    """
    停止所有正在运行的后台任务。
    在应用关闭时调用。
    """
    Logger.event("SHUTDOWN", "停止后台任务...")
    for task in list(background_tasks):
        if not task.done():
            task.cancel()
            try:
                # 等待任务响应取消操作
                await task
            except asyncio.CancelledError:
                Logger.event("TASK_CANCEL", f"后台任务已取消")
            except Exception as e:
                Logger.error("后台任务关闭时发生错误", exc=e)
