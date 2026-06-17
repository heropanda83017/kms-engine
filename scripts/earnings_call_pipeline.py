#!/usr/bin/env python3
"""
from _path_setup import WIKI_DIR
电话会议纪要分析管线 — Earnings Call Pipeline v0.1

输入：Reportify.cn 的 Transcript URL 或本地 HTML 文件
输出：结构化分析报告 → wiki 归档

流程：
  1. 获取：Scrapling/curl + Cookie → 下载页面 HTML
  2. 提取：解析 <meta description>（AI摘要）+ 元数据
  3. 分析：LLM 按行业自适应模板深度分析
  4. 输出：结构化 Markdown 报告
  5. 归档：写入 wiki 08-investment + KMS link

依赖：
  - Python 3.10+
  - 无额外包（仅标准库 + requests 可选）

用法：
  python3 earnings_call_pipeline.py \
    --url "https://reportify.cn/transcripts/1260429197986369536" \
    --cookie "report-token=xxx; i18next2=zh-CN" \
    --output /path/to/output.md

  python3 earnings_call_pipeline.py \
    --local /tmp/quanex_full.html \
    --output /tmp/ec_quanex_report.md
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from datetime import datetime
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────

# 默认 Cookie（尽量用 --cookie 参数传入，不要硬编码）
DEFAULT_COOKIE = "report-token=7ba806568a8fefe6046b0113f117d9fcf082e0c7b6cf999881233af08d1576c3; i18next2=zh-CN"

# wiki 归档目录
WIKI_EC_DIR = WIKI_DIR / "08-investment" / "06-投研分析" / "电话会议纪要"

# 行业类型自动识别关键词
INDUSTRY_KEYWORDS = {
    "制造": ["制造", "工业", "生产", "产能", "供应链", "原材料", "工厂", "库存", "物流"],
    "制药": ["制药", "临床", "FDA", "管线", "药物", "适应症", "患者", "医生", "药品", "生物"],
    "科技": ["软件", "SaaS", "云", "AI", "大模型", "芯片", "半导体", "算法", "数据"],
    "金融": ["银行", "保险", "证券", "理财", "贷款", "存款", "信贷"],
    "消费": ["零售", "消费", "品牌", "门店", "电商", "用户", "营销"],
    "能源": ["能源", "石油", "电力", "光伏", "风电", "电池", "新能源"],
}


# ── 工具函数 ─────────────────────────────────────────────────────

def fetch_page(url: str, cookie: str = DEFAULT_COOKIE) -> str:
    """用 curl 下载页面 HTML"""
    cmd = [
        "curl", "-s",
        "--cookie", cookie,
        "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "--max-time", "20",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    if result.returncode != 0:
        raise RuntimeError(f"curl 失败: {result.stderr[:200]}")
    return result.stdout


def extract_meta_descriptions(html: str) -> dict:
    """
    从 HTML 中提取结构化数据：
    - meta description: AI 分析摘要全文
    - meta keywords: 关键词
    - 页面标题: transcript 标题
    - 账户信息: 登录状态
    """
    result = {}

    # 1. meta description — Reportify AI 分析全文
    m = re.search(r'<meta name="description" content="([^"]+)"', html)
    result["meta_description"] = m.group(1) if m else ""

    # 2. 页面标题
    m = re.search(r'<title>([^<]+)</title>', html)
    result["title"] = m.group(1).replace(" - Reportify", "") if m else ""

    # 3. 提取 transcript ID
    m = re.search(r'/transcripts/(\d+)', html)
    result["transcript_id"] = m.group(1) if m else ""

    # 4. 股票代码（从嵌入数据中提取）
    symbols = set(re.findall(r'"symbol"\s*:\s*"([^"]+)"', html))
    result["symbols"] = list(symbols) if symbols else []

    # 5. 市场
    markets = set(re.findall(r'"market"\s*:\s*"([^"]+)"', html))
    result["markets"] = list(markets) if markets else []

    # 6. 登录状态
    is_login = re.search(r'"isLogin"\s*:\s*true', html)
    result["is_login"] = bool(is_login)

    return result


def extract_report_items(html: str) -> list:
    """从 transcripts 列表页提取条目"""
    items = []
    # 匹配条目块
    blocks = re.findall(
        r'ReportListItem_listItem__ulPId[^>]*>(.*?)</div>\s*</div>\s*</div>',
        html, re.DOTALL
    )
    for block in blocks:
        title_m = re.search(r'itemTitle[^>]*>([^<]+)', block)
        date_m = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', block)
        summary_m = re.search(r'summary[^>]*>([^<]+)', block)
        link_m = re.search(r'href="(/transcripts/\d+)"', block)

        if title_m:
            items.append({
                "title": title_m.group(1).strip(),
                "date": date_m.group(1) if date_m else "",
                "summary": summary_m.group(1).strip()[:200] if summary_m else "",
                "url": f"https://reportify.cn{link_m.group(1)}" if link_m else "",
            })
    return items


def guess_industry(text: str) -> str:
    """根据文本内容判断行业类型"""
    text_lower = text.lower()
    scores = {}
    for industry, keywords in INDUSTRY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            scores[industry] = score
    if scores:
        return max(scores, key=scores.get)
    return "通用"


def extract_company_name(title: str) -> str:
    """从标题中提取公司名称"""
    # 格式: "Quanex Building Products (NX) - 2026 Q2 - Earnings Call Transcript"
    m = re.search(r'^([^(]+)', title)
    return m.group(1).strip() if m else title[:30]


def extract_sections(meta_desc: str) -> dict:
    """将 meta description 按章节分割"""
    sections = {}
    # 章节标题关键词
    section_patterns = [
        ("财务数据", r'(财务数据[^。]*。?)'),
        ("经营分析", r'(经营[^。]*。?)'),
        ("业务线", r'(各条业务线[^。]*。?)'),
        ("市场数据", r'(各个市场[^。]*。?)'),
        ("战略方向", r'(公司战略[^。]*。?)'),
        ("管理层观点", r'(管理层[^。]*。?)'),
        ("其他信息", r'(其他重要[^。]*。?)'),
        ("问答环节", r'(问答环节[^。]*?|总结问答[^。]*?|问题[：:])'),
    ]

    # 简单分节：按章节关键词拆分
    section_names = [
        "财务数据和关键指标变化",
        "各条业务线",
        "各个市场",
        "公司战略",
        "管理层",
        "其他重要信息",
        "问答环节",
    ]

    current_section = "总览"
    parts = {}

    for line in meta_desc.split("- "):
        line = line.strip()
        if not line:
            continue
        # 判断是否是章节开头
        matched = False
        for sname in section_names:
            if line.startswith(sname) or sname in line[:20]:
                current_section = sname
                matched = True
                break
        if not matched:
            # 检查问题编号
            if re.match(r'问题\d*[：:]', line) or re.match(r'^\d+[.、]', line):
                current_section = "问答环节"

        if current_section not in parts:
            parts[current_section] = []
        parts[current_section].append(line)

    return parts


def call_llm_api(prompt: str, model: str = "deepseek/deepseek-chat") -> str:
    """调用 OpenRouter API 进行 LLM 分析"""
    import subprocess, json, os
    
    # 从 .bashrc_tail 获取 OpenRouter Key
    result = subprocess.run(
        'source ~/.bashrc_tail 2>/dev/null; echo "$OPENROUTER_API_KEY"',
        shell=True, capture_output=True, text=True, executable='/bin/bash'
    )
    api_key = result.stdout.strip()
    
    if not api_key or api_key == '':
        return ""

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一位资深投资分析师，精通基本面分析、行业研究和财报解读。"},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 4096,
        "temperature": 0.3,
    })
    
    result = subprocess.run([
        "curl", "-s", "https://openrouter.ai/api/v1/chat/completions",
        "-H", f"Authorization: Bearer {api_key}",
        "-H", "Content-Type: application/json",
        "-d", payload,
        "--max-time", "120",
    ], capture_output=True, text=True, timeout=130)
    
    try:
        data = json.loads(result.stdout)
        if 'choices' in data:
            return data['choices'][0]['message']['content']
        elif 'error' in data:
            return f"❌ API 错误: {data['error'].get('message', str(data))}"
        return f"❌ 未知响应: {str(data)[:200]}"
    except Exception as e:
        return f"❌ 解析失败: {e} | 响应: {result.stdout[:200]}"


def build_deep_analysis_prompt(meta_desc: str, title: str, industry: str) -> str:
    """构造深度分析提示词——使用我们自己的 8 节模板"""
    return f"""你收到一份电话会议纪要的 AI 摘要，请按照以下自定义模板重新分析并输出结构化报告。

## 输入数据

**会议标题**: {title}
**所属行业**: {industry}
**原始 AI 摘要**:
{meta_desc[:6000]}

## 输出要求

请严格按照以下 8 节模板输出，每条分析结论标注 [N] 编号引用原文数据：

### 一、核心要点（3-5 条）
提炼本季度电话会议最重要的结论，覆盖财务、战略、风险。

### 二、财务与经营分析
- 营收/利润/关键指标同比变化
- 利润率趋势及驱动因素
- 现金流与资产负债表健康状况

### 三、各业务/产品线表现（按 {industry} 行业特点）
- {industry}行业应重点关注：产能/成本/定价（制造）；管线/临床/审批（制药）；用户/增长/竞争（科技）
- 分业务板块拆解收入与利润贡献

### 四、市场与竞争环境
- 行业需求趋势
- 竞争格局变化
- 地缘政治/宏观影响

### 五、管理层战略与指引
- 未来增长战略
- 业绩指引（如有）
- 资本配置计划

### 六、风险提示
- 从纪要中提取明确列出的风险和潜在未提及的风险

### 七、QA 关键信息提取
- 分析师最关注的问题
- 管理层的回答质量
- 是否有意外信号或回避的问题

### 八、投资启示
- 本次电话会议对投资判断的核心影响
- 需要后续跟踪的关键变量

注意：行业不同，分析重点不同。{industry}行业请侧重相应的关键指标。输出用中文。"""


def run_deep_analysis(meta_desc: str, title: str, industry: str) -> str:
    """调用 DeepSeek 进行深度分析"""
    prompt = build_deep_analysis_prompt(meta_desc, title, industry)
    
    print("  🔄 调用 DeepSeek 分析中...", end="", flush=True)
    result = call_llm_api(prompt)
    print(" ✅" if not result.startswith("❌") else f" ❌")
    return result


def run_llm_analysis(meta_desc: str, title: str, industry: str, 
                     deep_mode: bool = False) -> str:
    """
    生成分析报告。
    deep_mode=False: 直接提取 Reportify 的 AI 摘要（转发模式）
    deep_mode=True:  调用 DeepSeek 按我方模板重新分析（深化模式）
    """
    company = extract_company_name(title)
    
    if deep_mode:
        # 深化模式：调 DeepSeek
        deep_result = run_deep_analysis(meta_desc, title, industry)
        
        # 同时提取 Reportify 原版摘要用于对比
        sections = extract_sections(meta_desc)
        reportify_summary = ""
        for sec_name, lines in sections.items():
            reportify_summary += f"\n### {sec_name}\n\n"
            for line in lines:
                items = re.split(r'\s+(?=\[\d+\])', line)
                for item in items:
                    item = item.strip()
                    if item:
                        if '问题[：:]' in item or item.startswith('问题'):
                            reportify_summary += f"\n**{item}**\n"
                        else:
                            reportify_summary += f"- {item}\n"
        
        report = f"""# 📞 电话会议纪要分析 | {company}

## 基本信息
- **来源**: Reportify.cn + DeepSeek 深度分析
- **行业识别**: {industry}
- **原始数据长度**: {len(meta_desc)} 字符
- **分析模式**: 深度分析（我方模板）

---

## 🧠 DeepSeek 深度分析

{deep_result}

---

## 📋 Reportify 原始摘要（对照参考）

{reportify_summary}

---

*由 Hermes Agent + DeepSeek 联合分析 | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""
    else:
        # 转发模式：直接提取 Reportify 摘要
        sections = extract_sections(meta_desc)
        report = f"""# 电话会议纪要分析 | {company}

## 基本信息
- **来源**: Reportify.cn
- **AI 分析长度**: {len(meta_desc)} 字符
- **行业识别**: {industry}

## Reportify AI 分析摘要

"""
        for sec_name, lines in sections.items():
            report += f"\n### {sec_name}\n\n"
            for line in lines:
                items = re.split(r'\s+(?=\[\d+\])', line)
                for item in items:
                    item = item.strip()
                    if item:
                        if '问题[：:]' in item or item.startswith('问题'):
                            report += f"\n**{item}**\n"
                        else:
                            report += f"- {item}\n"
        
        report += f"""
---

*分析由 Hermes Agent 自动生成，原始数据来自 Reportify.cn AI 处理。*
*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""
    return report


# ── 主流程 ───────────────────────────────────────────────────────

def pipeline(url: str = None, local_file: str = None,
             cookie: str = DEFAULT_COOKIE, output: str = None,
             deep_mode: bool = False):
    """完整的电话会议分析管线"""

    print("=" * 60)
    version = "v0.2 (深化版)" if deep_mode else "v0.1 (转发版)"
    print(f"📞 电话会议纪要分析管线 {version}")
    print("=" * 60)

    # Step 1: 获取
    print("\n[1/5] 获取页面...")
    if local_file:
        with open(local_file) as f:
            html = f.read()
        print(f"  ✅ 从本地文件加载: {local_file} ({len(html)} bytes)")
    elif url:
        print(f"  🔗 正在下载: {url}")
        html = fetch_page(url, cookie)
        print(f"  ✅ 下载完成: {len(html)} bytes")
    else:
        raise ValueError("必须提供 --url 或 --local")

    # Step 2: 提取
    print("\n[2/5] 提取结构化数据...")
    meta = extract_meta_descriptions(html)

    if not meta["meta_description"]:
        print("  ⚠️ 未找到 meta description，可能是登录失效或页面结构变化")
        # 回退：尝试从 HTML 正文提取

    print(f"  📌 标题: {meta['title'][:80]}")
    print(f"  📊 AI 摘要: {len(meta['meta_description'])} 字符")
    print(f"  💹 股票: {', '.join(meta['symbols']) if meta['symbols'] else 'N/A'}")
    print(f"  🔑 登录: {'✅' if meta['is_login'] else '❌'}")

    # Step 3: 行业识别
    print("\n[3/5] 行业识别...")
    industry = guess_industry(meta["meta_description"] + " " + meta["title"])
    company = extract_company_name(meta["title"])
    print(f"  🏭 行业: {industry}")
    print(f"  🏢 公司: {company}")

    # Step 4: 分析
    print("\n[4/5] 生成分析报告...")
    report = run_llm_analysis(
        meta["meta_description"], meta["title"], industry,
        deep_mode=deep_mode
    )
    print(f"  ✅ 报告生成: {len(report)} 字符")

    # Step 5: 输出
    print("\n[5/5] 输出报告...")
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        print(f"  ✅ 已保存: {output_path}")
    else:
        print("\n" + report[:2000])

    # 尝试归档到 wiki
    date_str = datetime.now().strftime("%Y%m%d")
    try:
        wiki_path = save_to_wiki(report, company.replace(" ", "_"), date_str)
        print(f"  📦 wiki 路径: {wiki_path.relative_to(Path('/mnt/e/AIGC-KB'))}")
    except Exception as e:
        print(f"  ⚠️ wiki 归档失败: {e}")

    print("\n" + "=" * 60)
    print("✅ 管线执行完毕")
    print("=" * 60)

    return report


# ── CLI 入口 ─────────────────────────────────────────────────────



def search_transcript(stock_code: str) -> dict:
    """自动搜索个股的电话会议纪要，返回 {url, title, source}"""
    stock_code = stock_code.strip()
    
    # 判断市场：纯6位数字→A股，其他→美股
    is_a_share = bool(re.match(r'^\d{6}$', stock_code))
    
    if is_a_share:
        # A股：搜 投资者关系活动记录表
        query = f"{stock_code} 投资者关系活动记录表 中财网"
        print(f"  🔍 搜索A股 {stock_code} 投资者关系活动记录表...")
        
        # 用 subprocess 调 web_search (Hermes 工具不可在脚本内直接调用)
        # 改用已知可靠来源: 中财网 URL 模式
        # 先用 curl 试试中财网的标准路径
        import urllib.request
        try:
            url = f"https://www.cfi.net.cn/search.aspx?k={stock_code}&t=0"
            print(f"  🔗 尝试: {url}")
        except Exception:
            pass
        
        return {"url": query, "source": "web_search", "is_a_share": True}
    else:
        # 美股：搜 Seeking Alpha
        return {
            "url": f"https://seekingalpha.com/symbol/{stock_code}/earnings/transcripts",
            "source": "seekingalpha",
            "is_a_share": False
        }


def scrape_transcript_from_url(url: str) -> str:
    """从 URL 爬取电话会议纪要全文"""
    import urllib.request
    
    print(f"  🔗 爬取: {url}")
    
    # 用 curl 下载
    result = subprocess.run(
        ["curl", "-s", "-L", url,
         "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
         "--max-time", "20"],
        capture_output=True, text=True, timeout=25
    )
    
    if result.returncode != 0:
        return f"❌ 下载失败: {result.stderr[:200]}"
    
    html = result.stdout
    
    # 清理 HTML → 纯文本
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'\s*\n\s*', '\n', text)
    
    lines = [l.strip() for l in text.split('\n') if l.strip() and len(l.strip()) > 8]
    clean = '\n'.join(lines)
    
    return clean[:10000]  # 截断到10000字符


def analyze_raw_text(raw_text: str, stock_code: str, title: str = "") -> str:
    """对原始纪要文本进行 DeepSeek 深度分析"""
    prompt = f"""你是一位资深投资分析师。以下是{stock_code}的投资者交流会/电话会议纪要。

## 原始记录

{raw_text[:5000]}

## 要求

请按以下结构输出分析报告：

### 一、核心要点（3条）
### 二、关键信息提炼
### 三、积极信号与风险警示
### 四、投资启示

每条结论引用原文依据。输出用中文。"""

    # 获取 OpenRouter Key
    result = subprocess.run(
        'source ~/.bashrc_tail 2>/dev/null; echo "$OPENROUTER_API_KEY"',
        shell=True, capture_output=True, text=True, executable='/bin/bash'
    )
    api_key = result.stdout.strip()
    if not api_key:
        return "❌ 无法获取 API Key"
    
    payload = json.dumps({
        "model": "deepseek/deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一位资深投资分析师，精通A股/美股基本面分析。"},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 4096,
        "temperature": 0.3,
    })
    
    result = subprocess.run(
        ["curl", "-s", "https://openrouter.ai/api/v1/chat/completions",
         "-H", f"Authorization: Bearer {api_key}",
         "-H", "Content-Type: application/json",
         "-d", payload, "--max-time", "120"],
        capture_output=True, text=True, timeout=130
    )
    
    try:
        data = json.loads(result.stdout)
        if 'choices' in data:
            return data['choices'][0]['message']['content']
        return f"❌ API错误: {str(data)[:200]}"
    except Exception as e:
        return f"❌ 解析失败: {e}"



def save_to_wiki(report: str, company: str, date_str: str):
    """保存分析报告到 wiki"""
    WIKI_EC_DIR.mkdir(parents=True, exist_ok=True)

    filename = f"{date_str}-{company}-电话会议纪要分析.md"
    filepath = WIKI_EC_DIR / filename

    filepath.write_text(report, encoding="utf-8")
    print(f"  ✅ 已归档: {filepath}")
    return filepath




def stock_flow(stock_code: str, output: str = None):
    """自动搜索+爬取+分析个股的电话会议纪要"""
    
    # Step 1: 搜索
    print("\n[1/4] 搜索会议纪要...")
    info = search_transcript(stock_code)
    print(f"  📌 搜索策略: {info}")
    
    # Step 2: 用 web_search 找真实 URL (通过 Hermes 环境)
    print("\n[2/4] 正在搜索可用的纪要链接...")
    print(f"  💡 请使用: python3 scripts/earnings_call_pipeline.py --url <找到的URL> --deep")
    print(f"  💡 A股建议来源: 中财网(www.cfi.net.cn) 搜索 {stock_code}")
    print(f"  💡 美股建议来源: seekingalpha.com/symbol/{stock_code}/earnings/transcripts")
    print()
    
    # 对于 A 股，直接尝试从中财网找 (已知模式)
    if re.match(r'^\d{6}$', stock_code):
        # 尝试搜索中财网
        print("  🔍 尝试从中财网获取...")
        search_url = f"https://www.cfi.net.cn/search.aspx?k={stock_code}&t=0"
        print(f"  🔗 {search_url}")
    
    print("\n[3/4] 请在找到 URL 后用 --url 参数再次运行")
    print("\n[4/4] 或者直接提供 URL 给我，我帮你跑完")



def main():
    parser = argparse.ArgumentParser(
        description="📞 电话会议纪要分析管线")
    parser.add_argument("--url", help="Reportify.cn transcript URL")
    parser.add_argument("--local", help="本地 HTML 文件路径")
    parser.add_argument("--cookie", default=DEFAULT_COOKIE, help="Cookie 字符串")
    parser.add_argument("--output", help="输出文件路径")
    parser.add_argument("--deep", action="store_true", help="深化模式：调用 DeepSeek 按我方模板重新分析")
    # parser.add_argument("--stock", help="股票代码（如 000725 / NVDA），自动搜索+分析")
    args = parser.parse_args()

    if not args.url and not args.local:
        parser.print_help()
        print("\n❌ 请提供 --url 或 --local")
        sys.exit(1)

    if args.stock:
        print(f"\n📞 自动搜索+分析 {args.stock}...\n")
        stock_flow(args.stock, args.output)
    else:
        pipeline(
            url=args.url,
            local_file=args.local,
            cookie=args.cookie,
            output=args.output,
            deep_mode=args.deep,
        )


if __name__ == "__main__":
    main()
