"""
PDF 解析接口模块。

提供一次性返回和流式（NDJSON）两种 PDF 结构化抽取接口，均需 token 鉴权。
抽取流程：PDF 文本/OCR 提取 → 通义千问按 prompt 抽取结构化 JSON。

@author: ziyu
@date: 2026-07-13
"""
import json
import shutil
import tempfile
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, stream_with_context

from app.core.auth import require_token


bp = Blueprint("pdf", __name__, url_prefix="/api")


def _build_json_line(payload: dict) -> str:
    """将 dict 序列化为 NDJSON 单行（用于流式接口的逐行输出）。"""
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _save_upload_to_temp(uploaded_file) -> tuple[Path, Path]:
    """把上传的 PDF 落到临时目录，返回 (临时目录, 临时文件路径)。"""
    temp_dir = Path(tempfile.mkdtemp())
    temp_path = temp_dir / "upload.pdf"
    uploaded_file.save(temp_path)
    return temp_dir, temp_path


@bp.post("/parse-pdf")
@require_token
def parse_pdf():
    """一次性 PDF 结构化抽取接口：抽取完成后整体返回结构化 JSON 与元数据。"""
    prompt = (request.form.get("prompt") or "").strip().lower()
    uploaded_file = request.files.get("pdf")
    pdf_type = (request.form.get("pdf_type") or "").strip().lower()
    original_filename = (uploaded_file.filename or "").strip() if uploaded_file else ""

    if uploaded_file is None or not original_filename:
        return jsonify({"success": False, "error": "请先上传 PDF 文件。"}), 400

    if pdf_type not in {"image", "text"}:
        return jsonify({"success": False, "error": "pdf_type 只支持 image 或 text。"}), 400

    temp_dir = None
    try:
        from app.services.pdf_pipeline import process_pdf

        temp_dir, temp_path = _save_upload_to_temp(uploaded_file)
        data, metadata = process_pdf(temp_path, pdf_type, original_filename, prompt)
        return jsonify({"success": True, "metadata": metadata, "data": data})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


@bp.post("/parse-pdf-stream")
@require_token
def parse_pdf_stream():
    """流式 PDF 结构化抽取接口：以 NDJSON 逐行推送状态/内容块/最终结果，前端可边生成边显示。"""
    uploaded_file = request.files.get("pdf")
    pdf_type = (request.form.get("pdf_type") or "").strip().lower()
    prompt = (request.form.get("prompt") or "").strip().lower()
    original_filename = (uploaded_file.filename or "").strip() if uploaded_file else ""

    if uploaded_file is None or not original_filename:
        return jsonify({"success": False, "error": "请先上传 PDF 文件。"}), 400

    if pdf_type not in {"image", "text"}:
        return jsonify({"success": False, "error": "pdf_type 只支持 image 或 text。"}), 400

    temp_dir, temp_path = _save_upload_to_temp(uploaded_file)

    @stream_with_context
    def generate():
        """NDJSON 生成器：逐行推送处理状态、增量内容与最终结果，异常时推送错误行。"""
        try:
            from app.services.pdf_pipeline import stream_process_pdf

            yield _build_json_line({"type": "status", "message": "文件已上传，开始处理..."})
            for event in stream_process_pdf(temp_path, pdf_type, original_filename, prompt):
                yield _build_json_line(event)
        except Exception as exc:
            yield _build_json_line({"type": "error", "error": str(exc)})
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    return Response(generate(), mimetype="application/x-ndjson")
