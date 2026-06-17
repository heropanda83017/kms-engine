#!/usr/bin/env python3
"""agent_protocol.py — Agent 通信协议 (A2A 轻量版)

借鉴 Google A2A (Agent2Agent) 和 Anthropic MCP 的标准化通信思想。
提供：消息定义、消息总线、能力注册、链路追踪。

用法:
  from agent_protocol import MessageBus, AgentMessage, CapabilityRegistry

  # 发布消息
  MessageBus.publish(AgentMessage(sender="macro", receiver="screening",
                    message_type="request", payload={"goal": "分析股票"}))

  # 订阅消息
  MessageBus.subscribe("screening", lambda msg: print(msg))

  # 链路追踪
  chain = MessageBus.get_chain(trace_id="xxx")
"""

import json, uuid as _uuid, logging, sys
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable


# ── 消息定义 ──────────────────────────────────────────

@dataclass
class AgentMessage:
    """Agent 间通信消息（借鉴 A2A 规范）"""
    message_id: str = ""
    trace_id: str = ""
    sender: str = ""
    receiver: str = ""
    message_type: str = "request"  # request/response/status/error/capability
    payload: dict = field(default_factory=dict)
    timestamp: str = ""
    status: str = ""

    def __post_init__(self):
        if not self.message_id:
            self.message_id = str(_uuid.uuid4())[:12]
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


# ── 消息总线 ──────────────────────────────────────────

class MessageBus:
    """轻量消息总线（单进程内，线程安全）"""

    _messages: list[AgentMessage] = []
    _subscribers: dict[str, list[Callable]] = {}
    _trace_chains: dict[str, list] = {}

    @classmethod
    def publish(cls, message: AgentMessage):
        """发布消息"""
        cls._messages.append(message)

        # 记录链路
        trace_id = message.trace_id or message.message_id
        if trace_id not in cls._trace_chains:
            cls._trace_chains[trace_id] = []
        cls._trace_chains[trace_id].append({
            "message_id": message.message_id,
            "from": message.sender,
            "to": message.receiver,
            "type": message.message_type,
            "status": message.status,
            "time": message.timestamp,
        })

        # 通知订阅者
        patterns = ["*", message.receiver, message.message_type]
        notified = set()
        for pattern in patterns:
            if pattern in cls._subscribers:
                for cb in cls._subscribers[pattern]:
                    cb_id = id(cb)
                    if cb_id not in notified:
                        try:
                            cb(message)
                            notified.add(cb_id)
                        except Exception as e:
                            logging.warning(f"消息订阅者异常: {e}")

    @classmethod
    def subscribe(cls, pattern: str, callback: Callable):
        """订阅消息（pattern = receiver 名 或 "*" 或 message_type）"""
        if pattern not in cls._subscribers:
            cls._subscribers[pattern] = []
        cls._subscribers[pattern].append(callback)

    @classmethod
    def unsubscribe(cls, pattern: str, callback: Callable = None):
        """取消订阅"""
        if pattern in cls._subscribers:
            if callback:
                cls._subscribers[pattern] = [
                    cb for cb in cls._subscribers[pattern] if cb != callback
                ]
            else:
                del cls._subscribers[pattern]

    @classmethod
    def get_messages(cls, trace_id: str = "", limit: int = 50) -> list:
        """按 trace_id 查询消息"""
        if not trace_id:
            return cls._messages[-limit:]
        return [m for m in cls._messages if m.trace_id == trace_id][-limit:]

    @classmethod
    def get_chain(cls, trace_id: str) -> list:
        """获取完整调用链"""
        return cls._trace_chains.get(trace_id, [])

    @classmethod
    def clear(cls):
        """清空所有消息（测试用）"""
        cls._messages.clear()
        cls._subscribers.clear()
        cls._trace_chains.clear()

    @classmethod
    def stats(cls) -> dict:
        """消息统计"""
        return {
            "total_messages": len(cls._messages),
            "active_subscribers": sum(len(v) for v in cls._subscribers.values()),
            "trace_chains": len(cls._trace_chains),
        }


# ── 能力注册 ──────────────────────────────────────────

@dataclass
class AgentCapability:
    """Agent 能力声明"""
    template_name: str
    description: str
    input_schema: dict = field(default_factory=lambda: {"goal": "str", "context": "str"})
    output_schema: dict = field(default_factory=lambda: {"result": "str"})
    toolsets: list = field(default_factory=list)
    model: str = ""


class CapabilityRegistry:
    """能力注册表"""

    _capabilities: dict[str, AgentCapability] = {}

    @classmethod
    def register(cls, name: str, cap: AgentCapability):
        """注册能力"""
        cls._capabilities[name] = cap
        # 发布能力声明消息
        MessageBus.publish(AgentMessage(
            sender=name,
            receiver="broadcast",
            message_type="capability",
            payload={"description": cap.description, "toolsets": cap.toolsets},
        ))

    @classmethod
    def discover(cls, query: str) -> list:
        """能力发现：根据描述搜索能处理该任务的 agent"""
        results = []
        q = query.lower()
        for name, cap in cls._capabilities.items():
            if q in cap.description.lower():
                results.append(cap)
        return results

    @classmethod
    def get(cls, name: str) -> Optional[AgentCapability]:
        """获取指定 agent 的能力"""
        return cls._capabilities.get(name)

    @classmethod
    def list_all(cls) -> list:
        """列出所有已注册能力"""
        return list(cls._capabilities.values())

    @classmethod
    def auto_register(cls):
        """从 agent_template 自动注册所有能力"""
        try:
            from agent_template import list_templates
            for t in list_templates():
                cap = AgentCapability(
                    template_name=t["name"],
                    description=t["description"],
                    toolsets=t["toolsets"],
                    model=t.get("model", ""),
                )
                cls.register(t["name"], cap)
            logging.info(f"已自动注册 {len(cls._capabilities)} 个 agent 能力")
        except ImportError:
            logging.warning("agent_template 不可用，跳过自动注册")

    @classmethod
    def clear(cls):
        """清空注册表（测试用）"""
        cls._capabilities.clear()


# ── 链路追踪辅助 ──────────────────────────────────────

class TraceContext:
    """链路追踪上下文（用于在 DAG 执行中传递 trace_id）"""

    _current_trace_id: str = ""

    @classmethod
    def new(cls) -> str:
        """创建新的追踪 ID"""
        cls._current_trace_id = str(_uuid.uuid4())[:12]
        return cls._current_trace_id

    @classmethod
    def current(cls) -> str:
        """获取当前追踪 ID"""
        if not cls._current_trace_id:
            cls._current_trace_id = str(_uuid.uuid4())[:12]
        return cls._current_trace_id

    @classmethod
    def set(cls, trace_id: str):
        """设置追踪 ID"""
        cls._current_trace_id = trace_id

    @classmethod
    def clear(cls):
        """清空"""
        cls._current_trace_id = ""


# ── 测试 ──────────────────────────────────────────────

def _test():
    """测试消息总线 + 能力注册 + 链路追踪"""
    print("=== 测试 1: 消息发布/订阅 ===")
    received = []

    def on_message(msg):
        received.append(msg)

    MessageBus.subscribe("test_agent", on_message)
    MessageBus.publish(AgentMessage(
        sender="macro", receiver="test_agent",
        message_type="request", payload={"goal": "test"},
    ))
    assert len(received) == 1
    assert received[0].sender == "macro"
    print("  ✅ 消息发布/订阅正常")

    MessageBus.clear()
    received.clear()

    print("\n=== 测试 2: 链路追踪 ===")
    trace_id = "trace_test_001"
    MessageBus.publish(AgentMessage(
        trace_id=trace_id, sender="macro", receiver="industry",
        message_type="request", payload={"goal": "分析行业"},
    ))
    MessageBus.publish(AgentMessage(
        trace_id=trace_id, sender="industry", receiver="macro",
        message_type="response", payload={"result": "done"},
        status="success",
    ))
    chain = MessageBus.get_chain(trace_id)
    assert len(chain) == 2
    assert chain[0]["from"] == "macro"
    assert chain[1]["from"] == "industry"
    print(f"  ✅ 链路追踪正常 ({len(chain)} 步)")

    MessageBus.clear()

    print("\n=== 测试 3: 能力注册/发现 ===")
    CapabilityRegistry.register("macro", AgentCapability(
        template_name="macro",
        description="宏观环境评估 — 大盘指数 + 板块强弱 + 周期框架",
        toolsets=["web", "terminal"],
    ))
    CapabilityRegistry.register("industry", AgentCapability(
        template_name="industry",
        description="行业扫描 — 因子板块排名 + 行业板块 + 舆情",
        toolsets=["web", "terminal"],
    ))
    results = CapabilityRegistry.discover("宏观")
    assert len(results) >= 1
    assert results[0].template_name == "macro"
    print("  ✅ 能力发现正常")

    CapabilityRegistry.clear()

    print("\n=== 测试 4: 自动注册 ===")
    CapabilityRegistry.auto_register()
    count = len(CapabilityRegistry.list_all())
    print(f"  ✅ 自动注册: {count} 个 agent 能力")

    CapabilityRegistry.clear()

    print("\n=== 测试 5: 消息统计 ===")
    MessageBus.clear()
    MessageBus.publish(AgentMessage(sender="a", receiver="b"))
    MessageBus.publish(AgentMessage(sender="b", receiver="c"))
    stats = MessageBus.stats()
    assert stats["total_messages"] == 2, f"预期2条，实际{stats['total_messages']}"
    print(f"  ✅ 消息统计: {stats['total_messages']} 条")

    MessageBus.clear()

    print(f"\n{'='*40}")
    print("🎉 全部测试通过!")
    print(f"{'='*40}")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
    else:
        print(__doc__)
