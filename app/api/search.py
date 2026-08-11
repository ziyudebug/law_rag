"""
检索接口模块。

POST /api/search：根据 query、tenant_id、kb_id 进行混合检索，支持按文档/文件夹限定范围。

@author: ziyu
@date: 2026-07-27
"""
from flask import Blueprint, current_app, jsonify, request


bp = Blueprint("search", __name__, url_prefix="/api")


@bp.post("/search")
def api_search():
    """混合检索接口：解析检索范围后调用检索服务返回命中分段。"""
    data = request.json or {}
    query = data.get("query")
    tenant_id = data.get("tenant_id")
    kb_id = data.get("kb_id")
    if not query:
        return jsonify({"success": False, "error": "缺少 query。"}), 400
    if not tenant_id:
        return jsonify({"success": False, "error": "缺少 tenant_id。"}), 400
    if not kb_id:
        return jsonify({"success": False, "error": "缺少 kb_id。"}), 400

    service = current_app.extensions["retrieval_service"]
    scope_resolver = current_app.extensions["retrieval_scope_resolver"]
    try:
        # 解析检索范围（文档/文件夹/节点约束），转为 document_id 过滤条件
        scope = scope_resolver.resolve(tenant_id=tenant_id, kb_id=kb_id, payload=data)
        if scope.limited and not scope.document_ids:
            return jsonify({"success": True, "data": [], "meta": {"scope": scope.to_dict()}})

        result = service.retrieve(
            query=query,
            tenant_id=tenant_id,
            kb_id=kb_id,
            document_id=scope.document_filter(),
            top_k=data.get("top_k"),
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
    return jsonify({"success": True, "data": result, "meta": {"scope": scope.to_dict()}})
