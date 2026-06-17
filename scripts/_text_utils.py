"""_text_utils.py — 共享文本处理工具函数

从 rrf_search.py 提取，供 process_pdf.py 等模块复用。
"""
import re


def chunk_text(text: str, max_chars: int = 2000, overlap: int = 300) -> list[str]:
    """将长文本分割成有意义的块, 优先按标题拆分

    Args:
        text: 输入文本
        max_chars: 每块最大字符数
        overlap: 块间重叠字符数

    Returns:
        文本块列表
    """
    sections = re.split(r'\n(?=#+\s)', text)
    if len(sections) <= 1:
        sections = text.split("\n\n")

    chunks = []
    current = ""
    for s in sections:
        s = s.strip()
        if not s:
            continue
        if len(current) + len(s) > max_chars and current:
            chunks.append(current)
            current = current[-overlap:] + "\n\n" + s if overlap else s
        else:
            current = (current + "\n\n" + s).strip() if current else s
    if current:
        chunks.append(current)
    return chunks if chunks else [text[:max_chars]]


def strip_markdown(text: str) -> str:
    """去除 Markdown 标记，保留纯文本"""
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'[*_~`#>\-]', '', text)
    text = re.sub(r'\n\s*\n', '\n', text)
    return text.strip()


def detect_chapters(text: str) -> list[tuple[str, int, str]]:
    """多语言章节检测，返回 [(标题, 行号, 标签), ...]

    支持 9 种模式：中文数字/阿拉伯数字章节、英文 Chapter/Part、双语混合等。
    """
    lines = text.split('\n')

    patterns = [
        (r'第[一二三四五六七八九十百零]+[章课]\s*[^\n]*', 'cn_num'),
        (r'第\d+[章课]\s*[^\n]*', 'cn_digit'),
        (r'[Cc][Hh][Aa][Pp][Tt][Ee][Rr]\s+\d+[^\n]*', 'en_chapter'),
        (r'[Pp][Aa][Rr][Tt]\s+[IVXLCDM\d]+[^\n]*', 'en_part'),
        (r'[Cc][Hh][Aa][Pp]\.?\s*\d+[^\n]*', 'en_variant'),
        (r'^\d+\.\s+[A-Z][^\n]{3,}', 'en_numbered'),
        (r'第[一二三四五六七八九十百零]+节', 'cn_section'),
        (r'Section\s+\d+', 'en_section'),
        (r'第\s*\d+\s*课', 'cn_lesson'),
    ]

    all_matches = []
    matched_patterns = set()

    for pattern, label in patterns:
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            m = re.search(pattern, line_stripped)
            if m:
                all_matches.append((m.group().strip(), i, label))
                matched_patterns.add(label)

    # 对话式书籍假阳性过滤：短行 + 上下文检查
    genuine = []
    for title, line_no, label in all_matches:
        if len(title) > 25:
            continue
        prev_line = lines[line_no - 1].strip() if line_no > 0 else ''
        if prev_line == '' or re.match(r'^\d+$', prev_line) or len(prev_line) < 5:
            genuine.append((title, line_no, label))

    if not genuine:
        return genuine

    # 去重（5行内的视为同一章节）
    seen_buckets = set()
    deduped = []
    for title, line_no, label in genuine:
        bucket = line_no // 5
        if bucket not in seen_buckets:
            seen_buckets.add(bucket)
            deduped.append((title, line_no, label))

    # 添加已知前缀章节
    front_keywords = ['序言', '前言', '引言', 'Preface', 'Introduction', 'Prologue',
                      '自序', '推荐序', '译者序']
    for kw in front_keywords:
        for i, line in enumerate(lines):
            if kw in line and i < len(lines) * 0.15:
                # 检查是否已存在
                if not any(kw in t for t, _, _ in deduped):
                    deduped.insert(0, (kw, i, 'front_matter'))
                break

    return deduped


def extract_metadata(text: str) -> dict:
    """从 PDF 文本开头提取元数据"""
    meta = {}
    lines = text.split('\n')[:50]
    for line in lines:
        line = line.strip()
        if not line:
            continue
        for key in ['作者', '出版社', 'ISBN', '出版年', '译者']:
            if key in line:
                parts = line.split(key, 1)
                if len(parts) > 1:
                    val = parts[1].lstrip('：:').strip()
                    if val and key not in meta:
                        meta[key] = val
    return meta
