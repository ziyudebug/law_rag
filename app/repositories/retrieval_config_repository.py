"""
检索配置仓储：按 (tenant_id, kb_id) 持久化检索参数到 MySQL。

使用 kb_retrieval_config 表，UPSERT 写入、按 status=1 读取，缺省时回退默认配置。

@author: ziyu
@date: 2026-07-16
"""
from typing import Any

from sqlalchemy import text

from app.core.database import db
from app.services.retrieval_config_models import (
    DEFAULT_ENABLE_SOURCE,
    DEFAULT_HYBRID_STRATEGY,
    DEFAULT_KEYWORD_WEIGHT,
    DEFAULT_RERANK_MODEL,
    DEFAULT_RETRIEVAL_MODE,
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_SEMANTIC_WEIGHT,
    DEFAULT_TOP_K,
    DEFAULT_USE_RERANK,
    RetrievalConfig,
)


class RetrievalConfigRepository:
    """检索配置的 MySQL 读写仓储。"""

    def get(self, tenant_id: str, kb_id: str) -> RetrievalConfig | None:
        """按 tenant+kb 读取有效配置，无则返回 None。"""
        with db.SessionLocal() as session:
            row = session.execute(
                text(
                    """
                    SELECT *
                    FROM kb_retrieval_config
                    WHERE tenant_id = :tenant_id
                      AND kb_id = :kb_id
                      AND status = 1
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id, "kb_id": kb_id},
            ).mappings().first()

        if row is None:
            return None
        return self._row_to_config(dict(row))

    def get_or_default(self, tenant_id: str, kb_id: str) -> RetrievalConfig:
        """读取配置，不存在则返回默认配置。"""
        return self.get(tenant_id, kb_id) or RetrievalConfig.default(tenant_id, kb_id)

    def save(self, config: RetrievalConfig) -> RetrievalConfig:
        """归一化后 UPSERT 写入配置，返回归一化后的对象。"""
        normalized = config.normalized()
        with db.SessionLocal() as session:
            with session.begin():
                session.execute(
                    text(
                        """
                        INSERT INTO kb_retrieval_config (
                            tenant_id, kb_id, retrieval_mode, use_rerank, rerank_model,
                            hybrid_strategy, semantic_weight, keyword_weight,
                            top_k, enable_source, score_threshold, status
                        )
                        VALUES (
                            :tenant_id, :kb_id, :retrieval_mode, :use_rerank, :rerank_model,
                            :hybrid_strategy, :semantic_weight, :keyword_weight,
                            :top_k, :enable_source, :score_threshold, 1
                        )
                        ON DUPLICATE KEY UPDATE
                            retrieval_mode = VALUES(retrieval_mode),
                            use_rerank = VALUES(use_rerank),
                            rerank_model = VALUES(rerank_model),
                            hybrid_strategy = VALUES(hybrid_strategy),
                            semantic_weight = VALUES(semantic_weight),
                            keyword_weight = VALUES(keyword_weight),
                            top_k = VALUES(top_k),
                            enable_source = VALUES(enable_source),
                            score_threshold = VALUES(score_threshold),
                            status = 1,
                            update_time = CURRENT_TIMESTAMP
                        """
                    ),
                    self._config_to_params(normalized),
                )
        return normalized

    def _row_to_config(self, row: dict[str, Any]) -> RetrievalConfig:
        """把数据库行映射为 RetrievalConfig（缺失字段用默认值），并归一化。"""
        return RetrievalConfig(
            tenant_id=str(row["tenant_id"]),
            kb_id=str(row["kb_id"]),
            retrieval_mode=str(row.get("retrieval_mode") or DEFAULT_RETRIEVAL_MODE),
            use_rerank=bool(row.get("use_rerank")) if row.get("use_rerank") is not None else DEFAULT_USE_RERANK,
            rerank_model=str(row.get("rerank_model") or DEFAULT_RERANK_MODEL),
            hybrid_strategy=str(row.get("hybrid_strategy") or DEFAULT_HYBRID_STRATEGY),
            semantic_weight=float(row.get("semantic_weight") or DEFAULT_SEMANTIC_WEIGHT),
            keyword_weight=float(row.get("keyword_weight") or DEFAULT_KEYWORD_WEIGHT),
            top_k=int(row.get("top_k") or DEFAULT_TOP_K),
            enable_source=(
                bool(row.get("enable_source"))
                if row.get("enable_source") is not None
                else DEFAULT_ENABLE_SOURCE
            ),
            score_threshold=float(row.get("score_threshold") or DEFAULT_SCORE_THRESHOLD),
        ).normalized()

    def _config_to_params(self, config: RetrievalConfig) -> dict[str, Any]:
        """把配置对象转为 SQL 参数字典（布尔转 int）。"""
        return {
            "tenant_id": config.tenant_id,
            "kb_id": config.kb_id,
            "retrieval_mode": config.retrieval_mode,
            "use_rerank": int(config.use_rerank),
            "rerank_model": config.rerank_model,
            "hybrid_strategy": config.hybrid_strategy,
            "semantic_weight": config.semantic_weight,
            "keyword_weight": config.keyword_weight,
            "top_k": config.top_k,
            "enable_source": int(config.enable_source),
            "score_threshold": config.score_threshold,
        }
