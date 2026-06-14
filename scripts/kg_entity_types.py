#!/usr/bin/env python3
"""kg_entity_types.py — 知识图谱实体类型定义

定义萃取管线中使用的实体类型、关系类型、prompt 模板。
与 kg_extract.py / kg_store.py 共享。
"""

# ── 实体类型体系 ──────────────────────────────────────
ENTITY_TYPES = {
    "concept": {
        "label": "核心概念",
        "desc": "抽象的理论/概念/术语（如 RRF混合搜索, 安全边际, 知识图谱）",
        "color": "#4A90D9",
    },
    "person": {
        "label": "人物",
        "desc": "真实人物（如 Andrej Karpathy, Tiago Forte）",
        "color": "#E67E22",
    },
    "company": {
        "label": "公司/机构",
        "desc": "公司、组织、产品团队（如 OpenAI, DeepSeek, 中际旭创）",
        "color": "#27AE60",
    },
    "factor": {
        "label": "投资因子",
        "desc": "量化投资因子（如 资金流因子, 趋势因子, CK因子）",
        "color": "#8E44AD",
    },
    "indicator": {
        "label": "指标/度量",
        "desc": "可量化的指标值（如 IC值, PE分位数, RSI, ROE）",
        "color": "#F39C12",
    },
    "method": {
        "label": "方法/框架",
        "desc": "方法论、工作流、框架（如 Zettelkasten, PARA, RRF）",
        "color": "#1ABC9C",
    },
    "tool": {
        "label": "工具/系统",
        "desc": "软件工具、系统平台（如 Obsidian, MiniMax, Hermes Agent）",
        "color": "#E74C3C",
    },
    "domain": {
        "label": "领域/学科",
        "desc": "知识领域、研究学科（如 知识管理, 量化投资, AI工程）",
        "color": "#2C3E50",
    },
}

# ── 关系类型 ──────────────────────────────────────────
RELATION_TYPES = {
    "is_a": {
        "label": "是子类/实例",
        "desc": "实体A是实体B的子类或实例（RRF is_a 搜索方法）",
    },
    "part_of": {
        "label": "组成部分",
        "desc": "实体A是实体B的组成部分（实体抽取 part_of 知识图谱引擎）",
    },
    "uses": {
        "label": "使用/依赖",
        "desc": "实体A使用/依赖实体B（知识图谱 uses MiniMax）",
    },
    "related_to": {
        "label": "一般相关",
        "desc": "实体A与实体B显著相关但没有强语义关系",
    },
    "influences": {
        "label": "影响关系",
        "desc": "实体A影响/驱动实体B（资金流 influences 股价）",
    },
    "contrasts_with": {
        "label": "对比/替代",
        "desc": "实体A与实体B可对比或互为替代（RAG contrasts_with LLM Wiki）",
    },
}

# ── LLM Prompt 模板 ──────────────────────────────────

SYSTEM_PROMPT = """你是一个知识图谱实体抽取专家。请从一段笔记内容中提取结构化的实体和关系。

## 实体类型（8种）

{entity_type_guide}

## 关系类型（6种）

{relation_type_guide}

## 输出格式

请只返回一个 JSON 对象，格式如下：
{{
  "entities": [
    {{
      "name": "实体名称",
      "type": "concept|person|company|factor|indicator|method|tool|domain",
      "description": "一句话描述（10-30字）",
      "aliases": ["别名1", "别名2"]
    }}
  ],
  "relations": [
    {{
      "source": "源实体名称",
      "target": "目标实体名称",
      "type": "is_a|part_of|uses|related_to|influences|contrasts_with",
      "description": "关系描述（可选，5-15字）"
    }}
  ]
}}

## 抽取原则

1. **只抽取对知识管理/投资研究有长期价值的实体**——不要抽取通用词汇（如"数据"、"系统"、"方法"）
2. **宁少勿滥**：疑似不确定的不要抽取，每个笔记通常 3-8 个实体，3-6 条关系
3. **实体名称用规范中文名**，英文名放入 aliases
4. **关系必须有依据**：笔记中明确提及/对比/关联时才能提取关系
5. **description 控制在 10-30 字**，一句话说明该实体在本笔记中的定位
6. **避免重复**：如果笔记中多次提到同一个实体，只输出一次
"""

def build_system_prompt() -> str:
    """构建完整的 system prompt"""
    entity_guide = "\n".join(
        f"  - {k}: {v['desc']}"
        for k, v in ENTITY_TYPES.items()
    )
    relation_guide = "\n".join(
        f"  - {k}: {v['desc']}"
        for k, v in RELATION_TYPES.items()
    )
    return SYSTEM_PROMPT.format(
        entity_type_guide=entity_guide,
        relation_type_guide=relation_guide,
    )


def valid_entity_type(t: str) -> bool:
    return t in ENTITY_TYPES


def valid_relation_type(t: str) -> bool:
    return t in RELATION_TYPES


if __name__ == "__main__":
    print(build_system_prompt())
