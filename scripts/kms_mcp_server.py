#!/usr/bin/env python3
"""
KMS MCP Server — 将 KMS 知识管理系统暴露为 MCP 工具
供 Hermes Agent 通过 stdio MCP 直接搜索/链接/融合 wiki 笔记。

协议: JSON-RPC 2.0 over stdio (MCP 2024-11-05)
工具:
  - kms_search <query> [type_filter]    — wiki 全文检索
  - kms_status                          — KMS 系统状态
  - kms_link                            — 更新 wiki 双向链接
  - kms_smart_fuse <note_path>          — 为笔记找融合候选
  - kms_score <target> [--batch] [--dry-run] — AI 0-10 打分门禁
  - kms_enrich <target> [dry_run] [force] — 背景富化(需score≥6)
  - kms_resolve <query> [top_k] — 三层Skill解析(从查询匹配L2技能)

安装: 在 ~/.hermes/config.yaml profile 下添加:
  mcp_servers:
    kms:
      transport: stdio
      command: python3
      args:
        - /path/to/kms_mcp_server.py
      enabled: true

源自: GBrain MCP 暴露模式 (garrytan/gbrain)
"""

import sys
import json
import subprocess
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [kms-mcp] %(message)s",
)
logger = logging.getLogger("kms-mcp")

# ─── 路径配置 ─────────────────────────────────────────────
KMS_ENGINE = Path(__file__).resolve().parent.parent  # kms-engine/
SCRIPTS_DIR = KMS_ENGINE / "scripts"
KMS_CLI = SCRIPTS_DIR / "kms.py"
SMART_FUSE = SCRIPTS_DIR / "smart_fuse.py"
ENRICH_SCRIPT = SCRIPTS_DIR / "enrich.py"

# ─── 工具定义 ─────────────────────────────────────────────
TOOLS = [
    {
        "name": "kms_search",
        "description": "wiki 全文检索：按关键词搜索知识库。可选 --rrf 启用混合搜索(关键词+语义)，可选 --mode 指定搜索模式(rrf/fts5/vector)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词",
                },
                "type_filter": {
                    "type": "string",
                    "description": "可选的笔记类型过滤 (e.g. research/lecture/reference)",
                },
                "rrf": {
                    "type": "boolean",
                    "description": "设为 true 启用 RRF 混合搜索 (关键词+语义)，须先运行 kms index build",
                    "default": False,
                },
                "mode": {
                    "type": "string",
                    "enum": ["rrf", "fts5", "vector"],
                    "description": "搜索模式：rrf=混合搜索, fts5=纯关键词, vector=纯语义 (默认关键词搜索)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "kms_status",
        "description": "KMS 系统状态：wiki 文件数、脚本数、注册表状态",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "kms_link",
        "description": "更新 wiki 双向链接，保持所有笔记间链接一致性",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "kms_smart_fuse",
        "description": "智能融合：为新笔记查找最佳的已存在融合目标",
        "inputSchema": {
            "type": "object",
            "properties": {
                "note_path": {
                    "type": "string",
                    "description": "新笔记的绝对路径",
                },
            },
            "required": ["note_path"],
        },
    },
    {
        "name": "kms_score",
        "description": "AI 打分：对笔记进行 0-10 质量评分并写入 frontmatter",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "笔记路径 或 目录路径(--batch)",
                },
                "batch": {
                    "type": "boolean",
                    "description": "设为 true 时批量扫描整个目录",
                    "default": False,
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "设为 true 时仅预览结果，不写入",
                    "default": False,
                },
            },
            "required": ["target"],
        },
    },
    {
        "name": "kms_enrich",
        "description": "背景富化：为已打分的笔记自动搜索补充背景信息（需要 score ≥ 6）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "笔记文件路径",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "设为 true 时仅预览搜索关键词，不写入",
                    "default": False,
                },
                "force": {
                    "type": "boolean",
                    "description": "设为 true 时跳过 score ≥ 6 检查",
                    "default": False,
                },
            },
            "required": ["target"],
        },
    },
    {
        "name": "kms_resolve",
        "description": "三层Skill架构解析：从用户查询匹配L2 Resolver-routed技能。返回技能名+匹配度+简介，帮助决策在特定任务中该按需加载哪些技能。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用户查询文本，如 '帮我研究一下中际旭创的估值'",
                },
                "top_k": {
                    "type": "number",
                    "description": "返回前N个匹配 (默认5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
]


def _run_script(script_path: Path, args: list[str] | None = None,
                timeout: int = 60) -> tuple[str, int]:
    """运行 KMS 脚本并返回输出"""
    cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = r.stdout[-3000:] if r.stdout else ""
        if r.stderr:
            output += f"\n⚠️ stderr:\n{r.stderr[:1000]}"
        return output, r.returncode
    except subprocess.TimeoutExpired:
        return "❌ 脚本执行超时", 1
    except FileNotFoundError:
        return f"❌ 脚本未找到: {script_path}", 1


# ─── MCP 请求处理 ──────────────────────────────────────────
def handle_request(req: dict) -> dict | None:
    """处理单条 MCP JSON-RPC 请求"""
    method = req.get("method", "")
    params = req.get("params", {})
    req_id = req.get("id")

    # Step 1: initialize
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "kms-mcp-server",
                    "version": "1.0.0",
                },
            },
        }

    # Step 2: notification (no response)
    if method == "notifications/initialized":
        return None

    # Step 3: tools/list
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    # Step 4: tools/call
    if method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {})

        result_content = execute_tool(tool_name, args)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": result_content,
                    }
                ],
            },
        }

    # Unknown method
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"未知方法: {method}"},
    }


def execute_tool(tool_name: str, args: dict) -> str:
    """执行 MCP 工具"""
    if tool_name == "kms_search":
        query = args.get("query", "")
        type_filter = args.get("type_filter", "")
        use_rrf = args.get("rrf", False)
        mode = args.get("mode", "")
        cli_args = ["search", query]
        if type_filter:
            cli_args.extend(["--type", type_filter])
        if use_rrf:
            cli_args.append("--rrf")
        if mode:
            cli_args.extend(["--mode", mode])
        output, rc = _run_script(KMS_CLI, cli_args)
        return f"## kms_search: {query}\n{output}"

    elif tool_name == "kms_status":
        output, rc = _run_script(KMS_CLI, ["status"])
        return output

    elif tool_name == "kms_link":
        output, rc = _run_script(KMS_CLI, ["link"])
        return output

    elif tool_name == "kms_smart_fuse":
        note_path = args.get("note_path", "")
        if not note_path:
            return "❌ 缺少参数: note_path (笔记路径)"
        if not Path(note_path).exists():
            return f"❌ 笔记路径不存在: {note_path}"
        output, rc = _run_script(SMART_FUSE, [note_path])
        return output

    elif tool_name == "kms_score":
        target = args.get("target", "")
        batch = args.get("batch", False)
        dry_run = args.get("dry_run", False)
        scorer = SCRIPTS_DIR / "quality_gate_scorer.py"
        qgs_args = [target]
        if batch:
            qgs_args.append("--batch")
        if dry_run:
            qgs_args.append("--dry-run")
        output, rc = _run_script(scorer, qgs_args, timeout=120)
        return output

    elif tool_name == "kms_enrich":
        target = args.get("target", "")
        dry_run = args.get("dry_run", False)
        force = args.get("force", False)
        enrich_args = [target]
        if dry_run:
            enrich_args.append("--dry-run")
        if force:
            enrich_args.append("--force")
        output, rc = _run_script(ENRICH_SCRIPT, enrich_args, timeout=90)
        return output

    elif tool_name == "kms_resolve":
        query = args.get("query", "")
        top_k = str(args.get("top_k", 5))
        if not query:
            return "❌ 缺少参数: query"
        tl = SCRIPTS_DIR / "three_layer.py"
        output, rc = _run_script(tl, ["--resolve", query, "--top-k", top_k])
        return output

    else:
        return f"❌ 未知工具: {tool_name}"


def main():
    """MCP stdio 主循环"""
    logger.info("KMS MCP Server 启动")
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                resp = handle_request(req)
                if resp is not None:
                    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
            except json.JSONDecodeError:
                logger.warning("非 JSON 行, 忽略: %s", line[:80])
    except KeyboardInterrupt:
        logger.info("KMS MCP Server 终止")
    except BrokenPipeError:
        logger.info("客户端断开, KMS MCP Server 终止")


if __name__ == "__main__":
    main()
