"""
检索服务：封装向量检索、全文检索与混合检索三类召回策略。

支持 VECTOR / FULLTEXT / HYBRID 三种模式，HYBRID 下再分 RERANK（重排）与 WEIGHT（加权融合）两种策略。
所有检索均按 tenant_id + kb_id 做多租户隔离，可按 document_id 进一步过滤。

@author: ziyu
@date: 2026-07-17
"""
from http import HTTPStatus
from typing import Any

import dashscope
from elasticsearch import Elasticsearch, NotFoundError
from pymilvus import MilvusClient

from app.core.config import settings
from app.repositories.retrieval_config_repository import RetrievalConfigRepository
from app.services.retrieval_config_models import (
    HYBRID_STRATEGY_WEIGHT,
    SEARCH_TYPE_FULLTEXT,
    SEARCH_TYPE_HYBRID,
    SEARCH_TYPE_VECTOR,
    RetrievalConfig,
)


DocumentIdFilter = str | list[str] | None


class RetrievalService:
    """检索服务核心类，统一调度 ES 全文检索与 Milvus 向量检索。"""

    def __init__(
        self,
        es_client: Elasticsearch,
        milvus_client: MilvusClient,
        collection_name: str,
        config_repository: RetrievalConfigRepository | None = None,
        es_index_name: str | None = None,
        embedding_model: str | None = None,
        candidate_multiplier: int | None = None,
        min_hybrid_candidate_k: int | None = None,
        rerank_instruct: str | None = None,
    ):
        """初始化检索服务，注入 ES/Milvus 客户端与可配置参数，缺省值取自全局 settings。"""
        self.es = es_client
        self.milvus = milvus_client
        self.collection_name = collection_name
        self.config_repository = config_repository or RetrievalConfigRepository()
        self.es_index_name = es_index_name or settings.es_chunk_index_name
        self.embedding_model = embedding_model or settings.embedding_model
        self.candidate_multiplier = max(1, candidate_multiplier or settings.retrieval_candidate_multiplier)
        self.min_hybrid_candidate_k = max(1, min_hybrid_candidate_k or settings.retrieval_min_candidate_k)
        self.rerank_instruct = rerank_instruct or settings.rerank_instruct

    def retrieve(
        self,
        query: str,
        tenant_id: str,
        kb_id: str,
        document_id: DocumentIdFilter = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """对外主入口：根据检索模式分发到向量/全文/混合检索流程。"""
        if not query:
            return []

        config = self.config_repository.get_or_default(tenant_id=tenant_id, kb_id=kb_id)
        selected_type = self._resolve_search_type(config.retrieval_mode)

        if selected_type == SEARCH_TYPE_VECTOR:
            return self._retrieve_vector(query, tenant_id, kb_id, document_id, config, top_k)
        if selected_type == SEARCH_TYPE_FULLTEXT:
            return self._retrieve_fulltext(query, tenant_id, kb_id, document_id, config, top_k)
        return self._retrieve_hybrid(query, tenant_id, kb_id, document_id, config, top_k)

    def create_query_embedding(self, query: str) -> list[float]:
        """调用 DashScope 多模态嵌入模型，把查询文本转向量。"""
        resp = dashscope.MultiModalEmbedding.call(
            model=self.embedding_model,
            input=[{"text": query}],
        )
        if resp.status_code != HTTPStatus.OK:
            raise RuntimeError(f"embedding失败:{resp}")
        return resp.output["embeddings"][0]["embedding"]

    def search_es(
        self,
        query: str,
        tenant_id: str,
        kb_id: str,
        document_id: DocumentIdFilter = None,
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        """在 ES 中按 tenant/kb/document 过滤做全文匹配检索，返回带 es_score 的结果列表。"""
        filters = [
            {"term": {"tenant_id": tenant_id}},
            {"term": {"kb_id": kb_id}},
        ]
        document_ids = self._normalize_document_ids(document_id)
        if len(document_ids) == 1:
            filters.append({"term": {"document_id": document_ids[0]}})
        elif len(document_ids) > 1:
            filters.append({"terms": {"document_id": document_ids}})

        body = {
            "size": top_k,
            "_source": [
                "chunk_id",
                "db_chunk_id",
                "parent_chunk_id",
                "document_id",
                "tenant_id",
                "kb_id",
                "content",
                "source_file",
                "metadata",
            ],
            "query": {
                "bool": {
                    "must": [{"match": {"content": query}}],
                    "filter": filters,
                }
            },
        }

        try:
            resp = self.es.search(index=self.es_index_name, body=body)
        except NotFoundError:
            return []

        result = []
        for hit in resp["hits"]["hits"]:
            source = hit["_source"]
            item = self._source_to_item(source)
            item["es_score"] = float(hit["_score"])
            item["score"] = item["es_score"]
            result.append(item)
        return result

    def search_vector(
        self,
        query_vector: list[float],
        tenant_id: str,
        kb_id: str,
        document_id: DocumentIdFilter = None,
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        """在 Milvus 中按 tenant/kb/document 过滤做向量相似检索，返回带 vector_score 的结果列表。"""
        filter_expr = f'tenant_id == "{tenant_id}" and kb_id == "{kb_id}"'
        document_ids = self._normalize_document_ids(document_id)
        if len(document_ids) == 1:
            filter_expr += f' and document_id == "{self._escape_milvus_string(document_ids[0])}"'
        elif len(document_ids) > 1:
            values = ", ".join(f'"{self._escape_milvus_string(item)}"' for item in document_ids)
            filter_expr += f" and document_id in [{values}]"

        resp = self.milvus.search(
            collection_name=self.collection_name,
            data=[query_vector],
            filter=filter_expr,
            limit=top_k,
            output_fields=[
                "chunk_id",
                "document_id",
                "tenant_id",
                "kb_id",
                "content",
                "source_file",
                "parent_id",
                "metadata",
            ],
        )

        result = []
        for item in resp[0]:
            entity = item["entity"]
            chunk = self._source_to_item(entity)
            chunk["parent_chunk_id"] = entity.get("parent_id") or chunk.get("parent_chunk_id")
            chunk["vector_score"] = self._hit_distance(item)
            chunk["score"] = chunk["vector_score"]
            result.append(chunk)
        return result

    def rerank(
        self,
        query: str,
        chunks: list[dict[str, Any]],
        top_k: int,
        model_name: str,
    ) -> list[dict[str, Any]]:
        """调用 Qwen 重排模型对候选块重新打分，返回按 relevance_score 排序的结果。"""
        if not chunks:
            return []

        documents = [item["content"] for item in chunks]
        resp = dashscope.TextReRank.call(
            model=model_name,
            query=query,
            documents=documents,
            top_n=top_k,
            return_documents=False,
            instruct=self.rerank_instruct,
        )
        if resp.status_code != HTTPStatus.OK:
            raise RuntimeError(f"Qwen rerank失败:{resp}")

        results = []
        for item in resp.output["results"]:
            chunk = dict(chunks[item["index"]])
            chunk["rerank_score"] = float(item["relevance_score"])
            chunk["score"] = chunk["rerank_score"]
            results.append(chunk)
        return results

    def _retrieve_vector(
        self,
        query: str,
        tenant_id: str,
        kb_id: str,
        document_id: DocumentIdFilter,
        options: RetrievalConfig,
        top_k_override: int | None,
    ) -> list[dict[str, Any]]:
        """纯向量检索：查询向量→召回→按是否重排分别收敛。"""
        top_k = self._effective_top_k(options.top_k, top_k_override)
        query_vector = self.create_query_embedding(query)
        chunks = self.search_vector(query_vector, tenant_id, kb_id, document_id, top_k=self._expanded_top_k(top_k))
        if options.use_rerank:
            chunks = self.rerank(query, chunks, top_k=top_k, model_name=options.rerank_model)
            return self._finalize(chunks, options.score_threshold, options.enable_source, top_k)
        chunks = self._sort_and_limit(chunks, "vector_score", top_k)
        return self._finalize(chunks, options.score_threshold, options.enable_source, top_k)

    def _retrieve_fulltext(
        self,
        query: str,
        tenant_id: str,
        kb_id: str,
        document_id: DocumentIdFilter,
        options: RetrievalConfig,
        top_k_override: int | None,
    ) -> list[dict[str, Any]]:
        """纯全文检索：ES 召回→按是否重排分别收敛。"""
        top_k = self._effective_top_k(options.top_k, top_k_override)
        chunks = self.search_es(query, tenant_id, kb_id, document_id, top_k=self._expanded_top_k(top_k))
        if options.use_rerank:
            chunks = self.rerank(query, chunks, top_k=top_k, model_name=options.rerank_model)
            return self._finalize(chunks, options.score_threshold, options.enable_source, top_k)
        chunks = self._sort_and_limit(chunks, "es_score", top_k)
        return self._finalize(chunks, options.score_threshold, options.enable_source, top_k)

    def _retrieve_hybrid(
        self,
        query: str,
        tenant_id: str,
        kb_id: str,
        document_id: DocumentIdFilter,
        config: RetrievalConfig,
        top_k_override: int | None,
    ) -> list[dict[str, Any]]:
        """混合检索：按策略分发到加权融合或重排融合。"""
        if config.hybrid_strategy == HYBRID_STRATEGY_WEIGHT:
            return self._retrieve_hybrid_weight(
                query, tenant_id, kb_id, document_id, config, top_k_override
            )
        return self._retrieve_hybrid_rerank(
            query, tenant_id, kb_id, document_id, config, top_k_override
        )

    def _retrieve_hybrid_rerank(
        self,
        query: str,
        tenant_id: str,
        kb_id: str,
        document_id: DocumentIdFilter,
        options: RetrievalConfig,
        top_k_override: int | None,
    ) -> list[dict[str, Any]]:
        """混合-重排策略：双路召回合并→重排→收敛。"""
        top_k = self._effective_top_k(options.top_k, top_k_override)
        candidates = self._hybrid_candidates(
            query,
            tenant_id,
            kb_id,
            document_id,
            candidate_k=self._hybrid_candidate_top_k(top_k),
        )
        reranked = self.rerank(query, candidates, top_k=top_k, model_name=options.rerank_model)
        return self._finalize(reranked, options.score_threshold, options.enable_source, top_k)

    def _retrieve_hybrid_weight(
        self,
        query: str,
        tenant_id: str,
        kb_id: str,
        document_id: DocumentIdFilter,
        options: RetrievalConfig,
        top_k_override: int | None,
    ) -> list[dict[str, Any]]:
        """混合-加权策略：双路召回→归一化加权融合→排序收敛。"""
        top_k = self._effective_top_k(options.top_k, top_k_override)
        query_vector = self.create_query_embedding(query)
        candidate_k = self._hybrid_candidate_top_k(top_k)
        vector_chunks = self.search_vector(query_vector, tenant_id, kb_id, document_id, top_k=candidate_k)
        es_chunks = self.search_es(query, tenant_id, kb_id, document_id, top_k=candidate_k)
        weighted = self._merge_weighted(vector_chunks, es_chunks, options)
        weighted = self._sort_and_limit(weighted, "hybrid_score", top_k)
        return self._finalize(weighted, options.score_threshold, options.enable_source, top_k)

    def _hybrid_candidates(
        self,
        query: str,
        tenant_id: str,
        kb_id: str,
        document_id: DocumentIdFilter,
        candidate_k: int,
    ) -> list[dict[str, Any]]:
        """混合检索的候选收集：向量 + ES 双路召回，按 chunk_id 去重合并。"""
        query_vector = self.create_query_embedding(query)
        vector_chunks = self.search_vector(query_vector, tenant_id, kb_id, document_id, top_k=candidate_k)
        es_chunks = self.search_es(query, tenant_id, kb_id, document_id, top_k=candidate_k)
        return self._merge_chunks(es_chunks, vector_chunks)

    def _merge_chunks(
        self,
        es_chunks: list[dict[str, Any]],
        vector_chunks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """按 chunk_id 合并双路结果，相同块合并各路 score 字段并标记 hybrid=True。"""
        result: dict[str, dict[str, Any]] = {}
        for item in es_chunks + vector_chunks:
            chunk_id = item["chunk_id"]
            if chunk_id not in result:
                result[chunk_id] = dict(item)
            else:
                result[chunk_id].update({key: value for key, value in item.items() if key.endswith("_score")})
                result[chunk_id]["hybrid"] = True
        return list(result.values())

    def _merge_weighted(
        self,
        vector_chunks: list[dict[str, Any]],
        es_chunks: list[dict[str, Any]],
        options: RetrievalConfig,
    ) -> list[dict[str, Any]]:
        """按语义/关键词权重对双路分数归一化后加权融合，写入 hybrid_score。"""
        max_vector_score = max([item.get("vector_score", 0.0) for item in vector_chunks] or [0.0])
        max_es_score = max([item.get("es_score", 0.0) for item in es_chunks] or [0.0])
        merged = self._merge_chunks(es_chunks, vector_chunks)

        for item in merged:
            vector_score = float(item.get("vector_score") or 0)
            es_score = float(item.get("es_score") or 0)
            vector_norm = vector_score / max_vector_score if max_vector_score > 0 else 0
            es_norm = es_score / max_es_score if max_es_score > 0 else 0
            item["semantic_weight"] = options.semantic_weight
            item["keyword_weight"] = options.keyword_weight
            item["semantic_score"] = round(vector_norm, 6)
            item["keyword_score"] = round(es_norm, 6)
            item["hybrid_score"] = round(
                options.semantic_weight * vector_norm + options.keyword_weight * es_norm,
                6,
            )
            item["score"] = item["hybrid_score"]
        return merged

    def _finalize(
        self,
        chunks: list[dict[str, Any]],
        score_threshold: float,
        enable_source: bool,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """最终收尾：按分数阈值过滤、截断 top_k、按可见性裁剪来源字段。"""
        filtered = [item for item in chunks if float(item.get("score") or 0) >= score_threshold]
        return [self._apply_source_visibility(item, enable_source) for item in filtered[:top_k]]

    def _sort_and_limit(self, chunks: list[dict[str, Any]], score_key: str, top_k: int) -> list[dict[str, Any]]:
        """按指定分数键降序排序并截断到 top_k。"""
        return sorted(chunks, key=lambda item: float(item.get(score_key) or 0), reverse=True)[:top_k]

    def _apply_source_visibility(self, item: dict[str, Any], enable_source: bool) -> dict[str, Any]:
        """按 enable_source 决定是否保留 source_file / metadata 字段。"""
        result = dict(item)
        if enable_source:
            return result
        result.pop("source_file", None)
        result.pop("metadata", None)
        return result

    def _source_to_item(self, source: dict[str, Any]) -> dict[str, Any]:
        """把 ES/Milvus 原始字段统一映射为标准结果项字典。"""
        metadata = source.get("metadata") or {}
        return {
            "chunk_id": source.get("chunk_id"),
            "db_chunk_id": source.get("db_chunk_id") or metadata.get("db_chunk_id"),
            "parent_chunk_id": source.get("parent_chunk_id") or metadata.get("parent_chunk_id"),
            "document_id": source.get("document_id"),
            "tenant_id": source.get("tenant_id"),
            "kb_id": source.get("kb_id"),
            "content": source.get("content"),
            "source_file": source.get("source_file"),
            "metadata": metadata,
        }

    def _hit_distance(self, hit: Any) -> float:
        """从 Milvus 命中对象提取 distance/score 作为向量相似度分数。"""
        if isinstance(hit, dict):
            return float(hit.get("distance", hit.get("score", 0.0)) or 0.0)
        return float(getattr(hit, "distance", getattr(hit, "score", 0.0)) or 0.0)

    def _normalize_document_ids(self, document_id: DocumentIdFilter) -> list[str]:
        """把 document_id 统一规整为非空字符串列表（兼容 str/list/逗号分隔）。"""
        if document_id is None:
            return []
        if isinstance(document_id, list):
            values = document_id
        else:
            values = str(document_id).replace("\n", ",").replace(" ", ",").split(",")
        return [str(item).strip() for item in values if str(item).strip()]

    def _escape_milvus_string(self, value: str) -> str:
        """转义 Milvus 过滤表达式中的反斜杠与双引号。"""
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _effective_top_k(self, configured_top_k: int, override: int | None) -> int:
        """计算生效 top_k：有覆盖值取覆盖值（至少 1），否则用配置值。"""
        if override is None:
            return configured_top_k
        try:
            return max(1, int(override))
        except (TypeError, ValueError):
            return configured_top_k

    def _expanded_top_k(self, top_k: int) -> int:
        """召回扩样：top_k 乘以候选倍数，保证重排前有足够候选。"""
        return max(top_k, top_k * self.candidate_multiplier)

    def _hybrid_candidate_top_k(self, top_k: int) -> int:
        """混合检索候选数：取扩样值与最小候选下限的较大者。"""
        return max(self._expanded_top_k(top_k), self.min_hybrid_candidate_k)

    def _resolve_search_type(self, search_type: str) -> str:
        """校验并归一化检索模式，非法值回退为 HYBRID。"""
        normalized = str(search_type or "").strip().upper()
        if normalized in {SEARCH_TYPE_VECTOR, SEARCH_TYPE_FULLTEXT, SEARCH_TYPE_HYBRID}:
            return normalized
        return SEARCH_TYPE_HYBRID
