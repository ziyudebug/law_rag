"""
Milvus 客户端模块。

使用 pymilvus 新版 MilvusClient 通过 uri 连接，并封装为懒加载代理：
首次访问任意属性时才真正建立连接，避免启动阶段即连向量库。

@author: ziyu
@date: 2026-07-29
"""
from functools import lru_cache
from typing import Any

from pymilvus import MilvusClient

from app.core.config import settings


@lru_cache(maxsize=1)
def get_milvus_client() -> MilvusClient:
    """获取单例 MilvusClient（带 lru 缓存）。pymilvus 新版用 uri 连接，host/port 关键字会被 **kwargs 吞掉。"""
    uri = f"http://{settings.milvus_host}:{settings.milvus_port}"
    return MilvusClient(
        uri=uri,
        user=settings.milvus_username,
        password=settings.milvus_password,
    )


class LazyMilvusClient:
    """MilvusClient 的懒加载代理：首次属性访问时才建立真实连接。"""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_milvus_client(), name)


# 全局 Milvus 客户端代理实例
client = LazyMilvusClient()
