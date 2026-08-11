"""
上传服务装配模块。

按 settings 与运行参数装配上传链路各组件（仓储、事件总线、索引服务、索引处理器、
分段器、向量服务），把处理器订阅到事件总线，最终返回可用的上传服务实例。

@author: ziyu
@date: 2026-07-16
"""
from elasticsearch import Elasticsearch
from pymilvus import MilvusClient

from app.core.config import settings
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.services.document_indexing_handler import DocumentIndexingHandler
from app.services.document_text_reader import DocumentTextReader
from app.services.embedding_service import DashScopeEmbeddingService
from app.services.event_bus import AsyncEventBus
from app.services.parent_child_chunker import ParentChildChunker
from app.services.search_index_service import SearchIndexService
from app.services.upload_models import DocumentUploadRequested
from app.services.upload_service import DocumentUploadService


def build_upload_service(
    es_client: Elasticsearch,
    milvus_client: MilvusClient,
    collection_name: str,
    es_index_name: str | None = None,
    worker_count: int | None = None,
    embedding_model: str | None = None,
    embedding_batch_size: int | None = None,
    embedding_batch_interval_seconds: float | None = None,
    embedding_retry_count: int | None = None,
    embedding_retry_interval_seconds: float | None = None,
    parent_chunk_size: int | None = None,
    parent_chunk_overlap: int | None = None,
    child_chunk_size: int | None = None,
    child_chunk_overlap: int | None = None,
    table_row_group_size: int | None = None,
) -> DocumentUploadService:
    """装配上传链路各组件并订阅处理事件，返回 DocumentUploadService 实例。"""
    repository = KnowledgeBaseRepository()
    event_bus = AsyncEventBus(max_workers=worker_count or settings.upload_worker_count)
    index_service = SearchIndexService(
        es_client=es_client,
        milvus_client=milvus_client,
        collection_name=collection_name,
        es_index_name=es_index_name or settings.es_chunk_index_name,
    )
    handler = DocumentIndexingHandler(
        repository=repository,
        text_reader=DocumentTextReader(),
        chunker=ParentChildChunker(
            parent_chunk_size=parent_chunk_size or settings.parent_chunk_size,
            parent_chunk_overlap=parent_chunk_overlap or settings.parent_chunk_overlap,
            child_chunk_size=child_chunk_size or settings.child_chunk_size,
            child_chunk_overlap=child_chunk_overlap or settings.child_chunk_overlap,
            table_row_group_size=table_row_group_size or settings.table_row_group_size,
        ),
        embedding_service=DashScopeEmbeddingService(
            model_name=embedding_model or settings.embedding_model,
            batch_size=embedding_batch_size or settings.embedding_batch_size,
            batch_interval_seconds=embedding_batch_interval_seconds or settings.embedding_batch_interval_seconds,
            retry_count=embedding_retry_count or settings.embedding_retry_count,
            retry_interval_seconds=embedding_retry_interval_seconds or settings.embedding_retry_interval_seconds,
        ),
        index_service=index_service,
    )
    event_bus.subscribe(DocumentUploadRequested, handler.handle)
    return DocumentUploadService(repository=repository, event_bus=event_bus)
