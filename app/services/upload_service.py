"""
文档上传服务模块。

负责解析上传请求、落盘临时文件、标记文档状态、发布异步入库事件。
是上传接口与后台索引处理之间的协调层。

@author: ziyu
@date: 2026-07-13
"""
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from werkzeug.datastructures import FileStorage, MultiDict

from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.services.event_bus import AsyncEventBus
from app.services.upload_models import (
    DocumentDetail,
    DocumentUploadRequested,
    StoredUploadFile,
    UploadCommand,
)


class UploadRequestError(Exception):
    """上传请求参数校验失败异常。"""
    pass


class UploadRequestParser:
    """解析上传请求：校验 tenant_id/kb_id/files/document_detail，返回租户、知识库、文件与文档详情列表。"""

    def parse(self, files: list[FileStorage], form: MultiDict[str, Any]) -> tuple[str, str, list[FileStorage], list[DocumentDetail]]:
        """校验并解析上传表单，返回 (tenant_id, kb_id, files, details)。校验失败抛 UploadRequestError。"""
        tenant_id = str(form.get("tenant_id") or "").strip()
        kb_id = str(form.get("kb_id") or "").strip()
        if not tenant_id:
            raise UploadRequestError("缺少 tenant_id。")
        if not kb_id:
            raise UploadRequestError("缺少 kb_id。")
        if not files:
            raise UploadRequestError("请先上传文件。")

        detail_text = form.get("document_detail")
        if not detail_text:
            raise UploadRequestError("缺少 document_detail。")

        try:
            detail_data = json.loads(detail_text)
        except json.JSONDecodeError as exc:
            raise UploadRequestError(f"document_detail 不是合法 JSON: {exc}") from exc

        if not isinstance(detail_data, list):
            raise UploadRequestError("document_detail 必须是数组。")
        if len(detail_data) < len(files):
            raise UploadRequestError("document_detail 数量不能少于上传文件数量。")

        details = []
        for item in detail_data[: len(files)]:
            if not isinstance(item, dict):
                raise UploadRequestError("document_detail 数组元素必须是对象。")
            try:
                details.append(DocumentDetail.from_dict(item))
            except ValueError as exc:
                raise UploadRequestError(str(exc)) from exc

        return tenant_id, kb_id, files, details


class UploadFileStorage:
    """把上传文件落到临时目录，返回带路径与大小的存储记录。"""

    def save(self, files: list[FileStorage], details: list[DocumentDetail]) -> list[StoredUploadFile]:
        """将每个上传文件存入独立临时目录，返回存储记录列表。"""
        stored_files: list[StoredUploadFile] = []
        for uploaded_file, detail in zip(files, details):
            original_name = (uploaded_file.filename or detail.document_file).strip()
            if not original_name:
                raise UploadRequestError(f"文档 {detail.document_id} 的文件名为空。")

            safe_name = Path(original_name).name
            temp_dir = Path(tempfile.mkdtemp())
            temp_path = temp_dir / safe_name
            uploaded_file.save(temp_path)
            stored_files.append(
                StoredUploadFile(
                    detail=detail,
                    path=temp_path,
                    temp_dir=temp_dir,
                    original_name=original_name,
                    file_size=temp_path.stat().st_size,
                )
            )
        return stored_files


class DocumentUploadService:
    """文档上传服务：解析请求→落盘→标记 UPLOADING→发布异步事件，供后台处理。"""

    def __init__(
        self,
        repository: KnowledgeBaseRepository,
        event_bus: AsyncEventBus,
        parser: UploadRequestParser | None = None,
        storage: UploadFileStorage | None = None,
    ):
        self.repository = repository
        self.event_bus = event_bus
        self.parser = parser or UploadRequestParser()
        self.storage = storage or UploadFileStorage()

    def submit(self, files: list[FileStorage], form: MultiDict[str, Any]) -> dict[str, Any]:
        """提交上传：解析→落盘→标记状态→发布异步入库事件，返回事件 ID 与文档 ID。失败回滚临时文件。"""
        tenant_id, kb_id, upload_files, details = self.parser.parse(files, form)
        stored_files = self.storage.save(upload_files, details)
        command = UploadCommand(tenant_id=tenant_id, kb_id=kb_id, files=stored_files)

        try:
            self.repository.mark_documents_uploading(command.document_ids)
            event = DocumentUploadRequested.from_command(command)
            futures = self.event_bus.publish(event)
        except Exception:
            for stored_file in stored_files:
                shutil.rmtree(stored_file.temp_dir, ignore_errors=True)
            raise

        return {
            "event_id": event.event_id,
            "tenant_id": tenant_id,
            "kb_id": kb_id,
            "document_ids": command.document_ids,
            "queued_handlers": len(futures),
        }
