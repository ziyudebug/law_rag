"""
PaddleOCR 扫描件 PDF OCR 接口：调用 PaddleOCRVL 流水线把 PDF 转为 Markdown。

按文件名做结果缓存（merged.md / doc_*.md / result.json），命中缓存直接读回，避免重复 OCR。

@author: ziyu
@date: 2026-07-17
"""
import base64
import json
import re
from pathlib import Path
from typing import Any, Optional
import random
from typing import List
import requests

from app.core.config import settings

from paddleocr import PaddleOCRVL
pipeline = PaddleOCRVL(
    vl_rec_backend=settings.paddle_vl_backend,
    vl_rec_server_url=settings.paddle_vl_server_url,
)


OUTPUT_ROOT = Path(settings.paddle_ocr_output_root).expanduser() if settings.paddle_ocr_output_root else Path(__file__).resolve().parent / "output"



def _encode_file(file_path: Path) -> str:
    """读取文件并返回 base64 编码字符串。"""
    with file_path.open("rb") as file:
        return base64.b64encode(file.read()).decode("ascii")


def _sanitize_cache_name(filename: str) -> str:
    """把文件名规整为安全的缓存目录名（去除路径分隔符等特殊字符，截断到 120 字符）。"""
    stem = Path(filename).stem.strip() or "unnamed_pdf"
    sanitized = re.sub(r'[\\/:*?"<>|]+', "_", stem)
    return sanitized[:120]


def get_cache_dir(filename: str) -> Path:
    """按文件名获取（必要时创建）OCR 结果缓存目录。"""
    cache_dir = OUTPUT_ROOT / _sanitize_cache_name(filename)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _page_number(path: Path) -> int:
    """从 doc_N.md 文件名解析页码，用于排序。"""
    matched = re.search(r"doc_(\d+)\.md$", path.name)
    return int(matched.group(1)) if matched else 0


def load_cached_markdown(cache_dir: str | Path) -> str:
    """读取缓存的 Markdown：优先 merged.md，否则按页码拼接 doc_*.md。"""
    cache_path = Path(cache_dir)
    merged_file = cache_path / "merged.md"
    if merged_file.exists():
        return merged_file.read_text(encoding="utf-8").strip()

    doc_files = sorted(cache_path.glob("doc_*.md"), key=_page_number)
    if not doc_files:
        return ""

    markdown_parts = [doc_file.read_text(encoding="utf-8").strip() for doc_file in doc_files]
    return "\n\n".join(part for part in markdown_parts if part).strip()


def load_cached_json(cache_dir: str | Path) -> Optional[dict[str, Any]]:
    """读取缓存目录中的 result.json，不存在返回 None。"""
    result_file = Path(cache_dir) / "result.json"
    if not result_file.exists():
        return None
    return json.loads(result_file.read_text(encoding="utf-8"))


def save_cached_json(cache_dir: str | Path, data: dict[str, Any]) -> None:
    """把结果写入缓存目录的 result.json。"""
    result_file = Path(cache_dir) / "result.json"
    result_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _persist_summary_files(cache_dir: Path, file_name: str, markdown: str) -> None:
    """把源文件名与合并后的 Markdown 落盘到缓存目录。"""
    (cache_dir / "source_filename.txt").write_text(file_name, encoding="utf-8")
    (cache_dir / "merged.md").write_text(markdown, encoding="utf-8")


def extract_markdown_from_pdf(
    pdf_path: str | Path,
    file_type: int,
    save_output_dir: Optional[str | Path] = None,
) -> str:
    """调用 PaddleOCRVL 解析 PDF 为 Markdown，可选把每页 md 与图片落盘到 save_output_dir。"""
    file_path = Path(pdf_path).expanduser().resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"PDF 文件不存在: {file_path}")



    layout_results = pipeline.predict(str(file_path))

    if not layout_results:
        raise RuntimeError("OCR 服务返回为空，未解析到页面内容。")

    output_dir = None
    if save_output_dir is not None:
        output_dir = Path(save_output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    markdown_parts: list[str] = []
    for index, page in enumerate(layout_results, start=1):
        markdown = page.markdown.get('markdown_texts','').strip()
        if markdown:
            markdown_parts.append(f"===== 第{index}页 =====\n{markdown}")

        if output_dir is not None:
            md_filename = output_dir / f"doc_{index - 1}.md"
            md_filename.write_text(markdown, encoding="utf-8")

            for image_path, image_url in page.get("markdown", {}).get("images", {}).items():
                image_target = output_dir / image_path
                image_target.parent.mkdir(parents=True, exist_ok=True)
                image_response = requests.get(image_url, timeout=60)
                image_response.raise_for_status()
                image_target.write_bytes(image_response.content)

            for image_name, image_url in page.get("outputImages", {}).items():
                image_response = requests.get(image_url, timeout=60)
                image_response.raise_for_status()
                target = output_dir / f"{image_name}_{index - 1}.jpg"
                target.write_bytes(image_response.content)

    merged_markdown = "\n\n".join(markdown_parts).strip()
    if not merged_markdown:
        raise RuntimeError("OCR 服务执行成功，但没有返回可用 Markdown 文本。")
    return merged_markdown


def extract_markdown_with_cache(
    pdf_path: str | Path,
    file_name: str,
    file_type: int,
) -> tuple[str, dict[str, Any]]:
    """带缓存的 OCR 入口：命中缓存直接返回，否则执行 OCR 并落盘缓存。"""
    cache_dir = get_cache_dir(file_name)
    cached_markdown = load_cached_markdown(cache_dir)
    if cached_markdown:
        return cached_markdown, {
            "cacheDir": str(cache_dir),
            "ocrFromCache": True,
        }

    markdown = extract_markdown_from_pdf(pdf_path, file_type=file_type, save_output_dir=cache_dir)
    _persist_summary_files(cache_dir, file_name, markdown)
    return markdown, {
        "cacheDir": str(cache_dir),
        "ocrFromCache": False,
    }
