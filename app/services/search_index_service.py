"""
索引服务模块。

负责把分段与向量双写到 Milvus（向量检索）和 Elasticsearch（全文检索），
并支持按文档整体替换与删除，保证两端数据一致。

@author: ziyu
@date: 2026-07-16
"""
import re

from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch.helpers import BulkIndexError, bulk
from pymilvus import MilvusClient

from app.core.config import settings
from app.services.chunk_models import PersistedChildChunk


class SearchIndexService:
    """双写索引服务：Milvus 向量 + ES 全文，按文档整体增删替换。"""

    def __init__(
        self,
        es_client: Elasticsearch,
        milvus_client: MilvusClient,
        collection_name: str,
        es_index_name: str | None = None,
    ):
        self.es = es_client
        self.milvus = milvus_client
        self.collection_name = collection_name
        self.es_index_name = es_index_name or settings.es_chunk_index_name

    def replace_document_chunks(
        self,
        tenant_id: str,
        kb_id: str,
        document_id: str,
        chunks: list[PersistedChildChunk],
        vectors: list[list[float]],
    ) -> None:
        """整体替换某文档的全部分段索引：先删旧后插新，向量与分段数量必须一致。"""
        if len(chunks) != len(vectors):
            raise ValueError(f"索引数据数量不一致，chunks={len(chunks)} vectors={len(vectors)}")

        self.delete_document(tenant_id=tenant_id, kb_id=kb_id, document_id=document_id)
        if not chunks:
            return
        self._insert_milvus(chunks, vectors)
        self._insert_es(chunks)

    def delete_document(self, tenant_id: str, kb_id: str, document_id: str) -> None:
        """从 Milvus 与 ES 中删除某文档的全部分段。"""
        self._delete_milvus(tenant_id, kb_id, document_id)
        self._delete_es(tenant_id, kb_id, document_id)

    def _insert_milvus(self, chunks: list[PersistedChildChunk], vectors: list[list[float]]) -> None:
        """把分段与向量批量写入 Milvus。"""
        data = []
        for chunk, vector in zip(chunks, vectors):
            data.append(
                {
                    "chunk_id": chunk.milvus_id,
                    "document_id": str(chunk.document_id),
                    "tenant_id": str(chunk.tenant_id),
                    "kb_id": str(chunk.kb_id),
                    "content": chunk.content,
                    "vector": vector,
                    "source_file": chunk.source_file,
                    "parent_id": str(chunk.parent_chunk_id),
                    "metadata": chunk.metadata,
                }
            )

        self.milvus.insert(collection_name=self.collection_name, data=data)

    def _insert_es(self, chunks: list[PersistedChildChunk]) -> None:
        """把分段批量写入 ES（含父段内容、清洗后的文本）。"""
        actions = []
        for chunk in chunks:
            metadata = {
                **chunk.metadata,
                "parent_content": self._clean_text(chunk.parent_content),
            }
            actions.append(
                {
                    "_index": self.es_index_name,
                    "_id": chunk.milvus_id,
                    "_source": {
                        "chunk_id": chunk.milvus_id,
                        "db_chunk_id": chunk.id,
                        "parent_chunk_id": chunk.parent_chunk_id,
                        "document_id": chunk.document_id,
                        "tenant_id": chunk.tenant_id,
                        "kb_id": chunk.kb_id,
                        "content": self._clean_text(chunk.content),
                        "source_file": chunk.source_file,
                        "metadata": metadata,
                    },
                }
            )

        try:
            bulk(self.es, actions)
        except BulkIndexError as exc:
            for error in exc.errors:
                print(error)
            raise

    def _delete_milvus(self, tenant_id: str, kb_id: str, document_id: str) -> None:
        """按租户+知识库+文档过滤删除 Milvus 数据。"""
        self.milvus.delete(
            collection_name=self.collection_name,
            filter=(
                f'tenant_id == "{tenant_id}" '
                f'and kb_id == "{kb_id}" '
                f'and document_id == "{document_id}"'
            ),
        )

    def _delete_es(self, tenant_id: str, kb_id: str, document_id: str) -> None:
        """按租户+知识库+文档过滤删除 ES 数据，索引不存在时静默。"""
        try:
            self.es.delete_by_query(
                index=self.es_index_name,
                conflicts="proceed",
                refresh=True,
                query={
                    "bool": {
                        "filter": [
                            {"term": {"tenant_id": tenant_id}},
                            {"term": {"kb_id": kb_id}},
                            {"term": {"document_id": document_id}},
                        ]
                    }
                },
            )
        except NotFoundError:
            return

    def _clean_text(self, text: str) -> str:
        """把多余空白（含不间断空格）压成单空格并去首尾空白。"""
        if not text:
            return ""
        return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
