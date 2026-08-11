"""
上传相关数据模型模块。

定义文档详情、已存盘的上传文件、上传命令、上传事件等不可变数据类，
作为上传服务与后台索引处理之间的数据载体。

@author: ziyu
@date: 2026-07-13
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class DocumentDetail:
    """单个文档的上传详情（来自前端 document_detail 数组项）。"""

    document_id: str
    document_file: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def file_type(self) -> str:
        """从文件名提取扩展名（无点，小写）。"""
        return Path(self.document_file).suffix.lower().lstrip(".")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentDetail":
        """从 dict 构造文档详情，校验 document_id 与 document_file 必填。"""
        document_id = str(data.get("document_id") or "").strip()
        document_file = str(data.get("document_file") or data.get("file_name") or "").strip()
        if not document_id:
            raise ValueError("document_detail 中缺少 document_id。")
        if not document_file:
            raise ValueError(f"文档 {document_id} 缺少 document_file。")
        return cls(document_id=document_id, document_file=document_file, raw=data)


@dataclass(frozen=True)
class StoredUploadFile:
    """已落盘到临时目录的上传文件记录。"""

    detail: DocumentDetail
    path: Path
    temp_dir: Path
    original_name: str
    file_size: int


@dataclass(frozen=True)
class UploadCommand:
    """上传命令：租户/知识库 + 一批已存盘文件。"""

    tenant_id: str
    kb_id: str
    files: list[StoredUploadFile]

    @property
    def document_ids(self) -> list[str]:
        """提取本批次全部文档 ID。"""
        return [item.detail.document_id for item in self.files]


@dataclass(frozen=True)
class DocumentUploadRequested:
    """文档上传事件：发布到事件总线触发后台索引处理。"""

    event_id: str
    tenant_id: str
    kb_id: str
    files: list[StoredUploadFile]

    @classmethod
    def from_command(cls, command: UploadCommand) -> "DocumentUploadRequested":
        """从上传命令构造事件，生成唯一 event_id。"""
        return cls(
            event_id=str(uuid4()),
            tenant_id=command.tenant_id,
            kb_id=command.kb_id,
            files=command.files,
        )
