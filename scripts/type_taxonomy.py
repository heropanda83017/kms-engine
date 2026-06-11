"""
type_taxonomy.py — Wiki 页面类型体系

类型体系借鉴 GBrain 22种Schema的思路，但轻量化：
- 顶层10个类型，覆盖所有wiki笔记场景
- 每类型有清晰的判定规则+示例
- 供 quality_gate_scorer 和模板脚本引用

用法:
  from type_taxonomy import TYPES, detect_type_by_path, TYPE_LIST

类型定义:
  type       意思        典型场景                     示例
  ----       ----        --------                     ----
  research   研究分析    行业研究/公司分析/策略分析    投资研究/ck-chokepoint
  lecture    课程笔记    视频课程/讲座/AI教程         3Blue1Brown/晓辉博士
  reference  参考资料    工具说明/配置指南/系统文档    SCHEMA/EVOLUTION
  note       通用笔记    读书笔记/想法记录/个人总结    自进化知识库转写
  insight    洞察捕获    外部借鉴/对比分析/差距报告    Horizon-GBrain对比
  paper      论文精读    AI论文/学术文章              贝叶斯定理
  report     定期报告    周报/日报/同步状态报告        sync状态报告
  profile    人物画像    用户画像/个人介绍             胡盼画像
  system     系统文档    KMS配置/脚本/规则             SCHEMA.md
  index      导航索引    目录页/图谱/导航             索引/图谱导航
"""

TYPES = {
    "research": {
        "description": "研究分析",
        "examples": ["行业研究", "公司分析", "策略研究", "投资分析", "ck-chokepoint"],
        "detection": "包含投资/行业/策略/基本面/技术面/因子等分析性内容的笔记",
    },
    "lecture": {
        "description": "课程笔记",
        "examples": ["视频课程", "讲座笔记", "AI教程", "3Blue1Brown", "晓辉博士"],
        "detection": "来自视频/课程/演讲等学习材料的结构化笔记",
    },
    "reference": {
        "description": "参考资料",
        "examples": ["工具说明", "配置指南", "KMS文档", "SCHEMA", "EVOLUTION"],
        "detection": "系统文档/工具说明/配置指南/索引等元文档",
    },
    "note": {
        "description": "通用笔记",
        "examples": ["读书笔记", "想法记录", "个人总结", "转写"],
        "detection": "没有明确分类的个人笔记、文章摘要、转写文本",
    },
    "insight": {
        "description": "洞察捕获",
        "examples": ["外部借鉴", "对比分析", "差距报告", "外部借鉴记录"],
        "detection": "来自外部项目的借鉴分析、对比文章、差距评估",
    },
    "paper": {
        "description": "论文精读",
        "examples": ["AI论文", "学术文章", "arXiv论文"],
        "detection": "学术论文/预印本的结构化精读笔记",
    },
    "report": {
        "description": "定期报告",
        "examples": ["周报", "日报", "同步报告", "sync"],
        "detection": "按周期生成的系统状态/同步/健康检查报告",
    },
    "profile": {
        "description": "人物画像",
        "examples": ["用户画像", "个人介绍", "胡盼画像"],
        "detection": "关于特定人物的画像/背景介绍/能力评估",
    },
    "system": {
        "description": "系统文档",
        "examples": ["KMS配置", "脚本规则", "管线文档"],
        "detection": "关于系统架构/配置/CICD/规则的定义性文档",
    },
    "index": {
        "description": "导航索引",
        "examples": ["目录页", "图谱", "导航", "索引"],
        "detection": "导航页/索引页/图谱/目录等结构化导航",
    },
}

TYPE_LIST = list(TYPES.keys())
TYPE_VALUES = " | ".join(f"`{t}`" for t in TYPE_LIST)

# 按路径前缀自动检测类型的规则
PATH_RULES = [
    ("08-investment/06-投研分析/外部借鉴记录", "insight"),
    ("08-investment/04-因子研究", "research"),
    ("08-investment/03-宏观与产业", "research"),
    ("08-investment/02-行业", "research"),
    ("08-investment/01-数据源与工具", "reference"),
    ("08-investment/", "research"),
    ("06-reading-notes/AI大模型前沿研究", "insight"),
    ("06-reading-notes/晓辉博士", "lecture"),
    ("06-reading-notes/", "lecture"),
    ("01-theory/", "reference"),
    ("02-fundamentals/", "reference"),
    ("03-core-ai/", "reference"),
    ("04-tools/", "reference"),
    ("05-applications/", "reference"),
    ("07-practices/", "note"),
    ("00-系统/", "system"),
    ("导航/", "index"),
]


def detect_type_by_path(file_path: str) -> str | None:
    """根据文件路径自动推断类型"""
    from pathlib import Path
    path_str = str(Path(file_path)).replace("\\", "/")
    for subpath, ptype in PATH_RULES:
        if subpath in path_str:
            return ptype
    return None


def build_type_prompt_snippet() -> str:
    """生成 LLM type 判定 prompt 片段"""
    lines = ["类型定义（选择一个最匹配的类型）："]
    for t, info in TYPES.items():
        lines.append(f"  - `{t}` = {info['description']}（{info['detection']}）")
    lines.append("请返回一个最匹配的类型。")
    return "\n".join(lines)
