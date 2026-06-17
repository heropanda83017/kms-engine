#!/usr/bin/env python3
"""
KMS Intent Router — 自然语言 → 意图 → 技能 → 执行

让用户可以用自然语言调用 KMS 命令，无需记忆精确 CLI 参数。

用法:
    python3 kms_router.py "查资金因子"
    python3 kms_router.py "看看wiki健康"
    python3 kms_router.py "不知道的命令"  # → 显示帮助
"""

import re
import sys
from typing import Optional


class IntentRouter:
    """意图路由：自然语言 → (意图, 技能, 参数)"""

    def __init__(self):
        # 意图映射表：[(关键词列表, 意图, 技能, 参数)]
        # ⚠️ 长关键词在前，避免"检查笔记"被"查"误匹配
        self._intents = [
            # 写入门禁（长关键词优先）
            (["检查笔记", "笔记检查", "gate", "门禁"], "gate", "gate", None),
            # 并行健康检查（长关键词优先，放在常规健康检查之前）
            (["并行健康", "并行检查"], "health", "health", "--parallel"),
            # ReAct Agent（长关键词优先，放在搜索之前）
            (["智能路由", "智能验证", "智能流水线", "智能富化", "智能审查",
              "react router", "react validator", "react pipeline"], "react", "react", "router"),
            # 健康检查（不加参数 = 全量检查）
            (["wiki健康", "系统健康", "系统状态", "健康检查", "体检",
              "健康", "检查"], "health", "health", None),
            # 搜索
            (["查", "搜", "找", "搜索", "查找", "检索", "查询"], "search", "search", "--fusion"),
            # 链接更新
            (["更新链接", "跑链接", "链接", "link"], "link", "link", None),
            # 知识图谱
            (["kg", "图谱", "实体", "知识图谱"], "kg", "kg search", None),
            # 融合
            (["融合", "合并", "fuse", "smart-fuse"], "fuse", "smart-fuse", None),
            # 状态
            (["状态", "统计", "status", "概况"], "status", "status", None),
            # 备份
            (["备份", "backup"], "backup", "backup", None),
            # 索引
            (["索引", "index", "重建索引"], "index", "index build", None),
            # 打分
            (["打分", "评分", "score"], "score", "score", None),
            # 验证笔记
            (["验证笔记", "笔记验证", "validate"], "validate", "validate", None),
            # 使用分析
            (["使用分析", "使用报告", "analytics", "分析报告"], "analytics", "analytics", None),
            # ReAct Agent
            (["react", "ReAct", "智能路由", "智能验证", "智能流水线"], "react", "react", "router"),
        ]

    def resolve(self, text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """解析自然语言 → (意图, 技能, 参数)

        集成用户画像：画像关键词辅助意图匹配。
        """
        if not text:
            return None, None, None

        text_lower = text.lower().strip()

        # 加载画像关键词辅助匹配
        portrait_keywords = []
        try:
            from kms_session import load_portrait
            portrait = load_portrait()
            if portrait:
                interests = portrait.get("interests", [])
                for interest in interests:
                    portrait_keywords.extend(interest.lower().split())
        except Exception:
            pass

        for keywords, intent, skill, default_args in self._intents:
            for kw in keywords:
                if kw in text_lower:
                    # 提取搜索关键词（搜索意图特有）
                    if intent == "search":
                        # 去掉搜索关键词前缀，剩下的就是搜索词
                        query = text_lower
                        for prefix in ["查", "搜", "找", "搜索", "查找", "检索", "查询"]:
                            query = query.replace(prefix, "", 1) if query.startswith(prefix) else query
                        query = query.strip()
                        args = query if query else default_args
                    elif intent == "react":
                        # ReAct: 从文本中提取 agent 类型
                        if "验证" in text or "validate" in text:
                            agent_type = "validator"
                        elif "流水线" in text or "pipeline" in text:
                            agent_type = "pipeline"
                        elif "富化" in text or "enrich" in text:
                            agent_type = "enricher"
                        elif "审查" in text or "review" in text or "打分" in text:
                            agent_type = "reviewer"
                        else:
                            agent_type = "router"
                        args = f"{agent_type} {text}"
                    else:
                        args = default_args
                    return intent, skill, args

        return None, None, None

    def help(self) -> str:
        """显示可用命令帮助"""
        lines = [
            "📚 KMS 意图路由 — 直接说自然语言：",
            "",
            "| 你说 | 执行命令 |",
            "|:-----|:---------|",
        ]
        for keywords, intent, skill, _ in self._intents:
            kw_str = " / ".join(keywords[:3])
            lines.append(f"| `{kw_str}...` | `kms {skill}` |")
        lines.extend([
            "",
            "示例:",
            "  kms \"查资金因子\"      → kms search --fusion 资金因子",
            "  kms \"看看wiki健康\"    → kms health（全量检查）",
            "  kms \"更新链接\"        → kms link",
            "  kms \"KG 资金因子\"     → kms kg search 资金因子",
            "",
            "💡 传统 CLI 仍然可用：kms search xxx / kms link / kms status",
        ])
        return "\n".join(lines)


def cli():
    """命令行入口"""
    if len(sys.argv) < 2:
        print(IntentRouter().help())
        return

    text = " ".join(sys.argv[1:])
    router = IntentRouter()
    intent, skill, args = router.resolve(text)

    if intent:
        if args:
            print(f"→ kms {skill} {args}")
        else:
            print(f"→ kms {skill}")
    else:
        print(router.help())


if __name__ == "__main__":
    cli()
