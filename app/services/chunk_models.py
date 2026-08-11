"""
分段数据模型模块。

定义父分段草稿、子分段草稿、分段计划、已持久化子分段等不可变数据类，
作为分段器与入库 / 索引层之间的数据载体。

@author: ziyu
@date: 2026-07-13
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParentChunkDraft:
    """父分段草稿（粗粒度，入库前的中间形态）。"""

    chunk_no: int
    content: str
    page_no: int | None
    chapter: str | None
    article: str | None
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChildChunkDraft:
    """子分段草稿（细粒度，对应向量库与 ES 的一条记录）。"""

    chunk_no: int
    parent_no: int
    content: str
    page_no: int | None
    chapter: str | None
    article: str | None
    token_count: int
    milvus_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParentChildChunkPlan:
    """分段计划：一个文档切分后的全部父段与子段。"""

    parents: list[ParentChunkDraft]
    children: list[ChildChunkDraft]


@dataclass(frozen=True)
class PersistedChildChunk:
    """已持久化的子分段：含数据库 ID 与父段内容，用于双写索引。"""

    id: int
    chunk_no: int
    document_id: str
    tenant_id: str
    kb_id: str
    content: str
    source_file: str
    milvus_id: str
    parent_chunk_id: int
    parent_content: str
    metadata: dict[str, Any] = field(default_factory=dict)
