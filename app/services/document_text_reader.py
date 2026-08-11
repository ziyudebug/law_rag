"""
文档文本读取模块。

按文件扩展名分派到不同读取策略：PDF 走 pdf_pipeline（文本/OCR）、纯文本直接读取、
Office 走 textract。返回 (文本内容, 抽取元数据)。

@author: ziyu
@date: 2026-07-13
"""
from pathlib import Path
from typing import Any


PDF_EXTS = {".pdf"}
TEXT_EXTS = {".md", ".txt"}
OFFICE_EXTS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}


class UnsupportedDocumentType(ValueError):
    """不支持的文件类型异常。"""
    pass


class DocumentTextReader:
    """按扩展名分派的文档文本读取器。"""

    def read(self, file_path: Path, original_filename: str) -> tuple[str, dict[str, Any]]:
        """读取文档文本，返回 (文本内容, 抽取方法元数据)。不支持的类型抛 UnsupportedDocumentType。"""
        ext = file_path.suffix.lower()
        if ext in PDF_EXTS:
            from app.services.pdf_pipeline import extract_document_text

            return extract_document_text(file_path, "image", original_filename)
        if ext in TEXT_EXTS:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            return content, {
                "extractionMethod": "plain_text",
                "sourceTextLength": len(content),
            }
        if ext in OFFICE_EXTS:
            return self._read_office(file_path)
        raise UnsupportedDocumentType(f"暂不支持的文件类型: {ext or '未知'}")

    def _read_office(self, file_path: Path) -> tuple[str, dict[str, Any]]:
        """用 textract 读取 Office 文档，返回 (文本内容, 元数据)。"""
        try:
            import textract
        except ImportError as exc:
            raise RuntimeError("读取 Office 文件需要安装 textract。") from exc

        content = textract.process(file_path).decode("utf-8", errors="ignore")
        return content, {
            "extractionMethod": "textract",
            "sourceTextLength": len(content),
        }
