"""
PDF 处理流水线模块。

提供 PDF 文本/OCR 提取、以及一次性 / 流式两种结构化抽取（通义千问按 prompt 抽取 JSON）。
OCR 结果与抽取结果均支持缓存，避免重复调用。

@author: ziyu
@date: 2026-04-24
"""
import json
from pathlib import Path
from typing import Any, Iterator
from . import pdftoimages
from model.paddleocr_model.api import (
    extract_markdown_with_cache,
    load_cached_json,
    save_cached_json,
)
from model.qwen.qwen_model import (
    generate_structured_json,
    parse_structured_json_text,
    stream_structured_json_text,
)


def _extract_text_with_pypdf(pdf_path: Path) -> str:
    """用 pypdf 本地提取文本型 PDF 文本，按页拼接并标注页码标记。无 pypdf 时返回空串。"""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""

    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(f"===== 第{index}页 =====\n{text}")
    return "\n\n".join(pages).strip()

def extract_document_text(
    pdf_path: str | Path,
    pdf_type: str,
    original_filename: str,
) -> tuple[str, dict[str, Any]]:
    """提取 PDF 文本，返回 (文本, 元数据)。

    - text 类型：优先本地 pypdf 提取，失败回退 OCR（file_type=0）；
    - image 类型：直接走 OCR（file_type=1）。
    """
    file_path = Path(pdf_path).expanduser().resolve()
    normalized_type = pdf_type.lower()

    if normalized_type == "text":
        # pdftoimages.pdf_to_image_pdf_compressed(pdf_path, pdf_path)
        # normalized_type = "image"
        local_text = _extract_text_with_pypdf(file_path)
        if local_text:
            return local_text, {
                "pdfType": pdf_type,
                "extractionMethod": "local_text",
                "sourceTextLength": len(local_text),
                "ocrFromCache": False,
                "cacheDir": None,
            }

        document_text, cache_meta = extract_markdown_with_cache(
            file_path,
            file_name=original_filename,
            file_type=0,
        )
        metadata = {
            "pdfType": pdf_type,
            "extractionMethod": "ocr_fallback",
            "sourceTextLength": len(document_text),
            **cache_meta,
        }
        return document_text, metadata

    if normalized_type != "image":
        raise ValueError("pdf_type 只支持 image 或 text。")

    document_text, cache_meta = extract_markdown_with_cache(
        file_path,
        file_name=original_filename,
        file_type=1,
    )
    metadata = {
        "pdfType": pdf_type,
        "extractionMethod": "ocr",
        "sourceTextLength": len(document_text),
        **cache_meta,
    }
    return document_text, metadata


def _stream_text_as_chars(content: str) -> Iterator[dict[str, Any]]:
    """把文本逐字符作为 chunk 事件生成，用于流式回放缓存 JSON。"""
    for char in content:
        yield {"type": "chunk", "content": char}


def process_pdf(
    pdf_path: str | Path,
    pdf_type: str,
    original_filename: str,
    prompt: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """一次性 PDF 结构化抽取：提取文本→命中缓存则回放→否则调 Qwen 抽取并写缓存。返回 (结构化结果, 元数据)。"""
    document_text, metadata = extract_document_text(pdf_path, pdf_type, original_filename)

    cache_dir = metadata.get("cacheDir")
    if cache_dir:
        cached_result = load_cached_json(cache_dir)
        if cached_result is not None:
            metadata["resultFromCache"] = True
            return cached_result, metadata

    structured_json = generate_structured_json(document_text,prompt)
    metadata["resultFromCache"] = False
    if cache_dir:
        save_cached_json(cache_dir, structured_json)
    return structured_json, metadata


def stream_process_pdf(
    pdf_path: str | Path,
    pdf_type: str,
    original_filename: str,
    prompt: str,
) -> Iterator[dict[str, Any]]:
    """流式 PDF 结构化抽取：逐事件推送状态/元数据/增量内容/最终结果，命中缓存则逐字符回放。"""
    yield {"type": "status", "message": "正在读取 PDF 并准备内容..."}
    document_text, metadata = extract_document_text(pdf_path, pdf_type, original_filename)
    yield {"type": "metadata", "metadata": metadata}

    cache_dir = metadata.get("cacheDir")
    if cache_dir:
        cached_result = load_cached_json(cache_dir)
        if cached_result is not None:
            metadata["resultFromCache"] = True
            yield {"type": "status", "message": "命中结果缓存，正在回放已生成 JSON..."}
            pretty_json = json.dumps(cached_result, ensure_ascii=False, indent=2)
            yield from _stream_text_as_chars(pretty_json)
            yield {"type": "done", "data": cached_result, "metadata": metadata}
            return

    metadata["resultFromCache"] = False
    yield {"type": "status", "message": "正在调用 Qwen 生成结构化 JSON..."}

    collected_parts: list[str] = []
    for chunk in stream_structured_json_text(document_text,prompt):
        collected_parts.append(chunk)
        for char in chunk:
            yield {"type": "chunk", "content": char}

    result_text = "".join(collected_parts)
    structured_json = parse_structured_json_text(result_text)
    if cache_dir:
        save_cached_json(cache_dir, structured_json)
    yield {"type": "done", "data": structured_json, "metadata": metadata}
