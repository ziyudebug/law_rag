"""
父子分段器模块。

兼容普通文本 / 法规文档 / Markdown 表格 / HTML 表格片段混合文档，做父子两层分段：
父段粗粒度（按章节/法条边界），子段细粒度（按字符滑窗），表格整体保留并按行组切子块。
对外接口：ParentChildChunker.split(document_text) -> ParentChildChunkPlan。

@author: ziyu
@date: 2026-07-17
"""
import re
import uuid
from html import unescape
from html.parser import HTMLParser
from typing import Any, List, Tuple, Optional

from app.core.config import settings
from app.services.chunk_models import ChildChunkDraft, ParentChildChunkPlan, ParentChunkDraft

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    RecursiveCharacterTextSplitter = None

# ====================== 正则规则 ======================
# 分页标记：===== 第(\d+)页 =====
PAGE_PATTERN = re.compile(r"===== 第(\d+)页 =====")
# 匹配章节标题：第X章
CHAPTER_PATTERN = re.compile(r"(第[一二三四五六七八九十百千万\d]+章[^\n。；;]*)")
# 匹配法条条目：第X条
ARTICLE_PATTERN = re.compile(r"(第[一二三四五六七八九十百千万\d]+条)")
# Markdown表格识别
MD_TABLE_PATTERN = re.compile(r"((?:\|.*\|\n)+)")
MD_TABLE_SEP_PATTERN = re.compile(r"\|[\s\-:]+\|")
# HTML表格识别。一个<table>...</table>整体作为一个表格片段。
HTML_TABLE_PATTERN = re.compile(r"(<table\b.*?</table>)", re.IGNORECASE | re.DOTALL)


class HtmlTableParser(HTMLParser):
    """轻量HTML表格解析器，仅依赖标准库。负责把 <table> 解析成带 rowspan/colspan 的二维网格。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, Any]]] = []
        self._current_row: list[dict[str, Any]] | None = None
        self._current_cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """处理开始标签：tr 开始新行，td/th 开始新单元格（记录 rowspan/colspan）。"""
        tag = tag.lower()
        if tag == "tr":
            self._current_row = []
            return
        if tag in {"td", "th"} and self._current_row is not None:
            attr_map = {key.lower(): value for key, value in attrs}
            self._current_cell = {
                "text_parts": [],
                "rowspan": self._positive_int(attr_map.get("rowspan"), 1),
                "colspan": self._positive_int(attr_map.get("colspan"), 1),
                "is_header": tag == "th",
            }
            return
        if tag == "br" and self._current_cell is not None:
            self._current_cell["text_parts"].append("\n")

    def handle_data(self, data: str) -> None:
        """收集单元格内的文本数据。"""
        if self._current_cell is not None:
            self._current_cell["text_parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        """处理结束标签：td/th 收尾并入行，tr 结束把行并入结果。"""
        tag = tag.lower()
        if tag in {"td", "th"} and self._current_cell is not None and self._current_row is not None:
            cell = self._current_cell
            self._current_row.append(
                {
                    "text": self._normalize_cell_text("".join(cell["text_parts"])),
                    "rowspan": cell["rowspan"],
                    "colspan": cell["colspan"],
                    "is_header": cell["is_header"],
                }
            )
            self._current_cell = None
            return
        if tag == "tr" and self._current_row is not None:
            if self._current_row:
                self.rows.append(self._current_row)
            self._current_row = None

    def error(self, message: str) -> None:
        return

    @staticmethod
    def _positive_int(value: str | None, default: int) -> int:
        """把值解析为不小于 1 的正整数，失败用默认值。"""
        try:
            parsed = int(value or default)
        except (TypeError, ValueError):
            return default
        return max(1, parsed)

    @staticmethod
    def _normalize_cell_text(text: str) -> str:
        """规范化单元格文本：反转义、压空白、去首尾。"""
        text = unescape(text).replace("\\n", " ").replace("\xa0", " ")
        return re.sub(r"\s+", " ", text).strip()


class TextSplitter:
    """通用文本分割工具类，优先用 LangChain 递归分割，未安装时兜底滑动窗口。"""

    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        if RecursiveCharacterTextSplitter:
            self._splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=["\n\n", "\n", "。", "；", ";", "，", ",", " ", ""],
            )
        else:
            self._splitter = None

    def split_text(self, text: str) -> list[str]:
        """分割文本为多个子串：优先 LangChain，否则用滑动窗口。"""
        text = text.strip()
        if not text:
            return []
        if self._splitter:
            return [item.strip() for item in self._splitter.split_text(text) if item.strip()]
        return self._split_by_window(text)

    def _split_by_window(self, text: str) -> list[str]:
        """滑动窗口兜底分割：按 chunk_size 切，按 step 步进（步长=大小-重叠）。"""
        chunks: list[str] = []
        start = 0
        text_length = len(text)
        step = max(1, self.chunk_size - self.chunk_overlap)
        while start < text_length:
            end = min(text_length, start + self.chunk_size)
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end == text_length:
                break
            start += step
        return chunks


class ParentChildChunker:
    """
    【增强版】兼容：普通文本 / 法规文档 / Markdown表格 / HTML表格片段混合文档
    对外接口保持不变：split(document_text) -> ParentChildChunkPlan
    """
    def __init__(
        self,
        parent_chunk_size: int | None = None,
        parent_chunk_overlap: int | None = None,
        child_chunk_size: int | None = None,
        child_chunk_overlap: int | None = None,
        table_row_group_size: int | None = None,  # 表格子块：每N行合并为一个子块
    ):
        self.parent_chunk_size = parent_chunk_size or settings.parent_chunk_size
        self.table_row_group_size = table_row_group_size or settings.table_row_group_size
        self.parent_splitter = TextSplitter(
            self.parent_chunk_size,
            parent_chunk_overlap or settings.parent_chunk_overlap,
        )
        self.child_splitter = TextSplitter(
            child_chunk_size or settings.child_chunk_size,
            child_chunk_overlap or settings.child_chunk_overlap,
        )

    def split(self, document_text: str) -> ParentChildChunkPlan:
        """对文档做父子两层分段，返回分段计划（父段列表 + 子段列表）。

        先把文档拆成「文本 / Markdown 表格 / HTML 表格」三类片段，再分别处理：
        文本段做语义预切分后父子两层切；表格段整体保留，按行组切子块。
        """
        parents: List[ParentChunkDraft] = []
        children: List[ChildChunkDraft] = []
        # 全局上下文状态（顺序继承）
        ctx = {
            "last_page_no": None,
            "last_chapters": [],
            "last_articles": [],
            "parent_seq": 0,
            "child_seq": 0,
        }

        # 步骤1：拆分【文本片段 / 表格片段】
        seg_list = self._split_text_and_tables(document_text)

        for seg_type, seg_content, seg_global_start in seg_list:
            if seg_type == "text":
                p_list, c_list, ctx = self._process_text_segment(seg_content, seg_global_start, ctx)
                parents.extend(p_list)
                children.extend(c_list)
            elif seg_type == "markdown_table":
                p_list, c_list, ctx = self._process_table_segment(seg_content, seg_global_start, ctx)
                parents.extend(p_list)
                children.extend(c_list)
            elif seg_type == "html_table":
                p_list, c_list, ctx = self._process_html_table_segment(seg_content, seg_global_start, ctx)
                parents.extend(p_list)
                children.extend(c_list)

        return ParentChildChunkPlan(parents=parents, children=children)

    # ====================== 结构拆分：区分文本与表格 ======================
    def _split_text_and_tables(self, full_text: str) -> List[Tuple[str, str, int]]:
        """把全文拆成 [(type, content, global_start_offset)]；type: text / markdown_table / html_table。"""
        result: List[Tuple[str, str, int]] = []
        table_matches: list[tuple[int, int, str, str]] = []

        html_spans: list[tuple[int, int]] = []
        for match in HTML_TABLE_PATTERN.finditer(full_text):
            s, e = match.span()
            html_spans.append((s, e))
            table_matches.append((s, e, "html_table", match.group(1)))

        for match in MD_TABLE_PATTERN.finditer(full_text):
            s, e = match.span()
            if self._overlaps_any((s, e), html_spans):
                continue
            table_matches.append((s, e, "markdown_table", match.group(1)))

        table_matches.sort(key=lambda item: item[0])
        last_pos = 0
        for s, e, table_type, table_content in table_matches:
            if e <= last_pos or s < last_pos:
                continue
            if s > last_pos:
                result.append(("text", full_text[last_pos:s], last_pos))
            result.append((table_type, table_content, s))
            last_pos = e
        if last_pos < len(full_text):
            result.append(("text", full_text[last_pos:], last_pos))
        return result

    def _overlaps_any(self, span: tuple[int, int], candidates: list[tuple[int, int]]) -> bool:
        """判断 span 是否与任一候选区间重叠（用于避免 Markdown 表格与 HTML 表格重复匹配）。"""
        start, end = span
        return any(start < candidate_end and end > candidate_start for candidate_start, candidate_end in candidates)

    # ====================== 处理普通文本/法规段落 ======================
    def _process_text_segment(
        self, seg_text: str, base_offset: int, ctx: dict
    ) -> Tuple[List[ParentChunkDraft], List[ChildChunkDraft], dict]:
        """处理普通文本段：清理分页标记→语义预切分→父段切分→子段切分，带章节/法条上下文继承。"""
        parents: List[ParentChunkDraft] = []
        children: List[ChildChunkDraft] = []

        # 提取本段内所有页码标记（同时清理分页标记正文）
        page_marks = []
        for m in PAGE_PATTERN.finditer(seg_text):
            page_marks.append(int(m.group(1)))
        clean_text = PAGE_PATTERN.sub("", seg_text).strip()
        if not clean_text:
            return parents, children, ctx

        # 更新全局页码上下文
        if page_marks:
            ctx["last_page_no"] = page_marks[-1]
        current_page = ctx["last_page_no"]
        page_range = (min(page_marks), max(page_marks)) if page_marks else None

        # ===== 语义预分割：优先按章、条分割，尽量不切断法条 =====
        semantic_segs = self._semantic_pre_split(clean_text)
        raw_parent_candidates = []
        for seg in semantic_segs:
            if len(seg) <= self.parent_chunk_size:
                raw_parent_candidates.append(seg)
            else:
                raw_parent_candidates.extend(self.parent_splitter.split_text(seg))

        # 遍历生成父块、子块
        for p_text in raw_parent_candidates:
            # 提取当前块内所有章节、法条
            chapters = [m.group(1) for m in CHAPTER_PATTERN.finditer(p_text)]
            articles = [m.group(1) for m in ARTICLE_PATTERN.finditer(p_text)]
            # 上下文兜底继承
            if not chapters:
                chapters = ctx["last_chapters"]
            else:
                ctx["last_chapters"] = chapters
            if not articles:
                articles = ctx["last_articles"]
            else:
                ctx["last_articles"] = articles

            first_chapter = chapters[0] if chapters else None
            first_article = articles[0] if articles else None

            p_start = base_offset + seg_text.find(p_text)
            p_end = p_start + len(p_text)

            parent = ParentChunkDraft(
                chunk_no=ctx["parent_seq"],
                content=p_text,
                page_no=current_page,
                chapter=first_chapter,
                article=first_article,
                token_count=len(p_text),
                metadata={
                    "length": len(p_text),
                    "page_single": current_page,
                    "page_range": page_range,
                    "chunk_type": "text_parent",
                    "all_chapters": chapters,
                    "all_articles": articles,
                    "start_offset": p_start,
                    "end_offset": p_end,
                },
            )
            parents.append(parent)
            ctx["parent_seq"] += 1

            # 父块切分子块
            for c_text in self.child_splitter.split_text(p_text):
                c_start = p_start + p_text.find(c_text)
                c_end = c_start + len(c_text)
                # 子块局部匹配标题，无则继承父
                c_chaps = [m.group(1) for m in CHAPTER_PATTERN.finditer(c_text)] or chapters
                c_arts = [m.group(1) for m in ARTICLE_PATTERN.finditer(c_text)] or articles
                c_chap = c_chaps[0] if c_chaps else None
                c_art = c_arts[0] if c_arts else None

                child = ChildChunkDraft(
                    chunk_no=ctx["child_seq"],
                    parent_no=parent.chunk_no,
                    content=c_text,
                    page_no=current_page,
                    chapter=c_chap,
                    article=c_art,
                    token_count=len(c_text),
                    milvus_id=str(uuid.uuid4()),
                    metadata={
                        "chunk_type": "text_child",
                        "all_chapters": c_chaps,
                        "all_articles": c_arts,
                        "parent_chunk_no": parent.chunk_no,
                        "start_offset": c_start,
                        "end_offset": c_end,
                    },
                )
                children.append(child)
                ctx["child_seq"] += 1
        return parents, children, ctx

    def _semantic_pre_split(self, text: str) -> List[str]:
        """语义预切分：以章节、法条作为分割边界，避免法条被截断"""
        # 捕获分隔符并保留匹配内容
        raw_parts = re.split(r"(第[一二三四五六七八九十百千万\d]+[章节条])", text)
        segments = []
        buffer = ""
        for idx, part in enumerate(raw_parts):
            if idx % 2 == 1:
                buffer += part
            else:
                buffer += part
                if buffer.strip():
                    segments.append(buffer.strip())
                    buffer = ""
        if buffer.strip():
            segments.append(buffer.strip())
        return segments

    # ====================== 处理HTML表格片段 ======================
    def _process_html_table_segment(
        self, table_raw: str, base_offset: int, ctx: dict
    ) -> Tuple[List[ParentChunkDraft], List[ChildChunkDraft], dict]:
        """处理 HTML 表格段：解析成二维网格→格式化为文本→整体作为父子段（内容相同）。"""
        grid = self._parse_html_table_grid(table_raw)
        if not grid:
            fallback_text = self._strip_html_tags(table_raw)
            if not fallback_text:
                return [], [], ctx
            grid = [[fallback_text]]

        table_text = self._format_html_table_chunk(grid)
        current_page = ctx["last_page_no"]
        chapters = ctx["last_chapters"]
        articles = ctx["last_articles"]
        first_chapter = chapters[0] if chapters else None
        first_article = articles[0] if articles else None
        p_start = base_offset
        p_end = base_offset + len(table_raw)
        row_count = len(grid)
        column_count = max((len(row) for row in grid), default=0)

        parent = ParentChunkDraft(
            chunk_no=ctx["parent_seq"],
            content=table_text,
            page_no=current_page,
            chapter=first_chapter,
            article=first_article,
            token_count=len(table_text),
            metadata={
                "chunk_type": "html_table_parent",
                "table_format": "html",
                "row_count": row_count,
                "column_count": column_count,
                "start_offset": p_start,
                "end_offset": p_end,
                "all_chapters": chapters,
                "all_articles": articles,
            },
        )
        ctx["parent_seq"] += 1

        child = ChildChunkDraft(
            chunk_no=ctx["child_seq"],
            parent_no=parent.chunk_no,
            content=table_text,
            page_no=current_page,
            chapter=first_chapter,
            article=first_article,
            token_count=len(table_text),
            milvus_id=str(uuid.uuid4()),
            metadata={
                "chunk_type": "html_table_child",
                "table_format": "html",
                "row_count": row_count,
                "column_count": column_count,
                "parent_chunk_no": parent.chunk_no,
                "start_offset": p_start,
                "end_offset": p_end,
                "all_chapters": chapters,
                "all_articles": articles,
            },
        )
        ctx["child_seq"] += 1
        return [parent], [child], ctx

    def _parse_html_table_grid(self, table_raw: str) -> list[list[str]]:
        """用 HtmlTableParser 解析 HTML 表格为二维文本网格（已展开 rowspan/colspan）。"""
        parser = HtmlTableParser()
        parser.feed(table_raw)
        parser.close()
        return self._expand_html_table_spans(parser.rows)

    def _expand_html_table_spans(self, rows: list[list[dict[str, Any]]]) -> list[list[str]]:
        """展开 rowspan/colspan：把跨行跨列单元格复制到对应位置，返回对齐的二维网格。"""
        grid: list[list[str]] = []
        pending_rowspans: dict[int, dict[str, Any]] = {}

        for raw_row in rows:
            expanded_row: list[str] = []
            col_idx = 0

            for cell in raw_row:
                col_idx = self._fill_pending_rowspans(expanded_row, pending_rowspans, col_idx)
                text = cell.get("text") or ""
                rowspan = max(1, int(cell.get("rowspan") or 1))
                colspan = max(1, int(cell.get("colspan") or 1))

                for offset in range(colspan):
                    expanded_row.append(text)
                    if rowspan > 1:
                        pending_rowspans[col_idx + offset] = {
                            "text": text,
                            "remaining": rowspan - 1,
                        }
                col_idx += colspan

            while pending_rowspans and col_idx <= max(pending_rowspans):
                col_idx = self._fill_pending_rowspans(expanded_row, pending_rowspans, col_idx)
                if col_idx <= max(pending_rowspans, default=-1):
                    expanded_row.append("")
                    col_idx += 1

            grid.append(expanded_row)

        column_count = max((len(row) for row in grid), default=0)
        return [row + [""] * (column_count - len(row)) for row in grid]

    def _fill_pending_rowspans(
        self,
        expanded_row: list[str],
        pending_rowspans: dict[int, dict[str, Any]],
        col_idx: int,
    ) -> int:
        """把仍有效的跨行单元格填入当前行，递减剩余行数，耗尽则移除。"""
        while col_idx in pending_rowspans:
            span = pending_rowspans[col_idx]
            expanded_row.append(str(span["text"]))
            span["remaining"] = int(span["remaining"]) - 1
            if span["remaining"] <= 0:
                del pending_rowspans[col_idx]
            col_idx += 1
        return col_idx

    def _format_html_table_chunk(self, grid: list[list[str]]) -> str:
        """把展开后的二维网格格式化为带行展开与单元格上下文的文本块。"""
        row_lines = self._format_expanded_table_rows(grid)
        cell_lines = self._format_table_cell_facts(grid)
        sections = [
            f"【HTML表格】行数：{len(grid)}，列数：{max((len(row) for row in grid), default=0)}",
            "【表格行展开】",
            *row_lines,
        ]
        if cell_lines:
            sections.extend(["【单元格上下文】", *cell_lines])
        return "\n".join(sections).strip()

    def _format_expanded_table_rows(self, grid: list[list[str]]) -> list[str]:
        """把每行非空单元格拼成「第N行：a | b | c」格式。"""
        lines = []
        for index, row in enumerate(grid, start=1):
            values = [cell for cell in row if cell]
            if values:
                lines.append(f"第{index}行：" + " | ".join(values))
        return lines

    def _format_table_cell_facts(self, grid: list[list[str]]) -> list[str]:
        """为表体单元格生成带行/列上下文的事实条目，提升检索可读性。"""
        facts: list[str] = []
        body_start = self._infer_table_body_start(grid)
        stub_columns = self._infer_stub_column_count(grid, body_start)
        seen: set[str] = set()

        for row_idx, row in enumerate(grid):
            if row_idx < body_start:
                continue
            for col_idx, value in enumerate(row):
                if col_idx < stub_columns:
                    continue
                if not value:
                    continue
                row_context = self._unique_non_empty(row[:stub_columns])
                column_context = self._unique_non_empty(
                    grid[above_idx][col_idx]
                    for above_idx in range(body_start)
                    if col_idx < len(grid[above_idx])
                )
                if not row_context and not column_context:
                    continue
                context_parts = []
                if row_context:
                    context_parts.append("行上下文：" + " / ".join(row_context))
                if column_context:
                    context_parts.append("列上下文：" + " / ".join(column_context))
                context_parts.append(f"值：{value}")
                fact = "- " + "；".join(context_parts)
                if fact not in seen:
                    seen.add(fact)
                    facts.append(fact)
        return facts

    def _infer_table_body_start(self, grid: list[list[str]]) -> int:
        """推断表体起始行（跳过表头），首行与后续行出现差异处即表体起点。"""
        if len(grid) <= 1:
            return 0
        first_row = grid[0]
        for row_idx, row in enumerate(grid[1:], start=1):
            comparable_columns = min(2, len(first_row), len(row))
            if any(row[col_idx] and row[col_idx] != first_row[col_idx] for col_idx in range(comparable_columns)):
                return row_idx
        return 1

    def _infer_stub_column_count(self, grid: list[list[str]], body_start: int) -> int:
        """推断存根列数（表头上下文唯一、作为行标识的前置列数）。"""
        if not grid or body_start <= 0 or body_start >= len(grid):
            return 0
        width = max(len(row) for row in grid)
        count = 0
        for col_idx in range(width):
            body_value = grid[body_start][col_idx] if col_idx < len(grid[body_start]) else ""
            column_context = self._unique_non_empty(
                grid[row_idx][col_idx]
                for row_idx in range(body_start)
                if col_idx < len(grid[row_idx])
            )
            if body_value and len(column_context) <= 1:
                count += 1
                continue
            break
        return count

    def _unique_non_empty(self, values) -> list[str]:
        """去重保留非空字符串，保持原顺序。"""
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in result:
                result.append(text)
        return result

    def _strip_html_tags(self, text: str) -> str:
        """剥离 HTML 标签并规范化空白，作为表格解析失败的兜底文本。"""
        text = re.sub(r"<[^>]+>", " ", text)
        text = unescape(text).replace("\\n", " ").replace("\xa0", " ")
        return re.sub(r"\s+", " ", text).strip()

    # ====================== 处理Markdown表格片段 ======================
    def _process_table_segment(
        self, table_raw: str, base_offset: int, ctx: dict
    ) -> Tuple[List[ParentChunkDraft], List[ChildChunkDraft], dict]:
        """处理 Markdown 表格段：解析表头/数据行→父段为摘要→子段按行组切。"""
        parents: List[ParentChunkDraft] = []
        children: List[ChildChunkDraft] = []
        lines = [ln.strip() for ln in table_raw.splitlines() if ln.strip()]
        if len(lines) < 2:
            return parents, children, ctx

        # 解析表头、数据行
        header_sep_index: Optional[int] = None
        for i, line in enumerate(lines):
            if MD_TABLE_SEP_PATTERN.match(line):
                header_sep_index = i
                break
        if header_sep_index is None or header_sep_index == 0:
            return parents, children, ctx

        header_cells = [c.strip() for c in lines[header_sep_index - 1].split("|")[1:-1]]
        data_rows = []
        for line in lines[header_sep_index + 1:]:
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) == len(header_cells):
                data_rows.append(dict(zip(header_cells, cells)))
        if not data_rows:
            return parents, children, ctx

        # 继承上下文章节/页码
        current_page = ctx["last_page_no"]
        chapters = ctx["last_chapters"]
        articles = ctx["last_articles"]
        first_chapter = chapters[0] if chapters else None
        first_article = articles[0] if articles else None

        table_summary = f"表格信息：表头【{', '.join(header_cells)}】，共{len(data_rows)}行"
        p_start = base_offset
        p_end = base_offset + len(table_raw)

        # 表格父块
        parent = ParentChunkDraft(
            chunk_no=ctx["parent_seq"],
            content=table_summary,
            page_no=current_page,
            chapter=first_chapter,
            article=first_article,
            token_count=len(table_summary),
            metadata={
                "chunk_type": "table_parent",
                "columns": header_cells,
                "total_rows": len(data_rows),
                "start_offset": p_start,
                "end_offset": p_end,
                "all_chapters": chapters,
                "all_articles": articles,
            }
        )
        parents.append(parent)
        ctx["parent_seq"] += 1

        # 按行组构建子块
        group_size = self.table_row_group_size
        for group_idx in range(0, len(data_rows), group_size):
            group_rows = data_rows[group_idx: group_idx + group_size]
            text_parts = []
            row_data_list = []
            for row in group_rows:
                text_parts.append("；".join(f"{k}={v}" for k, v in row.items()))
                row_data_list.append(row)
            child_text = "【附表】" + " | ".join(text_parts)

            child = ChildChunkDraft(
                chunk_no=ctx["child_seq"],
                parent_no=parent.chunk_no,
                content=child_text,
                page_no=current_page,
                chapter=first_chapter,
                article=first_article,
                token_count=len(child_text),
                milvus_id=str(uuid.uuid4()),
                metadata={
                    "chunk_type": "table_child",
                    "columns": header_cells,
                    "row_group_start": group_idx,
                    "row_group_end": group_idx + len(group_rows) - 1,
                    "raw_rows": row_data_list,
                    "all_chapters": chapters,
                    "all_articles": articles,
                }
            )
            children.append(child)
            ctx["child_seq"] += 1
        return parents, children, ctx
