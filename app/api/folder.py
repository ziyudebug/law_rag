"""
文件树接口模块。

提供文件夹/文件节点的增删改查与树形查询接口，均需 token 鉴权。
支持按 parent_id 取子树、按关键字检索（ES/MySQL 双源）、递归列表等。

@author: ziyu
@date: 2026-07-28
"""
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from app.core.auth import require_token
from app.services.folder_service import FolderServiceError


bp = Blueprint("folder", __name__, url_prefix="/api")


@bp.post("/folder_create")
@require_token
def folder_create():
    """创建文件树节点（目录或文件），支持通过 full_path 一次性创建多层目录。"""
    service = current_app.extensions["folder_service"]
    try:
        result = service.create(_json_payload())
    except Exception as exc:
        return _error_response(exc)
    return jsonify({"success": True, "data": result})


@bp.route("/folder_list", methods=["GET", "POST"])
@bp.route("/folder_tree", methods=["GET", "POST"])
@require_token
def folder_tree():
    """查询文件树：按 parent_id 取子树，可带关键字做检索，返回树形结构与元信息。"""
    service = current_app.extensions["folder_service"]
    payload = _json_payload() if request.method == "POST" else _args_payload()
    try:
        result = service.query_tree(
            tenant_id=payload.get("tenant_id"),
            kb_id=payload.get("kb_id"),
            parent_id=payload.get("parent_id", 0),
            keyword=payload.get("keyword") or payload.get("name") or payload.get("query") or "",
            search_source=payload.get("search_source") or payload.get("search_type") or "auto",
            recursive=_bool_value(payload.get("recursive"), True),
            include_matched_folder_children=_bool_value(payload.get("include_matched_folder_children"), True),
            limit=_int_value(payload.get("limit"), 200),
        )
    except Exception as exc:
        return _error_response(exc)
    return jsonify({"success": True, "data": result["tree"], "meta": result["meta"]})


@bp.route("/folder_list_recursive", methods=["GET", "POST"])
@bp.route("/kb/tree/listRecursive", methods=["GET", "POST"])
@require_token
def folder_list_recursive():
    """递归列出文件树（兼容旧路径 /kb/tree/listRecursive），默认走 MySQL 全量。"""
    service = current_app.extensions["folder_service"]
    payload = _json_payload() if request.method == "POST" else _args_payload()
    parent_id = payload.get("parent_id") or payload.get("parentId") or payload.get("id") or 0
    tenant_id = payload.get("tenant_id") or payload.get("tenantId") or payload.get("id") or 0
    try:
        result = service.query_tree(
            tenant_id=tenant_id,
            kb_id=payload.get("kb_id") or payload.get("kbId"),
            parent_id=parent_id,
            keyword="",
            search_source="mysql",
            recursive=True,
            include_matched_folder_children=False,
            limit=_int_value(payload.get("limit"), 1000),
        )
    except Exception as exc:
        return _error_response(exc)
    return jsonify({"success": True, "data": result["tree"], "meta": result["meta"]})


@bp.route("/folder_detail", methods=["GET", "POST"])
@require_token
def folder_detail():
    """查询单个文件树节点详情（按 body 中的 id/document_id 定位）。"""
    service = current_app.extensions["folder_service"]
    payload = _json_payload() if request.method == "POST" else _args_payload()
    try:
        result = service.detail(payload)
    except Exception as exc:
        return _error_response(exc)
    return jsonify({"success": True, "data": result})


@bp.get("/folder/<int:node_id>")
@require_token
def folder_detail_by_id(node_id: int):
    """按路径中的 node_id 查询单个文件树节点详情。"""
    service = current_app.extensions["folder_service"]
    try:
        result = service.detail(_args_payload(), node_id=node_id)
    except Exception as exc:
        return _error_response(exc)
    return jsonify({"success": True, "data": result})


@bp.post("/folder_update")
@require_token
def folder_update():
    """更新文件树节点（按 body 中的 id/document_id 定位）。"""
    service = current_app.extensions["folder_service"]
    try:
        result = service.update(_json_payload())
    except Exception as exc:
        return _error_response(exc)
    return jsonify({"success": True, "data": result})


@bp.put("/folder/<int:node_id>")
@require_token
def folder_update_by_id(node_id: int):
    """按路径中的 node_id 更新文件树节点。"""
    service = current_app.extensions["folder_service"]
    try:
        result = service.update(_json_payload(), node_id=node_id)
    except Exception as exc:
        return _error_response(exc)
    return jsonify({"success": True, "data": result})


@bp.post("/folder_delete")
@require_token
def folder_delete():
    """删除文件树节点（按 body 中的 id/document_id 定位，支持递归）。"""
    service = current_app.extensions["folder_service"]
    try:
        result = service.delete(_json_payload())
    except Exception as exc:
        return _error_response(exc)
    return jsonify({"success": True, "data": result})


@bp.delete("/folder/<int:node_id>")
@require_token
def folder_delete_by_id(node_id: int):
    """按路径中的 node_id 删除文件树节点（支持递归）。"""
    service = current_app.extensions["folder_service"]
    try:
        payload = _args_payload()
        if request.is_json:
            payload.update(_json_payload())
        result = service.delete(payload, node_id=node_id)
    except Exception as exc:
        return _error_response(exc)
    return jsonify({"success": True, "data": result})


def _json_payload() -> dict[str, Any]:
    """安全读取 JSON body，非法或空时返回空 dict。"""
    return request.get_json(silent=True) or {}


def _args_payload() -> dict[str, Any]:
    """把 query string 转为 dict。"""
    return {key: value for key, value in request.args.items()}


def _bool_value(value: Any, default: bool) -> bool:
    """把多种形态的值解析为布尔，空值用默认值。"""
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_value(value: Any, default: int) -> int:
    """把多种形态的值解析为整数，失败用默认值。"""
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _error_response(exc: Exception):
    """把异常转为统一错误响应：FolderServiceError 用其自带状态码，其余 500。"""
    if isinstance(exc, FolderServiceError):
        return jsonify({"success": False, "error": str(exc)}), exc.status_code
    return jsonify({"success": False, "error": str(exc)}), 500
