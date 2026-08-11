"""
异步事件总线模块。

基于线程池的事件总线：发布事件后，订阅该事件类型的 handler 会在后台线程异步执行。
用于解耦上传接口与后台索引处理（解析→分段→向量化→双写索引）。

@author: ziyu
@date: 2026-07-16
"""
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, DefaultDict, TypeVar

from app.core.config import settings


EventT = TypeVar("EventT")
EventHandler = Callable[[Any], None]


class AsyncEventBus:
    """异步事件总线：按事件类型注册 handler，发布事件时后台线程池异步执行。"""

    def __init__(self, max_workers: int | None = None):
        self._executor = ThreadPoolExecutor(max_workers=max_workers or settings.upload_worker_count)
        self._handlers: DefaultDict[type, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: type[EventT], handler: Callable[[EventT], None]) -> None:
        """订阅指定事件类型：发布该类型事件时调用 handler。"""
        self._handlers[event_type].append(handler)

    def publish(self, event: Any) -> list[Future]:
        """发布事件：将事件分发给该类型的全部 handler，返回 Future 列表。"""
        futures: list[Future] = []
        for handler in self._handlers[type(event)]:
            futures.append(self._executor.submit(handler, event))
        return futures

    def shutdown(self) -> None:
        """关闭线程池，不再等待已提交任务完成。"""
        self._executor.shutdown(wait=False, cancel_futures=False)
