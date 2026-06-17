#!/usr/bin/env python3
"""group_chat.py — 多 Agent 对话式协作 (GroupChat)

借鉴 AutoGen (Microsoft, 2024) 的 GroupChat 模式。
让多个 agent 通过对话协作，来回讨论、互相反驳、迭代优化。

用法:
  from group_chat import GroupChat

  chat = GroupChat("中际旭创是否值得买入", agents=["bull", "bear", "judge"])
  summary = chat.run()
"""

import json, sys, uuid as _uuid
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_template import run_template, list_templates
from agent_protocol import MessageBus, AgentMessage, TraceContext


# ── 数据类 ────────────────────────────────────────────

@dataclass
class ChatMessage:
    """一轮对话中的一条消息"""
    speaker: str
    content: str
    round_num: int
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


# ── GroupChat ─────────────────────────────────────────

class GroupChat:
    """多 agent 对话式协作"""

    def __init__(self, topic: str, agents: list[str],
                 max_rounds: int = 3, context: str = ""):
        self.topic = topic
        self.agents = agents
        self.max_rounds = max_rounds
        self.context = context
        self.history: list[ChatMessage] = []
        self._trace_id = TraceContext.new()

    def _build_context(self) -> str:
        """构建含历史对话的 context"""
        lines = [f"## 研究主题\n{self.topic}\n"]
        if self.context:
            lines.append(f"## 额外上下文\n{self.context}\n")
        if self.history:
            lines.append("## 历史对话\n")
            for msg in self.history[-6:]:  # 只取最近 6 条
                lines.append(f"**{msg.speaker}** (第{msg.round_num}轮):")
                content_preview = msg.content[:300] if msg.content else "(无内容)"
                lines.append(f"{content_preview}\n")
        return "\n".join(lines)

    def round(self) -> list[ChatMessage]:
        """执行一轮对话：每个 agent 依次发言"""
        round_msgs = []
        for agent_name in self.agents:
            context = self._build_context()
            try:
                session = run_template(
                    agent_name,
                    goal=f"参与关于「{self.topic}」的讨论，基于历史对话发表你的观点",
                    context=context,
                )
                content = ""
                if hasattr(session, "result") and session.result:
                    content = str(session.result)[:1000]
                elif hasattr(session, "status"):
                    content = f"[{session.status}]"
            except Exception as e:
                content = f"[发言失败: {e}]"

            msg = ChatMessage(
                speaker=agent_name,
                content=content,
                round_num=len(self.history) + 1,
            )
            self.history.append(msg)
            round_msgs.append(msg)

            # 发布到消息总线
            MessageBus.publish(AgentMessage(
                trace_id=self._trace_id,
                sender=agent_name,
                receiver="groupchat",
                message_type="response",
                payload={"topic": self.topic, "content": content[:200]},
                status="success" if content and not content.startswith("[") else "failed",
            ))

        return round_msgs

    def run(self, verbose: bool = True) -> str:
        """完整对话流程"""
        if verbose:
            agents_str = ", ".join(self.agents)
            print(f"\n{'='*55}")
            print(f"  💬 GroupChat: {self.topic}")
            print(f"  参与者: {agents_str} | {self.max_rounds} 轮")
            print(f"{'='*55}\n")

        for r in range(self.max_rounds):
            if verbose:
                print(f"  📦 第 {r+1} 轮\n")

            round_msgs = self.round()

            if verbose:
                for msg in round_msgs:
                    preview = msg.content[:80].replace("\n", " ")
                    print(f"    [{msg.speaker}] {preview}...")
                print()

        summary = self._summarize()

        if verbose:
            print(f"{'='*55}")
            print(f"  ✅ 对话完成 — {len(self.history)} 条消息")
            print(f"{'='*55}")

        return summary

    def _summarize(self) -> str:
        """生成对话摘要"""
        lines = [f"# GroupChat 摘要: {self.topic}", "",
                 f"参与者: {', '.join(self.agents)}", f"总轮数: {self.max_rounds}",
                 f"总消息: {len(self.history)}", ""]

        for msg in self.history:
            lines.append(f"---\n### 第{msg.round_num}轮 - {msg.speaker}\n")
            lines.append(msg.content[:500] if msg.content else "(无内容)")
            lines.append("")

        return "\n".join(lines)

    def get_transcript(self) -> list[dict]:
        """获取对话记录（用于外部调用）"""
        return [
            {"speaker": m.speaker, "content": m.content,
             "round": m.round_num, "time": m.timestamp}
            for m in self.history
        ]


# ── 预置辩论模板 ──────────────────────────────────────

def create_debate(topic: str, context: str = "") -> GroupChat:
    """创建多空辩论"""
    return GroupChat(
        topic=topic,
        agents=["bull", "bear", "judge"],
        max_rounds=3,
        context=context,
    )


def create_review(topic: str, context: str = "") -> GroupChat:
    """创建评审讨论"""
    return GroupChat(
        topic=topic,
        agents=["code-reviewer", "analyst", "risk"],
        max_rounds=2,
        context=context,
    )


# ── CLI ───────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="GroupChat 多 Agent 对话")
    sub = parser.add_subparsers(dest="cmd")

    p_debate = sub.add_parser("debate", help="多空辩论")
    p_debate.add_argument("topic", help="辩论主题")
    p_debate.add_argument("--context", default="")

    p_review = sub.add_parser("review", help="评审讨论")
    p_review.add_argument("topic", help="评审主题")
    p_review.add_argument("--context", default="")

    p_custom = sub.add_parser("chat", help="自定义对话")
    p_custom.add_argument("topic")
    p_custom.add_argument("--agents", nargs="+", required=True)
    p_custom.add_argument("--rounds", type=int, default=3)

    args = parser.parse_args()

    if args.cmd == "debate":
        chat = create_debate(args.topic, args.context)
        chat.run()

    elif args.cmd == "review":
        chat = create_review(args.topic, args.context)
        chat.run()

    elif args.cmd == "chat":
        chat = GroupChat(args.topic, args.agents, args.rounds)
        chat.run()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
