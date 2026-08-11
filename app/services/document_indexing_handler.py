"""
文档索引处理模块。

事件总线的订阅者：接收到 DocumentUploadRequested 事件后，对每个文件依次执行
文本读取→父子分段→向量化→入库→双写索引，并同步文档状态；失败标记 FAILED，结束清理临时文件。

@author: ziyu
@date: 2026-07-13
"""
import shutil
import traceback

from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.services.document_text_reader import DocumentTextReader
from app.services.embedding_service import DashScopeEmbeddingService
from app.services.parent_child_chunker import ParentChildChunker
from app.services.search_index_service import SearchIndexService
from app.services.upload_models import DocumentUploadRequested, StoredUploadFile


class DocumentIndexingHandler:
    """文档入库处理器：解析→分段→向量化→入库→索引→状态流转。"""

    def __init__(
        self,
        repository: KnowledgeBaseRepository,
        text_reader: DocumentTextReader,
        chunker: ParentChildChunker,
        embedding_service: DashScopeEmbeddingService,
        index_service: SearchIndexService,
    ):
        self.repository = repository
        self.text_reader = text_reader
        self.chunker = chunker
        self.embedding_service = embedding_service
        self.index_service = index_service

    def handle(self, event: DocumentUploadRequested) -> None:
        """处理上传事件：逐个文件入库，异常时标记 FAILED，结束清理临时文件。"""
        for stored_file in event.files:
            try:
                self._process_file(event, stored_file)
            except Exception:
                traceback.print_exc()
                try:
                    self.repository.mark_document_failed(stored_file.detail.document_id)
                except Exception:
                    traceback.print_exc()
            finally:
                shutil.rmtree(stored_file.temp_dir, ignore_errors=True)

    def _process_file(self, event: DocumentUploadRequested, stored_file: StoredUploadFile) -> None:
        """处理单个文件：读取文本→分段→向量化→入库→双写索引→标记 DONE。"""
        detail = stored_file.detail
        file_type = detail.file_type or stored_file.path.suffix.lower().lstrip(".")
        # 标记文档进入解析阶段
        self.repository.mark_document_parsing(
            document_id=detail.document_id,
            file_name=stored_file.original_name,
            file_type=file_type.upper(),
            file_size=stored_file.file_size,
        )

        # 1. 读取文档文本（PDF/Office/纯文本等）
        document_text, extraction_metadata = self.text_reader.read(
            file_path=stored_file.path,
            original_filename=stored_file.original_name,
        )
        merged_detail = self._merge_extraction_metadata(detail, extraction_metadata)
        # 2. 父子分段
        chunk_plan = self.chunker.split(document_text)

        # 3. 向量化
        self.repository.mark_document_embedding(detail.document_id)
        vectors = self.embedding_service.embed_texts([child.content for child in chunk_plan.children])
        # 4. 入库（MySQL 父子分段）+ 双写索引（Milvus + ES）
        persisted_chunks = self.repository.replace_document_chunks(
            tenant_id=event.tenant_id,
            kb_id=event.kb_id,
            document_detail=merged_detail,
            source_file=stored_file.original_name,
            chunk_plan=chunk_plan,
        )
        self.index_service.replace_document_chunks(
            tenant_id=event.tenant_id,
            kb_id=event.kb_id,
            document_id=detail.document_id,
            chunks=persisted_chunks,
            vectors=vectors,
        )
        # 5. 标记完成
        self.repository.mark_document_done(
            document_id=detail.document_id,
            chunk_count=len(persisted_chunks),
        )

    def _merge_extraction_metadata(self, detail, extraction_metadata):
        """把文本抽取元数据合并进文档详情的 raw 字段。"""
        return type(detail)(
            document_id=detail.document_id,
            document_file=detail.document_file,
            raw={
                **detail.raw,
                "extraction": extraction_metadata,
            },
        )
