"""
文件夹/文件树节点数据模型：定义 FolderModels 节点及其序列化方法。

同时承载目录与文件两类节点（node_type=1 目录 / 2 文件），支持从字典、SQL 行映射构造，
并输出给前端（to_dict）或 ES（to_es_dict）。

@author: ziyu
@date: 2026-07-27
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


# 节点类型常量：目录 / 文件
NODE_TYPE_DIR = 1
NODE_TYPE_FILE = 2


@dataclass
class FolderModels:
    """文件树节点：目录或文件的统一数据结构。"""

    tenant_id: int
    kb_id: int
    name: str
    node_type: Optional[int] = None
    parent_id: int = 0
    path: str = ""
    full_path: str = ""
    document_id: Optional[int] = None
    id: Optional[int] = None
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None
    size: int = 0
    level: int = 0
    file_url: Optional[str] = None
    file_hash: Optional[str] = None
    extension: Optional[str] = None
    create_user: Optional[str] = None
    create_user_id: Optional[int] = None
    name_pinyin: Optional[str] = None
    sort: int = 0
    status: int = 1
    matched: bool = False
    children: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FolderModels":
        """从前端字典构造节点（兼容 id/node_id、full_path/tree_path/folder_path 等别名）。"""
        return cls(
            id=data.get("id") or data.get("node_id"),
            tenant_id=data.get("tenant_id"),
            kb_id=data.get("kb_id"),
            node_type=data.get("node_type"),
            name=str(data.get("name") or "").strip(),
            parent_id=data.get("parent_id", 0),
            path=str(data.get("path") or ""),
            full_path=str(data.get("full_path") or data.get("tree_path") or data.get("folder_path") or ""),
            document_id=data.get("document_id"),
            size=data.get("size") or 0,
            level=data.get("level") or 0,
            file_url=data.get("file_url"),
            file_hash=data.get("file_hash"),
            sort=data.get("sort") or 0,
            status=data.get("status") or 1,
            create_user=data.get("create_user"),
            create_user_id=data.get("create_user_id"),
            extension=data.get("extension"),
        )

    @classmethod
    def from_mapping(cls, row: Any) -> "FolderModels":
        """从 SQL 行映射构造节点（兼容 SQLAlchemy Row._mapping 与普通 dict）。"""
        mapping = row._mapping if hasattr(row, "_mapping") else row
        return cls(
            id=mapping.get("id"),
            tenant_id=mapping.get("tenant_id"),
            kb_id=mapping.get("kb_id"),
            parent_id=mapping.get("parent_id") or 0,
            node_type=mapping.get("node_type"),
            name=mapping.get("name") or "",
            extension=mapping.get("extension"),
            size=mapping.get("size") or 0,
            path=mapping.get("path") or "",
            level=mapping.get("level") or 0,
            file_url=mapping.get("file_url"),
            file_hash=mapping.get("file_hash"),
            sort=mapping.get("sort") or 0,
            status=mapping.get("status") if mapping.get("status") is not None else 1,
            create_time=mapping.get("create_time"),
            update_time=mapping.get("update_time"),
            create_user=mapping.get("create_user"),
            create_user_id=mapping.get("create_user_id"),
            document_id=mapping.get("document_id"),
        )

    def to_dict(self, include_children: bool = True) -> dict[str, Any]:
        """序列化为前端用的字典，可选是否带 children。"""
        data = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "kb_id": self.kb_id,
            "node_type": self.node_type,
            "name": self.name,
            "name_pinyin": self.name_pinyin,
            "extension": self.extension,
            "parent_id": self.parent_id,
            "path": self.path,
            "full_path": self.full_path,
            "level": self.level,
            "size": self.size,
            "file_url": self.file_url,
            "file_hash": self.file_hash,
            "sort": self.sort,
            "status": self.status,
            "create_user": self.create_user,
            "create_user_id": self.create_user_id,
            "document_id": self.document_id,
            "create_time": self._format_time(self.create_time),
            "update_time": self._format_time(self.update_time),
            "matched": self.matched,
        }
        if include_children:
            data["children"] = self.children
        return data

    def to_es_dict(self) -> dict[str, Any]:
        """序列化为 ES 索引文档（不带 children、不带 matched）。"""
        data = self.to_dict(include_children=False)
        data.pop("matched", None)
        return data

    @staticmethod
    def _format_time(value: Any) -> Optional[str]:
        """把时间值格式化为 ISO 字符串，None 原样返回。"""
        if value is None:
            return None
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%dT%H:%M:%S")
        return str(value)
