"""
文档上传接口模块。

POST /api/upload：接收文件与文档详情，异步入库（解析→分段→向量化→双写索引），即时返回事件 ID。
需通过 token 鉴权。

@author: ziyu
@date: 2026-07-13
"""
from flask import Blueprint, current_app, jsonify, request

from app.core.auth import require_token
from app.services.upload_service import UploadRequestError


bp = Blueprint("upload", __name__, url_prefix="/api")


@bp.post("/upload")
@require_token
def api_upload():
    """文档上传接口：校验 token 后提交给上传服务异步入库，返回事件 ID 与文档 ID。"""
    upload_service = current_app.extensions["upload_service"]
    try:
        accepted = upload_service.submit(
            files=request.files.getlist("files"),
            form=request.form,
        )
    except UploadRequestError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500

    return jsonify(
        {
            "success": True,
            "async": True,
            "message": "文件已接收，后台开始解析、分段、入库和索引。",
            "data": accepted,
        }
    )
