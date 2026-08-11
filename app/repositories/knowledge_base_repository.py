"""
知识库仓储：管理文档状态流转与父子分块的 MySQL 持久化。

文档状态：UPLOADING→PARSING→EMBEDDING→DONE / FAILED。
分块写入：先清旧→写父块→写子块及元数据→返回待索引的 PersistedChildChunk 列表。

@author: ziyu
@date: 2026-07-13
"""
from collections.abc import Iterable
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.database import db
from app.services.chunk_models import (
    ChildChunkDraft,
    ParentChildChunkPlan,
    ParentChunkDraft,
    PersistedChildChunk,
)
from app.services.upload_models import DocumentDetail


class DocumentStatus:
    """文档处理状态常量。"""

    UPLOADING = "UPLOADING"
    PARSING = "PARSING"
    EMBEDDING = "EMBEDDING"
    DONE = "DONE"
    FAILED = "FAILED"


class KnowledgeBaseRepository:
    """知识库文档与分块的 MySQL 持久化仓储。"""

    def mark_documents_uploading(self, document_ids: Iterable[str]) -> None:
        """把多个文档标记为 UPLOADING（上传中）。"""
        with db.SessionLocal() as session:
            with session.begin():
                for document_id in document_ids:
                    self._update_status(session, document_id, DocumentStatus.UPLOADING)

    def mark_document_parsing(
        self,
        document_id: str,
        file_name: str,
        file_type: str,
        file_size: int,
    ) -> None:
        """把文档标记为 PARSING，并更新文件名/类型/大小。"""
        with db.SessionLocal() as session:
            with session.begin():
                session.execute(
                    text(
                        """
                        UPDATE kb_document
                        SET status = :status,
                            file_name = :file_name,
                            file_type = :file_type,
                            file_size = :file_size
                        WHERE id = :document_id
                        """
                    ),
                    {
                        "status": DocumentStatus.PARSING,
                        "file_name": file_name,
                        "file_type": file_type,
                        "file_size": file_size,
                        "document_id": document_id,
                    },
                )

    def mark_document_embedding(self, document_id: str) -> None:
        """把文档标记为 EMBEDDING（向量化中）。"""
        with db.SessionLocal() as session:
            with session.begin():
                self._update_status(session, document_id, DocumentStatus.EMBEDDING)

    def mark_document_done(self, document_id: str, chunk_count: int) -> None:
        """把文档标记为 DONE，并写入分块数量。"""
        with db.SessionLocal() as session:
            with session.begin():
                session.execute(
                    text(
                        """
                        UPDATE kb_document
                        SET status = :status,
                            chunk_count = :chunk_count
                        WHERE id = :document_id
                        """
                    ),
                    {
                        "status": DocumentStatus.DONE,
                        "chunk_count": chunk_count,
                        "document_id": document_id,
                    },
                )

    def mark_document_failed(self, document_id: str) -> None:
        """把文档标记为 FAILED。"""
        with db.SessionLocal() as session:
            with session.begin():
                self._update_status(session, document_id, DocumentStatus.FAILED)

    def replace_document_chunks(
        self,
        tenant_id: str,
        kb_id: str,
        document_detail: DocumentDetail,
        source_file: str,
        chunk_plan: ParentChildChunkPlan,
    ) -> list[PersistedChildChunk]:
        """替换文档分块：清旧→写父块→写子块及元数据，返回待索引的持久化子块列表。"""
        with db.SessionLocal() as session:
            with session.begin():
                self._clear_document_chunks(session, tenant_id, document_detail.document_id)
                parent_ids = self._insert_parent_chunks(
                    session=session,
                    tenant_id=tenant_id,
                    document_id=document_detail.document_id,
                    parents=chunk_plan.parents,
                )
                return self._insert_child_chunks(
                    session=session,
                    tenant_id=tenant_id,
                    kb_id=kb_id,
                    document_detail=document_detail,
                    source_file=source_file,
                    parents=chunk_plan.parents,
                    children=chunk_plan.children,
                    parent_ids=parent_ids,
                )

    def _update_status(self, session: Session, document_id: str, status: str) -> None:
        """更新单条文档状态。"""
        session.execute(
            text("UPDATE kb_document SET status = :status WHERE id = :document_id"),
            {"status": status, "document_id": document_id},
        )

    def _clear_document_chunks(self, session: Session, tenant_id: str, document_id: str) -> None:
        """清空文档的子块元数据、子块、父块（顺序依赖外键）。"""
        session.execute(
            text(
                """
                DELETE FROM kb_chunk_metadata
                WHERE chunk_id IN (
                    SELECT id FROM kb_document_chunk
                    WHERE tenant_id = :tenant_id AND document_id = :document_id
                )
                """
            ),
            {"tenant_id": tenant_id, "document_id": document_id},
        )
        session.execute(
            text(
                """
                DELETE FROM kb_document_chunk
                WHERE tenant_id = :tenant_id AND document_id = :document_id
                """
            ),
            {"tenant_id": tenant_id, "document_id": document_id},
        )
        session.execute(
            text(
                """
                DELETE FROM kb_document_parent_chunk
                WHERE tenant_id = :tenant_id AND document_id = :document_id
                """
            ),
            {"tenant_id": tenant_id, "document_id": document_id},
        )

    def _insert_parent_chunks(
        self,
        session: Session,
        tenant_id: str,
        document_id: str,
        parents: list[ParentChunkDraft],
    ) -> dict[int, int]:
        """批量插入父块，返回 {chunk_no: 自增主键} 映射。"""
        parent_ids: dict[int, int] = {}
        for parent in parents:
            result = session.execute(
                text(
                    """
                    INSERT INTO kb_document_parent_chunk
                        (tenant_id, document_id, chunk_no, content, page_no, chapter, article, token_count)
                    VALUES
                        (:tenant_id, :document_id, :chunk_no, :content, :page_no, :chapter, :article, :token_count)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "chunk_no": parent.chunk_no,
                    "content": parent.content,
                    "page_no": parent.page_no,
                    "chapter": parent.chapter,
                    "article": parent.article,
                    "token_count": parent.token_count,
                },
            )
            parent_ids[parent.chunk_no] = self._lastrowid(session, result)
        return parent_ids

    def _insert_child_chunks(
        self,
        session: Session,
        tenant_id: str,
        kb_id: str,
        document_detail: DocumentDetail,
        source_file: str,
        parents: list[ParentChunkDraft],
        children: list[ChildChunkDraft],
        parent_ids: dict[int, int],
    ) -> list[PersistedChildChunk]:
        """批量插入子块及其元数据，组装并返回 PersistedChildChunk 列表。"""
        parents_by_no = {parent.chunk_no: parent for parent in parents}
        persisted: list[PersistedChildChunk] = []
        for child in children:
            parent_id = parent_ids[child.parent_no]
            result = session.execute(
                text(
                    """
                    INSERT INTO kb_document_chunk
                        (
                            tenant_id, document_id, chunk_no, content, page_no,
                            chapter, article, token_count, milvus_id, parent_chunk_id
                        )
                    VALUES
                        (
                            :tenant_id, :document_id, :chunk_no, :content, :page_no,
                            :chapter, :article, :token_count, :milvus_id, :parent_chunk_id
                        )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "document_id": document_detail.document_id,
                    "chunk_no": child.chunk_no,
                    "content": child.content,
                    "page_no": child.page_no,
                    "chapter": child.chapter,
                    "article": child.article,
                    "token_count": child.token_count,
                    "milvus_id": child.milvus_id,
                    "parent_chunk_id": parent_id,
                },
            )
            child_id = self._lastrowid(session, result)
            self._insert_chunk_metadata(session, child_id, document_detail.raw, child.metadata)
            parent = parents_by_no[child.parent_no]
            metadata = self._build_index_metadata(
                child=child,
                child_id=child_id,
                parent_id=parent_id,
                kb_id=kb_id,
                document_detail=document_detail,
            )
            persisted.append(
                PersistedChildChunk(
                    id=child_id,
                    chunk_no=child.chunk_no,
                    document_id=document_detail.document_id,
                    tenant_id=tenant_id,
                    kb_id=kb_id,
                    content=child.content,
                    source_file=source_file,
                    milvus_id=child.milvus_id,
                    parent_chunk_id=parent_id,
                    parent_content=parent.content,
                    metadata=metadata,
                )
            )
        return persisted

    def _insert_chunk_metadata(
        self,
        session: Session,
        child_id: int,
        document_metadata: dict[str, Any],
        chunk_metadata: dict[str, Any],
    ) -> None:
        """插入子块的法规元数据（law_name/industry 等），全为空则跳过。"""
        metadata = self._metadata_fields(document_metadata, chunk_metadata)
        if not any(metadata.values()):
            return
        session.execute(
            text(
                """
                INSERT INTO kb_chunk_metadata
                    (chunk_id, law_name, industry, pollutant, behavior, penalty, region)
                VALUES
                    (:chunk_id, :law_name, :industry, :pollutant, :behavior, :penalty, :region)
                """
            ),
            {"chunk_id": child_id, **metadata},
        )

    def _build_index_metadata(
        self,
        child: ChildChunkDraft,
        child_id: int,
        parent_id: int,
        kb_id: str,
        document_detail: DocumentDetail,
    ) -> dict[str, Any]:
        """组装写入向量/全文索引用的合并元数据（文档级 + 子块级 + 关联 id）。"""
        return {
            **document_detail.raw,
            **child.metadata,
            "kb_id": kb_id,
            "db_chunk_id": child_id,
            "parent_chunk_id": parent_id,
            "document_file": document_detail.document_file,
            "file_type": document_detail.file_type,
        }

    def _metadata_fields(
        self,
        document_metadata: dict[str, Any],
        chunk_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """合并文档级与子块级法规元数据字段（文档级优先）。"""
        return {
            "law_name": document_metadata.get("law_name") or chunk_metadata.get("law_name"),
            "industry": document_metadata.get("industry") or chunk_metadata.get("industry"),
            "pollutant": document_metadata.get("pollutant") or chunk_metadata.get("pollutant"),
            "behavior": document_metadata.get("behavior") or chunk_metadata.get("behavior"),
            "penalty": document_metadata.get("penalty") or chunk_metadata.get("penalty"),
            "region": document_metadata.get("region") or chunk_metadata.get("region"),
        }

    def _lastrowid(self, session: Session, result: CursorResult) -> int:
        """获取上一条 INSERT 的自增主键：优先取 lastrowid，否则查 LAST_INSERT_ID()。"""
        lastrowid = getattr(result, "lastrowid", None)
        if lastrowid:
            return int(lastrowid)
        return int(session.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())
