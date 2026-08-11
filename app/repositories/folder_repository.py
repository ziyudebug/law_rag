"""
文件树仓储：对 kb_file_tree 表的 CRUD 与路径维护。

节点 path 字段形如 /1/3/7/，存的是祖先 id 序列；移动节点时连同子树 path/level 一起调整。
删除为软删（status=0），保留树结构可追溯。

@author: ziyu
@date: 2026-07-27
"""
from typing import Any, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.database import db
from app.services.folder_models import FolderModels, NODE_TYPE_DIR, NODE_TYPE_FILE


class FolderRepository:
    """文件树节点的 MySQL 持久化仓储。"""

    def get_by_id(
        self,
        tenant_id: int,
        kb_id: int,
        node_id: int,
        include_deleted: bool = False,
    ) -> Optional[FolderModels]:
        """按 id 查节点，默认只查有效（status=1）。"""
        with db.SessionLocal() as session:
            return self._get_by_id(
                session=session,
                tenant_id=tenant_id,
                kb_id=kb_id,
                node_id=node_id,
                include_deleted=include_deleted,
            )

    def get_by_document_id(
        self,
        tenant_id: int,
        kb_id: int,
        document_id: int,
        include_deleted: bool = False,
    ) -> Optional[FolderModels]:
        """按 document_id 查文件节点，默认只查有效。"""
        sql = """
            SELECT *
            FROM kb_file_tree
            WHERE tenant_id = :tenant_id
              AND kb_id = :kb_id
              AND document_id = :document_id
        """
        if not include_deleted:
            sql += " AND status = 1"
        sql += " ORDER BY id DESC LIMIT 1"

        with db.SessionLocal() as session:
            row = session.execute(
                text(sql),
                {"tenant_id": tenant_id, "kb_id": kb_id, "document_id": document_id},
            ).fetchone()
            return self._row_to_model(row)

    def get_child_by_name(
        self,
        tenant_id: int,
        kb_id: int,
        parent_id: int,
        name: str,
        include_deleted: bool = False,
    ) -> Optional[FolderModels]:
        """按 parent_id + name 查同级子节点，默认只查有效。"""
        with db.SessionLocal() as session:
            return self._get_child_by_name(
                session=session,
                tenant_id=tenant_id,
                kb_id=kb_id,
                parent_id=parent_id,
                name=name,
                include_deleted=include_deleted,
            )

    def list_all(self, tenant_id: int, kb_id: int, include_deleted: bool = False) -> list[FolderModels]:
        """列出知识库下全部节点，默认只列有效节点。"""
        sql = """
            SELECT *
            FROM kb_file_tree
            WHERE tenant_id = :tenant_id AND kb_id = :kb_id
        """
        if not include_deleted:
            sql += " AND status = 1"
        sql += " ORDER BY level ASC, sort ASC, node_type ASC, name ASC, id ASC"

        with db.SessionLocal() as session:
            rows = session.execute(text(sql), {"tenant_id": tenant_id, "kb_id": kb_id}).fetchall()
            return [FolderModels.from_mapping(row) for row in rows]

    def list_children(self, tenant_id: int, kb_id: int, parent_id: int) -> list[FolderModels]:
        """列出指定父目录下的直接子节点。"""
        with db.SessionLocal() as session:
            rows = session.execute(
                text(
                    """
                    SELECT *
                    FROM kb_file_tree
                    WHERE tenant_id = :tenant_id
                      AND kb_id = :kb_id
                      AND parent_id = :parent_id
                      AND status = 1
                    ORDER BY sort ASC, node_type ASC, name ASC, id ASC
                    """
                ),
                {"tenant_id": tenant_id, "kb_id": kb_id, "parent_id": parent_id},
            ).fetchall()
            return [FolderModels.from_mapping(row) for row in rows]

    def list_by_parent(
        self,
        tenant_id: int,
        kb_id: int,
        parent_id: int = 0,
        recursive: bool = True,
    ) -> list[FolderModels]:
        """按 parent 列出节点：非递归列直接子节点，递归则按 path 前缀取整棵子树。"""
        if not recursive:
            return self.list_children(tenant_id=tenant_id, kb_id=kb_id, parent_id=parent_id)

        if parent_id == 0:
            return self.list_all(tenant_id=tenant_id, kb_id=kb_id)

        parent = self.get_by_id(tenant_id=tenant_id, kb_id=kb_id, node_id=parent_id)
        if not parent:
            return []

        with db.SessionLocal() as session:
            rows = session.execute(
                text(
                    """
                    SELECT *
                    FROM kb_file_tree
                    WHERE tenant_id = :tenant_id
                      AND kb_id = :kb_id
                      AND status = 1
                      AND path LIKE :path_like
                      AND id <> :parent_id
                    ORDER BY level ASC, sort ASC, node_type ASC, name ASC, id ASC
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "kb_id": kb_id,
                    "path_like": f"{parent.path}%",
                    "parent_id": parent_id,
                },
            ).fetchall()
            return [FolderModels.from_mapping(row) for row in rows]

    def list_subtree(
        self,
        tenant_id: int,
        kb_id: int,
        node_id: int,
        include_root: bool = True,
    ) -> list[FolderModels]:
        """按节点 path 前缀列出整棵子树，可选是否包含根节点本身。"""
        parent = self.get_by_id(tenant_id=tenant_id, kb_id=kb_id, node_id=node_id)
        if not parent:
            return []

        sql = """
            SELECT *
            FROM kb_file_tree
            WHERE tenant_id = :tenant_id
              AND kb_id = :kb_id
              AND status = 1
              AND path LIKE :path_like
        """
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "kb_id": kb_id,
            "path_like": f"{parent.path}%",
        }
        if not include_root:
            sql += " AND id <> :node_id"
            params["node_id"] = node_id
        sql += " ORDER BY level ASC, sort ASC, node_type ASC, name ASC, id ASC"

        with db.SessionLocal() as session:
            rows = session.execute(text(sql), params).fetchall()
            return [FolderModels.from_mapping(row) for row in rows]

    def list_by_ids(
        self,
        tenant_id: int,
        kb_id: int,
        node_ids: Iterable[int],
        include_deleted: bool = False,
    ) -> list[FolderModels]:
        """按 id 列表批量查节点，保持入参顺序，默认只查有效节点。"""
        ids = [int(node_id) for node_id in node_ids if node_id is not None]
        if not ids:
            return []

        placeholders = ", ".join(f":id_{index}" for index in range(len(ids)))
        params: dict[str, Any] = {"tenant_id": tenant_id, "kb_id": kb_id}
        params.update({f"id_{index}": node_id for index, node_id in enumerate(ids)})

        sql = f"""
            SELECT *
            FROM kb_file_tree
            WHERE tenant_id = :tenant_id
              AND kb_id = :kb_id
              AND id IN ({placeholders})
        """
        if not include_deleted:
            sql += " AND status = 1"

        with db.SessionLocal() as session:
            rows = session.execute(text(sql), params).fetchall()
            by_id = {item.id: item for item in (FolderModels.from_mapping(row) for row in rows)}
            return [by_id[node_id] for node_id in ids if node_id in by_id]

    def resolve_document_ids_by_node_ids(
        self,
        tenant_id: int,
        kb_id: int,
        node_ids: Iterable[int],
    ) -> list[str]:
        """把文件树节点ID解析为业务文档ID。

        文件节点取自身 document_id；目录节点递归取目录下所有文件节点的 document_id。
        """
        result: list[str] = []
        seen: set[str] = set()
        for node in self.list_by_ids(tenant_id=tenant_id, kb_id=kb_id, node_ids=node_ids):
            if node.node_type == NODE_TYPE_FILE:
                self._append_document_id(result, seen, node.document_id)
                continue
            if node.node_type == NODE_TYPE_DIR and node.id is not None:
                for child in self.list_subtree(
                    tenant_id=tenant_id,
                    kb_id=kb_id,
                    node_id=node.id,
                    include_root=False,
                ):
                    if child.node_type == NODE_TYPE_FILE:
                        self._append_document_id(result, seen, child.document_id)
        return result

    def search_by_name(self, tenant_id: int, kb_id: int, keyword: str, limit: int = 200) -> list[FolderModels]:
        """按名称模糊匹配检索节点（MySQL LIKE）。"""
        keyword = keyword.strip()
        if not keyword:
            return []

        with db.SessionLocal() as session:
            rows = session.execute(
                text(
                    """
                    SELECT *
                    FROM kb_file_tree
                    WHERE tenant_id = :tenant_id
                      AND kb_id = :kb_id
                      AND status = 1
                      AND name LIKE :keyword
                    ORDER BY level ASC, sort ASC, node_type ASC, name ASC, id ASC
                    LIMIT :limit
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "kb_id": kb_id,
                    "keyword": f"%{keyword}%",
                    "limit": max(1, int(limit)),
                },
            ).fetchall()
            return [FolderModels.from_mapping(row) for row in rows]

    def create(self, data: FolderModels) -> FolderModels:
        """创建节点：校验父目录与同级唯一性→插入→回填 path 与 level。"""
        with db.SessionLocal() as session:
            with session.begin():
                parent = self._validate_parent(session, data.tenant_id, data.kb_id, data.parent_id)
                self._ensure_unique_name(
                    session=session,
                    tenant_id=data.tenant_id,
                    kb_id=data.kb_id,
                    parent_id=data.parent_id,
                    name=data.name,
                )

                level = (parent.level + 1) if parent else 0
                sort = data.sort if data.sort is not None else self._next_sort(session, data.tenant_id, data.kb_id, data.parent_id)
                status = data.status if data.status is not None else 1

                result = session.execute(
                    text(
                        """
                        INSERT INTO kb_file_tree
                        (tenant_id, kb_id, parent_id, node_type, name, extension, size, path, level,
                         file_url, file_hash, sort, status, create_user, create_user_id, document_id)
                        VALUES
                        (:tenant_id, :kb_id, :parent_id, :node_type, :name, :extension, :size, '/',
                         :level, :file_url, :file_hash, :sort, :status, :create_user, :create_user_id,
                         :document_id)
                        """
                    ),
                    {
                        "tenant_id": data.tenant_id,
                        "kb_id": data.kb_id,
                        "parent_id": data.parent_id,
                        "node_type": data.node_type,
                        "name": data.name,
                        "extension": data.extension,
                        "size": data.size or 0,
                        "level": level,
                        "file_url": data.file_url,
                        "file_hash": data.file_hash,
                        "sort": sort,
                        "status": status,
                        "create_user": data.create_user,
                        "create_user_id": data.create_user_id,
                        "document_id": data.document_id,
                    },
                )
                node_id = self._lastrowid(session, result)
                parent_path = parent.path if parent else "/"
                node_path = f"{parent_path}{node_id}/"
                session.execute(
                    text(
                        """
                        UPDATE kb_file_tree
                        SET path = :path, level = :level, sort = :sort
                        WHERE id = :node_id
                        """
                    ),
                    {"path": node_path, "level": level, "sort": sort, "node_id": node_id},
                )
                created = self._get_by_id(session, data.tenant_id, data.kb_id, node_id)
                if not created:
                    raise ValueError("文件树节点创建失败。")
                return created

    def update(self, tenant_id: int, kb_id: int, node_id: int, updates: dict[str, Any]) -> FolderModels:
        """更新节点字段，移动父目录或改名时同步调整子树 path 与 level。"""
        with db.SessionLocal() as session:
            with session.begin():
                current = self._get_by_id(
                    session=session,
                    tenant_id=tenant_id,
                    kb_id=kb_id,
                    node_id=node_id,
                    for_update=True,
                )
                if not current:
                    raise ValueError("文件树节点不存在或已删除。")

                target_parent_id = updates.get("parent_id", current.parent_id)
                parent = self._validate_parent(session, tenant_id, kb_id, target_parent_id, current=current)
                target_name = updates.get("name", current.name)
                if target_parent_id != current.parent_id or target_name != current.name:
                    self._ensure_unique_name(
                        session=session,
                        tenant_id=tenant_id,
                        kb_id=kb_id,
                        parent_id=target_parent_id,
                        name=target_name,
                        exclude_id=node_id,
                    )

                old_path = current.path
                old_level = current.level
                new_level = (parent.level + 1) if parent else 0
                parent_path = parent.path if parent else "/"
                new_path = f"{parent_path}{node_id}/"

                values = {
                    "tenant_id": tenant_id,
                    "kb_id": kb_id,
                    "node_id": node_id,
                    "parent_id": target_parent_id,
                    "node_type": updates.get("node_type", current.node_type),
                    "name": target_name,
                    "extension": updates.get("extension", current.extension),
                    "size": updates.get("size", current.size),
                    "path": new_path,
                    "level": new_level,
                    "file_url": updates.get("file_url", current.file_url),
                    "file_hash": updates.get("file_hash", current.file_hash),
                    "sort": updates.get("sort", current.sort),
                    "create_user": updates.get("create_user", current.create_user),
                    "create_user_id": updates.get("create_user_id", current.create_user_id),
                    "document_id": updates.get("document_id", current.document_id),
                }
                session.execute(
                    text(
                        """
                        UPDATE kb_file_tree
                        SET parent_id = :parent_id,
                            node_type = :node_type,
                            name = :name,
                            extension = :extension,
                            size = :size,
                            path = :path,
                            level = :level,
                            file_url = :file_url,
                            file_hash = :file_hash,
                            sort = :sort,
                            create_user = :create_user,
                            create_user_id = :create_user_id,
                            document_id = :document_id
                        WHERE tenant_id = :tenant_id
                          AND kb_id = :kb_id
                          AND id = :node_id
                          AND status = 1
                        """
                    ),
                    values,
                )

                if old_path != new_path:
                    session.execute(
                        text(
                            """
                            UPDATE kb_file_tree
                            SET path = CONCAT(:new_path, SUBSTRING(path, :substring_start)),
                                level = level + :level_delta
                            WHERE tenant_id = :tenant_id
                              AND kb_id = :kb_id
                              AND status = 1
                              AND id <> :node_id
                              AND path LIKE :old_path_like
                            """
                        ),
                        {
                            "tenant_id": tenant_id,
                            "kb_id": kb_id,
                            "node_id": node_id,
                            "new_path": new_path,
                            "substring_start": len(old_path) + 1,
                            "level_delta": new_level - old_level,
                            "old_path_like": f"{old_path}%",
                        },
                    )

                updated = self._get_by_id(session, tenant_id, kb_id, node_id)
                if not updated:
                    raise ValueError("文件树节点更新失败。")
                return updated

    def delete_subtree(
        self,
        tenant_id: int,
        kb_id: int,
        node_id: int,
        recursive: bool = True,
    ) -> list[FolderModels]:
        """软删子树：非递归需无子节点，递归则把整棵子树 status 置 0，返回被删节点列表。"""
        with db.SessionLocal() as session:
            with session.begin():
                current = self._get_by_id(
                    session=session,
                    tenant_id=tenant_id,
                    kb_id=kb_id,
                    node_id=node_id,
                    for_update=True,
                )
                if not current:
                    raise ValueError("文件树节点不存在或已删除。")
                if not recursive and self._has_active_children(session, tenant_id, kb_id, node_id):
                    raise ValueError("目录下存在子节点，请使用 recursive=true 删除。")

                rows = self._list_subtree_by_path(session, tenant_id, kb_id, current.path)
                session.execute(
                    text(
                        """
                        UPDATE kb_file_tree
                        SET status = 0
                        WHERE tenant_id = :tenant_id
                          AND kb_id = :kb_id
                          AND status = 1
                          AND path LIKE :path_like
                        """
                    ),
                    {"tenant_id": tenant_id, "kb_id": kb_id, "path_like": f"{current.path}%"},
                )
                return rows

    def _get_by_id(
        self,
        session: Session,
        tenant_id: int,
        kb_id: int,
        node_id: int,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Optional[FolderModels]:
        """按 id 查单节点的内部实现，可带行锁（FOR UPDATE）与是否含已删。"""
        sql = """
            SELECT *
            FROM kb_file_tree
            WHERE tenant_id = :tenant_id
              AND kb_id = :kb_id
              AND id = :node_id
        """
        if not include_deleted:
            sql += " AND status = 1"
        if for_update:
            sql += " FOR UPDATE"

        row = session.execute(
            text(sql),
            {"tenant_id": tenant_id, "kb_id": kb_id, "node_id": node_id},
        ).fetchone()
        return self._row_to_model(row)

    def _get_child_by_name(
        self,
        session: Session,
        tenant_id: int,
        kb_id: int,
        parent_id: int,
        name: str,
        include_deleted: bool = False,
    ) -> Optional[FolderModels]:
        """按 parent_id + name 查同级子节点的内部实现。"""
        sql = """
            SELECT *
            FROM kb_file_tree
            WHERE tenant_id = :tenant_id
              AND kb_id = :kb_id
              AND parent_id = :parent_id
              AND name = :name
        """
        if not include_deleted:
            sql += " AND status = 1"
        sql += " ORDER BY id ASC LIMIT 1"

        row = session.execute(
            text(sql),
            {"tenant_id": tenant_id, "kb_id": kb_id, "parent_id": parent_id, "name": name},
        ).fetchone()
        return self._row_to_model(row)

    def _validate_parent(
        self,
        session: Session,
        tenant_id: int,
        kb_id: int,
        parent_id: int,
        current: Optional[FolderModels] = None,
    ) -> Optional[FolderModels]:
        """校验父目录有效性：存在、是目录、不能移到自身或子目录下。"""
        if parent_id == 0:
            return None

        parent = self._get_by_id(
            session=session,
            tenant_id=tenant_id,
            kb_id=kb_id,
            node_id=parent_id,
            for_update=True,
        )
        if not parent:
            raise ValueError("父目录不存在或已删除。")
        if parent.node_type != NODE_TYPE_DIR:
            raise ValueError("父节点必须是目录。")
        if current and parent.id == current.id:
            raise ValueError("不能将节点移动到自己下面。")
        if current and parent.path.startswith(current.path):
            raise ValueError("不能将目录移动到自己的子目录下面。")
        return parent

    def _ensure_unique_name(
        self,
        session: Session,
        tenant_id: int,
        kb_id: int,
        parent_id: int,
        name: str,
        exclude_id: Optional[int] = None,
    ) -> None:
        """校验同级下无同名节点（更新时排除自身 id）。"""
        duplicate = self._get_child_by_name(
            session=session,
            tenant_id=tenant_id,
            kb_id=kb_id,
            parent_id=parent_id,
            name=name,
        )
        if duplicate and duplicate.id != exclude_id:
            raise ValueError("同级目录下已存在同名节点。")

    def _next_sort(self, session: Session, tenant_id: int, kb_id: int, parent_id: int) -> int:
        """取同级下最大 sort+1，作为新节点默认排序值。"""
        value = session.execute(
            text(
                """
                SELECT COALESCE(MAX(sort), 0) + 1
                FROM kb_file_tree
                WHERE tenant_id = :tenant_id
                  AND kb_id = :kb_id
                  AND parent_id = :parent_id
                  AND status = 1
                """
            ),
            {"tenant_id": tenant_id, "kb_id": kb_id, "parent_id": parent_id},
        ).scalar_one()
        return int(value or 1)

    def _has_active_children(self, session: Session, tenant_id: int, kb_id: int, node_id: int) -> bool:
        """判断节点是否存在有效子节点（用于非递归删除前校验）。"""
        value = session.execute(
            text(
                """
                SELECT COUNT(1)
                FROM kb_file_tree
                WHERE tenant_id = :tenant_id
                  AND kb_id = :kb_id
                  AND parent_id = :node_id
                  AND status = 1
                """
            ),
            {"tenant_id": tenant_id, "kb_id": kb_id, "node_id": node_id},
        ).scalar_one()
        return int(value or 0) > 0

    def _list_subtree_by_path(self, session: Session, tenant_id: int, kb_id: int, path: str) -> list[FolderModels]:
        """按 path 前缀查出子树全部有效节点（删除前快照）。"""
        rows = session.execute(
            text(
                """
                SELECT *
                FROM kb_file_tree
                WHERE tenant_id = :tenant_id
                  AND kb_id = :kb_id
                  AND status = 1
                  AND path LIKE :path_like
                ORDER BY level ASC, sort ASC, node_type ASC, name ASC, id ASC
                """
            ),
            {"tenant_id": tenant_id, "kb_id": kb_id, "path_like": f"{path}%"},
        ).fetchall()
        return [FolderModels.from_mapping(row) for row in rows]

    def _lastrowid(self, session: Session, result: CursorResult) -> int:
        """获取上一条 INSERT 的自增主键：优先取 lastrowid，否则查 LAST_INSERT_ID()。"""
        lastrowid = getattr(result, "lastrowid", None)
        if lastrowid:
            return int(lastrowid)
        return int(session.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())

    @staticmethod
    def _row_to_model(row: Any) -> Optional[FolderModels]:
        """把单行 SQL 结果映射为 FolderModels，None 原样返回。"""
        if row is None:
            return None
        return FolderModels.from_mapping(row)

    @staticmethod
    def _append_document_id(result: list[str], seen: set[str], value: Any) -> None:
        """把 document_id 规整后去重追加到结果列表。"""
        document_id = str(value or "").strip()
        if document_id and document_id not in seen:
            seen.add(document_id)
            result.append(document_id)
