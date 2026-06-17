#!/usr/bin/env python3
"""kms_search_enhance.py — KMS搜索增强: TF-IDF排序

为KMS的fallback关键词搜索添加TF-IDF排序,
让最相关的结果排第一, 而不是随机顺序。

用法:
    from kms_search_enhance import TfIdfSearcher
    searcher = TfIdfSearcher()
    results = searcher.search("注意力机制")
"""

import math
import re
import json
from collections import Counter
from pathlib import Path
from typing import Optional
from _path_setup import WIKI_DIR


class TfIdfSearcher:
    """TF-IDF搜索引擎 (用于KMS fallback搜索增强).

    当前KMS fallback: 关键词匹配 → 无序返回
    改进: 关键词匹配 → TF-IDF排序 → 最相关排第一
    """

    def __init__(self, wiki_dir: str = str(WIKI_DIR)):
        self.wiki_dir = Path(wiki_dir)
        self._doc_freq: dict[str, int] = Counter()
        self._doc_tf: dict[str, dict[str, float]] = {}
        self._doc_count = 0
        self._index_built = False

    def search(self, keyword: str, top_n: int = 10) -> list[dict]:
        """搜索并返回TF-IDF排序的结果.

        Args:
            keyword: 搜索关键词
            top_n: 返回前N条

        Returns:
            [{"path": "...", "title": "...", "score": 0.xx, "snippet": "..."}]
        """
        if not self._index_built:
            self._build_index()

        words = self._tokenize(keyword)
        if not words:
            return []

        # 计算每个文档的TF-IDF分数
        scores: dict[str, float] = {}
        for doc_id in self._doc_tf:
            score = 0.0
            for word in words:
                tf = self._doc_tf[doc_id].get(word, 0)
                if tf > 0:
                    idf = math.log(self._doc_count / self._doc_freq.get(word, 1))
                    score += tf * idf
            if score > 0:
                scores[doc_id] = score

        # 排序
        results = []
        for doc_id in sorted(scores, key=lambda d: scores[d], reverse=True)[:top_n]:
            results.append({
                "path": doc_id,
                "title": Path(doc_id).stem,
                "score": round(scores[doc_id], 4),
            })
        return results

    def _build_index(self):
        """构建TF-IDF索引 (扫描所有wiki文件)."""
        md_files = list(self.wiki_dir.rglob("*.md"))
        for f in md_files:
            if ".obsidian" in str(f):
                continue
            try:
                content = f.read_text(encoding="utf-8")
                words = self._tokenize(content)
                if not words:
                    continue
                total = len(words)
                word_counts = Counter(words)
                tf = {w: c / total for w, c in word_counts.items()}
                rel_path = str(f.relative_to(self.wiki_dir))
                self._doc_tf[rel_path] = tf
                for word in set(words):
                    self._doc_freq[word] += 1
                self._doc_count += 1
            except Exception:
                continue
        self._index_built = True

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """中文+英文分词 (简单版)."""
        text = text.lower()
        # 提取英文单词
        words = re.findall(r'[a-z0-9]+', text)
        # 提取中文 (按字符)
        chinese_chars = re.findall(r'[\u4e00-\u9fff]+', text)
        for chars in chinese_chars:
            # 中文按二元组切分 (bigram)
            for i in range(len(chars) - 1):
                words.append(chars[i:i+2])
            # 也保留单个字符
            for c in chars:
                words.append(c)
        return words


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        searcher = TfIdfSearcher()
        results = searcher.search(sys.argv[1])
        print(f"搜索 '{sys.argv[1]}' 结果 (TF-IDF排序):")
        for r in results[:5]:
            print(f"  {r['score']:.4f}  {r['path']}")
    else:
        print("用法: python3 kms_search_enhance.py <关键词>")
