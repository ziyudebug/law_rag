"""
检索配置接口模块。

GET/PUT /api/retrieval-config：按 tenant_id × kb_id 读取或保存检索参数
（检索模式、是否 rerank、权重、top_k、阈值等），需登录 session。

@author: ziyu
@date: 2026-07-14
"""
from flask import Blueprint, current_app, jsonify, request, session

from app.services.retrieval_config_models import RetrievalConfig


bp = Blueprint("retrieval_config", __name__, url_prefix="/api")


@bp.get("/retrieval-config")
def get_retrieval_config():
    """读取检索配置：有则返回库中配置，无则返回默认配置。"""
    if not session.get("logged_in"):
        return jsonify({"success": False, "error": "未登录。"}), 401

    tenant_id = str(request.args.get("tenant_id") or "").strip()
    kb_id = str(request.args.get("kb_id") or "").strip()
    if not tenant_id or not kb_id:
        return jsonify({"success": False, "error": "缺少 tenant_id 或 kb_id。"}), 400

    repository = current_app.extensions["retrieval_config_repository"]
    config = repository.get_or_default(tenant_id=tenant_id, kb_id=kb_id)
    return jsonify({"success": True, "data": config.to_dict()})


@bp.put("/retrieval-config")
def save_retrieval_config():
    """保存检索配置：按 payload 构造配置并规范化后 upsert 入库。"""
    if not session.get("logged_in"):
        return jsonify({"success": False, "error": "未登录。"}), 401

    payload = request.json or {}
    try:
        config = RetrievalConfig.from_payload(payload)
        repository = current_app.extensions["retrieval_config_repository"]
        saved = repository.save(config)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500

    return jsonify({"success": True, "data": saved.to_dict()})
