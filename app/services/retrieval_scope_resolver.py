"""
检索范围解析器：把前端传入的多种范围参数归一化为最终的 document_id 列表。

支持 document_id(s)、folder_id(s)、file_node_id(s)、node_id(s)、selected_nodes 等多种入参，
文件夹/文件节点会经 FolderRepository 展开成其下的 document_id。

@author: ziyu
@date: 2026-07-27
"""
from dataclasses import asdict, dataclass
from typing import Any

from app.repositories.folder_repository import FolderRepository
from app.services.folder_models import NODE_TYPE_DIR, NODE_TYPE_FILE


@dataclass(frozen=True)
class RetrievalScope:
    """检索范围：聚合后最终参与检索的文档与各来源节点列表。"""

    document_ids: list[str]
    manual_document_ids: list[str]
    folder_ids: list[int]
    file_node_ids: list[int]
    mixed_node_ids: list[int]
    limited: bool

    def document_filter(self) -> str | list[str] | None:
        """返回供检索服务使用的 document_id 过滤值：无限制返回 None，单值返回 str，多值返回列表。"""
        if not self.limited:
            return None
        if len(self.document_ids) == 1:
            return self.document_ids[0]
        return self.document_ids

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典，用于接口返回或日志。"""
        return asdict(self)


class RetrievalScopeResolver:
    """把混合的检索范围参数解析为统一 RetrievalScope。"""

    def __init__(self, folder_repository: FolderRepository):
        """注入 FolderRepository，用于把树节点展开为 document_id。"""
        self.folder_repository = folder_repository

    def resolve(self, tenant_id: Any, kb_id: Any, payload: dict[str, Any]) -> RetrievalScope:
        """主入口：解析 payload 中各类范围参数→展开树节点→聚合去重→构造 RetrievalScope。"""
        tenant_id_int = self._required_int(tenant_id, "tenant_id")
        kb_id_int = self._required_int(kb_id, "kb_id")

        manual_document_ids = self._document_ids(payload.get("document_ids"))
        if not manual_document_ids:
            manual_document_ids = self._document_ids(payload.get("document_id"))

        folder_ids = self._int_ids(payload.get("folder_ids"))
        folder_ids.extend(self._int_ids(payload.get("folder_id")))
        file_node_ids = self._int_ids(payload.get("file_node_ids"))
        file_node_ids.extend(self._int_ids(payload.get("file_node_id")))
        file_node_ids.extend(self._int_ids(payload.get("file_ids")))
        mixed_node_ids = self._int_ids(payload.get("node_ids"))
        mixed_node_ids.extend(self._int_ids(payload.get("node_id")))
        mixed_node_ids.extend(self._int_ids(payload.get("selected_node_ids")))

        selected_document_ids, selected_folder_ids, selected_file_node_ids, selected_mixed_ids = (
            self._selected_nodes(payload.get("selected_nodes"))
        )
        manual_document_ids.extend(selected_document_ids)
        folder_ids.extend(selected_folder_ids)
        file_node_ids.extend(selected_file_node_ids)
        mixed_node_ids.extend(selected_mixed_ids)

        folder_ids = self._unique_ints(folder_ids)
        file_node_ids = self._unique_ints(file_node_ids)
        mixed_node_ids = self._unique_ints(mixed_node_ids)
        tree_node_ids = self._unique_ints([*folder_ids, *file_node_ids, *mixed_node_ids])
        tree_document_ids = self.folder_repository.resolve_document_ids_by_node_ids(
            tenant_id=tenant_id_int,
            kb_id=kb_id_int,
            node_ids=tree_node_ids,
        )

        document_ids = self._unique_strings([*manual_document_ids, *tree_document_ids])
        limited = bool(manual_document_ids or tree_node_ids or payload.get("selected_nodes"))
        return RetrievalScope(
            document_ids=document_ids,
            manual_document_ids=self._unique_strings(manual_document_ids),
            folder_ids=folder_ids,
            file_node_ids=file_node_ids,
            mixed_node_ids=mixed_node_ids,
            limited=limited,
        )

    def _selected_nodes(self, value: Any) -> tuple[list[str], list[int], list[int], list[int]]:
        """解析 selected_nodes 列表，按节点类型分桶为 (document_ids, folder_ids, file_node_ids, mixed_node_ids)。"""
        document_ids: list[str] = []
        folder_ids: list[int] = []
        file_node_ids: list[int] = []
        mixed_node_ids: list[int] = []
        for item in self._list_value(value):
            if isinstance(item, dict):
                node_id = self._optional_int(item.get("id") or item.get("node_id"))
                node_type = self._optional_int(item.get("node_type") or item.get("type"))
                if node_id is None:
                    document_ids.extend(self._document_ids(item.get("document_id")))
                    continue
                if node_type == NODE_TYPE_DIR:
                    folder_ids.append(node_id)
                elif node_type == NODE_TYPE_FILE:
                    file_node_ids.append(node_id)
                else:
                    mixed_node_ids.append(node_id)
            else:
                node_id = self._optional_int(item)
                if node_id is not None:
                    mixed_node_ids.append(node_id)
        return document_ids, folder_ids, file_node_ids, mixed_node_ids

    def _document_ids(self, value: Any) -> list[str]:
        """把入参规整为去重非空 document_id 字符串列表。"""
        return self._unique_strings(str(item).strip() for item in self._list_value(value) if str(item).strip())

    def _int_ids(self, value: Any) -> list[int]:
        """把入参规整为去重正整数 id 列表。"""
        result = []
        for item in self._list_value(value):
            number = self._optional_int(item)
            if number is not None and number > 0:
                result.append(number)
        return self._unique_ints(result)

    def _list_value(self, value: Any) -> list[Any]:
        """把任意入参规整为列表：list/tuple 直接转，字符串按中英文逗号/空格/换行拆分。"""
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        return [item for item in str(value).replace("\n", ",").replace("，", ",").replace(" ", ",").split(",")]

    def _required_int(self, value: Any, field: str) -> int:
        """取必填正整数，缺失或非法抛 ValueError。"""
        number = self._optional_int(value)
        if number is None or number < 1:
            raise ValueError(f"缺少 {field}。")
        return number

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        """宽松地把值转成 int，无法转换返回 None。"""
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _unique_ints(values: list[int]) -> list[int]:
        """对整数列表去重并保持原顺序。"""
        result: list[int] = []
        seen: set[int] = set()
        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result

    @staticmethod
    def _unique_strings(values) -> list[str]:
        """对字符串列表去重（去空白）并保持原顺序。"""
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result
