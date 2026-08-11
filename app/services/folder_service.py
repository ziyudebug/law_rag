"""
文件树服务：管理知识库下目录/文件节点的增删改查与树形检索。

数据双写 MySQL（FolderRepository）与 ES（文件树索引），支持按 full_path 路径自动建目录、
按关键词在 ES/MySQL 检索并回填匹配节点的祖先与子节点。

@author: ziyu
@date: 2026-07-27
"""
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable, Optional

from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch.helpers import BulkIndexError, bulk
from pypinyin import lazy_pinyin

from app.core.config import settings
from app.repositories.folder_repository import FolderRepository
from app.services.folder_models import FolderModels, NODE_TYPE_DIR, NODE_TYPE_FILE


class FolderServiceError(Exception):
    """文件树业务异常，携带 HTTP 状态码。"""

    def __init__(self, message: str, status_code: int = 400):
        """初始化异常消息与状态码（默认 400）。"""
        super().__init__(message)
        self.status_code = status_code


class FolderNotFoundError(FolderServiceError):
    """节点不存在异常（404）。"""

    def __init__(self, message: str = "文件树节点不存在或已删除。"):
        """初始化为 404 未找到异常。"""
        super().__init__(message, status_code=404)


class FolderService:
    """文件树业务服务：封装节点 CRUD、路径解析、树检索与 ES 同步。"""

    def __init__(
        self,
        repository: FolderRepository,
        es_client: Elasticsearch,
        es_index_name: str | None = None,
    ):
        """注入 FolderRepository 与 ES 客户端，确定文件树索引名。"""
        self.es = es_client
        self.repository = repository
        self.es_index_name = es_index_name or settings.es_file_tree_index_name

    def create(self, data: FolderModels | dict[str, Any]) -> dict[str, Any]:
        """创建节点：解析路径→自动补建父目录→入库→回填全路径→索引到 ES。"""
        payload = self._payload(data)
        tenant_id = self._required_int(payload, "tenant_id", min_value=1)
        kb_id = self._required_int(payload, "kb_id", min_value=1)
        node_type = self._node_type(payload)
        create_user = self._optional_str(payload.get("create_user"))
        create_user_id = self._optional_int(payload.get("create_user_id"), "create_user_id", min_value=0)

        parent_id = self._optional_int(payload.get("parent_id"), "parent_id", min_value=0)
        if parent_id is None:
            parent_id = 0

        path_parts = self._path_parts(payload)
        name = self._optional_str(payload.get("name"))
        if path_parts:
            if name:
                parent_parts = path_parts[:-1] if path_parts[-1] == name else path_parts
            else:
                name = path_parts[-1]
                parent_parts = path_parts[:-1]
            parent_id = self._ensure_directory_path(
                tenant_id=tenant_id,
                kb_id=kb_id,
                base_parent_id=parent_id,
                parts=parent_parts,
                create_user=create_user,
                create_user_id=create_user_id,
            )
        if not name:
            name = self._default_name(payload)

        name = self._required_name(name)
        file_url = self._file_url(payload, node_type=node_type, path_parts=path_parts)
        model = FolderModels(
            tenant_id=tenant_id,
            kb_id=kb_id,
            parent_id=parent_id,
            node_type=node_type,
            name=name,
            extension=self._extension(name=name, node_type=node_type, value=payload.get("extension")),
            size=self._optional_int(payload.get("size"), "size", min_value=0) or 0,
            file_url=file_url,
            file_hash=self._optional_str(payload.get("file_hash")),
            sort=self._optional_int(payload.get("sort"), "sort", min_value=0) or 0,
            status=1,
            create_user=create_user,
            create_user_id=create_user_id,
            document_id=self._optional_int(payload.get("document_id"), "document_id", min_value=1),
        )

        try:
            created = self.repository.create(model)
        except ValueError as exc:
            raise FolderServiceError(str(exc)) from exc

        self._attach_full_paths([created])
        self._index_nodes([created])
        return created.to_dict()

    def update(
        self,
        data: dict[str, Any],
        node_id: int | None = None,
    ) -> dict[str, Any]:
        """更新节点：按 payload 字段增量更新，目录类型清空文件属性，子树全路径重建并同步 ES。"""
        payload = self._payload(data)
        tenant_id = self._required_int(payload, "tenant_id", min_value=1)
        kb_id = self._required_int(payload, "kb_id", min_value=1)
        target = self._resolve_node(tenant_id=tenant_id, kb_id=kb_id, payload=payload, node_id=node_id)

        updates: dict[str, Any] = {}
        if "node_type" in payload and payload.get("node_type") not in (None, ""):
            updates["node_type"] = self._node_type(payload, default=target.node_type)
        target_node_type = updates.get("node_type", target.node_type)

        path_parts = self._path_parts(payload)
        if path_parts:
            name = self._optional_str(payload.get("name"))
            if name:
                parent_parts = path_parts[:-1] if path_parts[-1] == name else path_parts
                updates["name"] = self._required_name(name)
            else:
                updates["name"] = self._required_name(path_parts[-1])
                parent_parts = path_parts[:-1]
            base_parent_id = self._optional_int(payload.get("parent_id"), "parent_id", min_value=0)
            if base_parent_id is None:
                base_parent_id = 0
            updates["parent_id"] = self._ensure_directory_path(
                tenant_id=tenant_id,
                kb_id=kb_id,
                base_parent_id=base_parent_id,
                parts=parent_parts,
                create_user=self._optional_str(payload.get("create_user")),
                create_user_id=self._optional_int(payload.get("create_user_id"), "create_user_id", min_value=0),
            )
        else:
            if "name" in payload:
                updates["name"] = self._required_name(payload.get("name"))
            if "parent_id" in payload:
                parent_id = self._optional_int(payload.get("parent_id"), "parent_id", min_value=0)
                updates["parent_id"] = parent_id if parent_id is not None else 0

        if "size" in payload:
            updates["size"] = self._optional_int(payload.get("size"), "size", min_value=0) or 0
        if "file_url" in payload or "relative_path" in payload or "file_path" in payload:
            updates["file_url"] = self._file_url(payload, node_type=target_node_type, path_parts=path_parts)
        if "file_hash" in payload:
            updates["file_hash"] = self._optional_str(payload.get("file_hash"))
        if "sort" in payload:
            updates["sort"] = self._optional_int(payload.get("sort"), "sort", min_value=0) or 0
        if "create_user" in payload:
            updates["create_user"] = self._optional_str(payload.get("create_user"))
        if "create_user_id" in payload:
            updates["create_user_id"] = self._optional_int(payload.get("create_user_id"), "create_user_id", min_value=0)
        if "document_id" in payload:
            updates["document_id"] = self._optional_int(payload.get("document_id"), "document_id", min_value=1)

        target_name = updates.get("name", target.name)
        if "extension" in payload or "name" in updates or "node_type" in updates:
            extension_value = payload.get("extension") if "extension" in payload else None
            updates["extension"] = self._extension(
                name=target_name,
                node_type=target_node_type,
                value=extension_value,
                default=None if "name" in updates or "node_type" in updates else target.extension,
            )

        if target_node_type == NODE_TYPE_DIR:
            updates["extension"] = None
            updates["size"] = 0
            updates["file_url"] = None
            updates["file_hash"] = None
            updates["document_id"] = None

        try:
            updated = self.repository.update(tenant_id=tenant_id, kb_id=kb_id, node_id=target.id, updates=updates)
        except ValueError as exc:
            raise FolderServiceError(str(exc)) from exc

        subtree = self.repository.list_subtree(tenant_id=tenant_id, kb_id=kb_id, node_id=updated.id)
        self._attach_full_paths(subtree)
        self._index_nodes(subtree)
        self._attach_full_paths([updated])
        return updated.to_dict()

    def delete(self, data: dict[str, Any], node_id: int | None = None) -> dict[str, Any]:
        """删除节点（默认递归删子树），并按删除的 id 列表清理 ES 索引。"""
        payload = self._payload(data)
        tenant_id = self._required_int(payload, "tenant_id", min_value=1)
        kb_id = self._required_int(payload, "kb_id", min_value=1)
        target = self._resolve_node(tenant_id=tenant_id, kb_id=kb_id, payload=payload, node_id=node_id)
        recursive = self._bool(payload.get("recursive"), default=True)

        try:
            deleted = self.repository.delete_subtree(
                tenant_id=tenant_id,
                kb_id=kb_id,
                node_id=target.id,
                recursive=recursive,
            )
        except ValueError as exc:
            raise FolderServiceError(str(exc)) from exc

        deleted_ids = [item.id for item in deleted if item.id is not None]
        self._delete_es_by_ids(deleted_ids)
        return {
            "id": target.id,
            "tenant_id": tenant_id,
            "kb_id": kb_id,
            "deleted_count": len(deleted_ids),
            "deleted_ids": deleted_ids,
        }

    def detail(self, data: dict[str, Any], node_id: int | None = None) -> dict[str, Any]:
        """查询单个节点详情（含全路径）。"""
        payload = self._payload(data)
        tenant_id = self._required_int(payload, "tenant_id", min_value=1)
        kb_id = self._required_int(payload, "kb_id", min_value=1)
        target = self._resolve_node(tenant_id=tenant_id, kb_id=kb_id, payload=payload, node_id=node_id)
        self._attach_full_paths([target])
        return target.to_dict()

    def query_tree(
        self,
        tenant_id: Any,
        kb_id: Any,
        parent_id: Any = 0,
        keyword: str = "",
        search_source: str = "auto",
        recursive: bool = True,
        include_matched_folder_children: bool = True,
        limit: int = 200,
    ) -> dict[str, Any]:
        """查询文件树：无关键词时按 parent_id 列表建树；有关键词时走 _search_tree 检索。"""
        tenant_id_int = self._to_int(tenant_id, "tenant_id", required=True, min_value=1)
        kb_id_int = self._to_int(kb_id, "kb_id", required=True, min_value=1)
        parent_id_int = self._to_int(parent_id, "parent_id", required=False, min_value=0)
        if parent_id_int is None:
            parent_id_int = 0
        keyword = str(keyword or "").strip()
        source = str(search_source or "auto").strip().lower()
        if source not in {"auto", "es", "mysql"}:
            raise FolderServiceError("search_source 只支持 auto、es 或 mysql。")
        try:
            limit = max(1, min(int(limit or 200), 1000))
        except (TypeError, ValueError) as exc:
            raise FolderServiceError("limit 必须是整数。") from exc

        if keyword:
            return self._search_tree(
                tenant_id=tenant_id_int,
                kb_id=kb_id_int,
                parent_id=parent_id_int,
                keyword=keyword,
                search_source=source,
                include_matched_folder_children=include_matched_folder_children,
                limit=limit,
            )

        rows = self.repository.list_by_parent(
            tenant_id=tenant_id_int,
            kb_id=kb_id_int,
            parent_id=parent_id_int,
            recursive=recursive,
        )
        all_rows = rows if parent_id_int == 0 and recursive else self.repository.list_all(tenant_id_int, kb_id_int)
        self._attach_full_paths(rows, all_rows=all_rows)
        tree = self._build_tree(rows, parent_id=parent_id_int)
        return {
            "tree": tree,
            "meta": {
                "tenant_id": tenant_id_int,
                "kb_id": kb_id_int,
                "parent_id": parent_id_int,
                "keyword": "",
                "search_source": "mysql",
                "matched_count": 0,
                "node_count": len(rows),
            },
        }

    def _search_tree(
        self,
        tenant_id: int,
        kb_id: int,
        parent_id: int,
        keyword: str,
        search_source: str,
        include_matched_folder_children: bool,
        limit: int,
    ) -> dict[str, Any]:
        """关键词检索子树：ES/MySQL 取候选→限定在父作用域→补齐祖先与目录子节点→建树。"""
        all_rows = self.repository.list_all(tenant_id=tenant_id, kb_id=kb_id)
        self._attach_full_paths(all_rows, all_rows=all_rows)
        row_by_id = {item.id: item for item in all_rows if item.id is not None}
        parent = row_by_id.get(parent_id) if parent_id else None
        if parent_id and not parent:
            raise FolderNotFoundError("父目录不存在或已删除。")

        actual_source = search_source
        candidate_ids: list[int] = []
        es_error: Optional[Exception] = None

        if search_source in {"auto", "es"}:
            try:
                candidate_ids = self._search_es_ids(
                    tenant_id=tenant_id,
                    kb_id=kb_id,
                    keyword=keyword,
                    limit=limit,
                )
                actual_source = "es"
            except Exception as exc:
                es_error = exc
                if search_source == "es":
                    raise FolderServiceError(f"ES 搜索失败: {exc}", status_code=500) from exc

        if search_source == "mysql" or (search_source == "auto" and not candidate_ids):
            mysql_ids = self._search_mysql_ids(
                tenant_id=tenant_id,
                kb_id=kb_id,
                rows=all_rows,
                keyword=keyword,
                limit=limit,
            )
            candidate_ids = mysql_ids
            actual_source = "mysql" if es_error is None else "mysql_fallback"

        scoped_candidate_ids = []
        for node_id in candidate_ids:
            row = row_by_id.get(node_id)
            if row and self._in_parent_scope(row=row, parent=parent, parent_id=parent_id):
                scoped_candidate_ids.append(node_id)

        matched_ids = set(scoped_candidate_ids)
        display_ids: set[int] = set()
        for node_id in scoped_candidate_ids:
            row = row_by_id.get(node_id)
            if not row:
                continue
            for ancestor_id in self._path_ids(row.path):
                ancestor = row_by_id.get(ancestor_id)
                if ancestor and self._in_parent_scope(row=ancestor, parent=parent, parent_id=parent_id):
                    display_ids.add(ancestor_id)
            if include_matched_folder_children and row.node_type == NODE_TYPE_DIR:
                for item in all_rows:
                    if item.path.startswith(row.path) and self._in_parent_scope(row=item, parent=parent, parent_id=parent_id):
                        display_ids.add(item.id)

        display_rows = [item for item in all_rows if item.id in display_ids]
        for item in display_rows:
            item.matched = item.id in matched_ids

        tree = self._build_tree(display_rows, parent_id=parent_id)
        return {
            "tree": tree,
            "meta": {
                "tenant_id": tenant_id,
                "kb_id": kb_id,
                "parent_id": parent_id,
                "keyword": keyword,
                "search_source": actual_source,
                "matched_count": len(matched_ids),
                "node_count": len(display_rows),
            },
        }

    def _ensure_directory_path(
        self,
        tenant_id: int,
        kb_id: int,
        base_parent_id: int,
        parts: list[str],
        create_user: Optional[str] = None,
        create_user_id: Optional[int] = None,
    ) -> int:
        """按路径分段逐级确保目录存在（缺失则创建），返回末级目录的 node_id。"""
        parent_id = base_parent_id
        created_dirs: list[FolderModels] = []
        for part in parts:
            name = self._required_name(part)
            existing = self.repository.get_child_by_name(
                tenant_id=tenant_id,
                kb_id=kb_id,
                parent_id=parent_id,
                name=name,
            )
            if existing:
                if existing.node_type != NODE_TYPE_DIR:
                    raise FolderServiceError(f"路径 {name} 已存在且不是目录。")
                parent_id = existing.id
                continue

            model = FolderModels(
                tenant_id=tenant_id,
                kb_id=kb_id,
                parent_id=parent_id,
                node_type=NODE_TYPE_DIR,
                name=name,
                size=0,
                status=1,
                create_user=create_user,
                create_user_id=create_user_id,
            )
            try:
                created = self.repository.create(model)
            except ValueError as exc:
                raise FolderServiceError(str(exc)) from exc
            created_dirs.append(created)
            parent_id = created.id

        if created_dirs:
            self._attach_full_paths(created_dirs)
            self._index_nodes(created_dirs)
        return parent_id

    def _resolve_node(
        self,
        tenant_id: int,
        kb_id: int,
        payload: dict[str, Any],
        node_id: int | None = None,
    ) -> FolderModels:
        """按 id/node_id 或 document_id 定位节点，找不到抛 FolderNotFoundError。"""
        resolved_id = node_id or self._optional_int(payload.get("id") or payload.get("node_id"), "id", min_value=1)
        if resolved_id:
            node = self.repository.get_by_id(tenant_id=tenant_id, kb_id=kb_id, node_id=resolved_id)
        else:
            document_id = self._optional_int(payload.get("document_id"), "document_id", min_value=1)
            if not document_id:
                raise FolderServiceError("缺少 id/node_id 或 document_id。")
            node = self.repository.get_by_document_id(tenant_id=tenant_id, kb_id=kb_id, document_id=document_id)
        if not node:
            raise FolderNotFoundError()
        return node

    def _attach_full_paths(
        self,
        rows: list[FolderModels],
        all_rows: Optional[list[FolderModels]] = None,
    ) -> None:
        """为每行计算 name_pinyin 与 full_path（按 path 中的祖先 id 拼接名称）。"""
        if not rows:
            return
        if all_rows is None:
            all_rows = self.repository.list_all(tenant_id=rows[0].tenant_id, kb_id=rows[0].kb_id)
        names = {item.id: item.name for item in all_rows if item.id is not None}
        for row in rows:
            row.name_pinyin = "".join(lazy_pinyin(row.name or ""))
            path_names = [names[node_id] for node_id in self._path_ids(row.path) if node_id in names]
            row.full_path = "/" + "/".join(path_names) if path_names else f"/{row.name}"

    def _build_tree(self, rows: list[FolderModels], parent_id: int = 0) -> list[dict[str, Any]]:
        """把平铺节点列表组装成父子嵌套树，返回根节点列表。"""
        sorted_rows = self._sort_rows(rows)
        row_ids = {row.id for row in sorted_rows}
        node_map: dict[int, dict[str, Any]] = {}
        for row in sorted_rows:
            if row.id is None:
                continue
            data = row.to_dict(include_children=False)
            data["children"] = []
            node_map[row.id] = data

        roots: list[dict[str, Any]] = []
        for row in sorted_rows:
            if row.id is None or row.id not in node_map:
                continue
            node = node_map[row.id]
            if row.parent_id in node_map:
                node_map[row.parent_id]["children"].append(node)
            elif row.parent_id == parent_id or row.parent_id not in row_ids:
                roots.append(node)
        return roots

    def _search_es_ids(self, tenant_id: int, kb_id: int, keyword: str, limit: int) -> list[int]:
        """在 ES 中按名称/全路径/拼音匹配关键词，返回命中的 node_id 列表。"""
        body = {
            "size": limit,
            "_source": ["id"],
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"tenant_id": tenant_id}},
                        {"term": {"kb_id": kb_id}},
                    ],
                    "should": [
                        {"match": {"name": {"query": keyword, "boost": 3}}},
                        {"match": {"full_path": {"query": keyword, "boost": 2}}},
                        {"match": {"name_pinyin": {"query": keyword, "boost": 1}}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        }
        try:
            resp = self.es.search(index=self.es_index_name, body=body)
        except NotFoundError:
            return []

        ids: list[int] = []
        for hit in resp.get("hits", {}).get("hits", []):
            source = hit.get("_source") or {}
            raw_id = source.get("id") or hit.get("_id")
            try:
                node_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if node_id not in ids:
                ids.append(node_id)
        return ids

    def _search_mysql_ids(
        self,
        tenant_id: int,
        kb_id: int,
        rows: list[FolderModels],
        keyword: str,
        limit: int,
    ) -> list[int]:
        """在 MySQL 中按名称检索（ES 不可用时的兜底），并在内存对全路径做包含匹配。"""
        needle = keyword.lower()
        result: list[int] = []
        for row in self.repository.search_by_name(tenant_id=tenant_id, kb_id=kb_id, keyword=keyword, limit=limit):
            if row.id is not None and row.id not in result:
                result.append(row.id)
            if len(result) >= limit:
                return result
        for row in rows:
            haystacks = [row.name or "", row.full_path or ""]
            if any(needle in item.lower() for item in haystacks):
                if row.id is not None and row.id not in result:
                    result.append(row.id)
            if len(result) >= limit:
                break
        return result

    def _index_nodes(self, rows: list[FolderModels]) -> None:
        """把节点批量写入 ES 文件树索引，失败仅打印日志不抛异常。"""
        actions = []
        for row in rows:
            if row.id is None:
                continue
            row.name_pinyin = "".join(lazy_pinyin(row.name or ""))
            actions.append(
                {
                    "_index": self.es_index_name,
                    "_id": str(row.id),
                    "_source": row.to_es_dict(),
                }
            )
        if not actions:
            return
        try:
            _success, failed = bulk(self.es, actions, raise_on_error=False)
            if failed:
                print("文件树ES写入失败详情", failed)
        except BulkIndexError as exc:
            print("文件树ES写入失败", exc.errors)
        except Exception as exc:
            print(f"文件树ES写入失败: {exc}")

    def _delete_es_by_ids(self, node_ids: Iterable[int]) -> None:
        """按 node_id 批量删除 ES 文件树索引文档，索引不存在或失败均静默处理。"""
        ids = [str(node_id) for node_id in node_ids if node_id is not None]
        if not ids:
            return
        try:
            self.es.delete_by_query(
                index=self.es_index_name,
                body={"query": {"ids": {"values": ids}}},
                refresh=True,
                conflicts="proceed",
            )
        except NotFoundError:
            return
        except Exception as exc:
            print(f"文件树ES删除失败: {exc}")

    def _payload(self, data: FolderModels | dict[str, Any]) -> dict[str, Any]:
        """把入参统一转为 dict（dict 直接复制，dataclass 转 dict）。"""
        if isinstance(data, dict):
            return dict(data)
        if is_dataclass(data):
            return asdict(data)
        return {}

    def _node_type(self, payload: dict[str, Any], default: Optional[int] = None) -> int:
        """解析节点类型：显式 node_type 优先，否则按文件特征（file_url/document_id 等）推断目录或文件。"""
        raw = payload.get("node_type")
        if raw in (None, "") and default is not None:
            raw = default
        if raw in (None, ""):
            file_markers = [
                payload.get("document_id"),
                payload.get("file_url"),
                payload.get("relative_path"),
                payload.get("file_path"),
                payload.get("file_hash"),
                payload.get("extension"),
            ]
            size = self._optional_int(payload.get("size"), "size", min_value=0)
            return NODE_TYPE_FILE if any(self._optional_str(item) for item in file_markers) or (size or 0) > 0 else NODE_TYPE_DIR
        node_type = self._to_int(raw, "node_type", required=True, min_value=1)
        if node_type not in {NODE_TYPE_DIR, NODE_TYPE_FILE}:
            raise FolderServiceError("node_type 只支持 1(目录) 或 2(文件)。")
        return node_type

    def _file_url(self, payload: dict[str, Any], node_type: int, path_parts: list[str]) -> Optional[str]:
        """解析文件 URL：目录返回 None，文件按 file_url/relative_path/file_path/路径段顺序取值。"""
        if node_type == NODE_TYPE_DIR:
            return None
        file_url = (
            self._optional_str(payload.get("file_url"))
            or self._optional_str(payload.get("relative_path"))
            or self._optional_str(payload.get("file_path"))
        )
        if not file_url and path_parts:
            file_url = "/".join(path_parts)
        return file_url

    def _extension(
        self,
        name: str,
        node_type: int,
        value: Any = None,
        default: Optional[str] = None,
    ) -> Optional[str]:
        """解析扩展名：目录返回 None，文件按显式值→默认值→文件名后缀顺序推断，超长抛异常。"""
        if node_type == NODE_TYPE_DIR:
            return None
        extension = self._optional_str(value)
        if extension:
            extension = extension.lstrip(".").lower()
        elif default:
            extension = default.lstrip(".").lower()
        elif "." in name and not name.startswith("."):
            extension = name.rsplit(".", 1)[-1].lower()
        if extension and len(extension) > 20:
            raise FolderServiceError("extension 长度不能超过 20。")
        return extension or None

    def _path_parts(self, payload: dict[str, Any]) -> list[str]:
        """从 full_path/tree_path/folder_path 解析出非空路径分段列表。"""
        raw = (
            payload.get("full_path")
            or payload.get("tree_path")
            or payload.get("folder_path")
        )
        if not raw:
            return []
        path = str(raw).replace("\\", "/").strip()
        return [part.strip() for part in path.strip("/").split("/") if part.strip()]

    def _default_name(self, payload: dict[str, Any]) -> Optional[str]:
        """未显式提供 name 时，从文件名相关字段或路径中取末段作为默认名称。"""
        for key in ("file_name", "filename", "original_filename", "document_file"):
            value = self._optional_str(payload.get(key))
            if value:
                return value.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        for key in ("file_url", "relative_path", "file_path"):
            value = self._optional_str(payload.get(key))
            if value:
                return value.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        return None

    def _in_parent_scope(self, row: FolderModels, parent: Optional[FolderModels], parent_id: int) -> bool:
        """判断节点是否在指定父目录作用域内（根目录恒为真，否则要求 path 以父 path 为前缀）。"""
        if parent_id == 0:
            return True
        if not parent:
            return False
        return row.id != parent_id and row.path.startswith(parent.path)

    def _path_ids(self, path: str) -> list[int]:
        """把 path 字符串（/ 分隔的 id 序列）解析为整数 id 列表。"""
        ids: list[int] = []
        for item in str(path or "").strip("/").split("/"):
            if not item:
                continue
            try:
                ids.append(int(item))
            except ValueError:
                continue
        return ids

    def _sort_rows(self, rows: list[FolderModels]) -> list[FolderModels]:
        """按层级、排序值、节点类型、名称、id 排序，保证建树前顺序稳定。"""
        return sorted(
            rows,
            key=lambda item: (
                item.level or 0,
                item.sort or 0,
                item.node_type or 0,
                item.name or "",
                item.id or 0,
            ),
        )

    def _required_int(self, payload: dict[str, Any], field: str, min_value: int = 0) -> int:
        """取必填整数字段，缺失或非法抛 FolderServiceError。"""
        return self._to_int(payload.get(field), field, required=True, min_value=min_value)

    def _optional_int(self, value: Any, field: str, min_value: int = 0) -> Optional[int]:
        """取可选整数字段，缺失返回 None，非法或越界抛异常。"""
        return self._to_int(value, field, required=False, min_value=min_value)

    def _to_int(self, value: Any, field: str, required: bool, min_value: int = 0) -> Optional[int]:
        """整数值规整核心：空值按 required 决定抛异常或返回 None，否则转 int 并校验下限。"""
        if value in (None, ""):
            if required:
                raise FolderServiceError(f"缺少 {field}。")
            return None
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise FolderServiceError(f"{field} 必须是整数。") from exc
        if number < min_value:
            raise FolderServiceError(f"{field} 不能小于 {min_value}。")
        return number

    def _required_name(self, value: Any) -> str:
        """校验节点名称：非空且不含路径分隔符，否则抛异常。"""
        name = self._optional_str(value)
        if not name:
            raise FolderServiceError("缺少 name。")
        if "/" in name or "\\" in name:
            raise FolderServiceError("name 不能包含路径分隔符，请使用 full_path 传完整层级。")
        return name

    @staticmethod
    def _optional_str(value: Any) -> Optional[str]:
        """把值规整为去空白字符串，空串返回 None。"""
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @staticmethod
    def _bool(value: Any, default: bool = False) -> bool:
        """宽容地把多种字面量解析为布尔，无法识别用默认值。"""
        if value in (None, ""):
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
