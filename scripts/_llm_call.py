"""_llm_call.py — 共享 LLM 调用工具
"""
import json, subprocess

def _get_api_key() -> str:
    result = subprocess.run(
        'source ~/.bashrc_tail 2>/dev/null; echo "$OPENROUTER_API_KEY"',
        shell=True, capture_output=True, text=True, executable='/bin/bash'
    )
    return result.stdout.strip()

def llm_analyze(prompt: str, system_prompt: str = "",
                model: str = "deepseek/deepseek-chat",
                max_tokens: int = 2000,
                temperature: float = 0.3) -> str:
    api_key = _get_api_key()
    if not api_key:
        return ""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    })
    auth = f"Authorization: Bearer {api_key}"
    result = subprocess.run([
        "curl", "-s", "https://openrouter.ai/api/v1/chat/completions",
        "-H", auth,
        "-H", "Content-Type: application/json",
        "-d", payload,
        "--max-time", "120",
    ], capture_output=True, text=True, timeout=130)
    try:
        data = json.loads(result.stdout)
        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        elif "error" in data:
            return "API error: " + data["error"].get("message", str(data))
        return "Unknown: " + str(data)[:200]
    except Exception as e:
        return "Failed: " + str(e)

def extract_json(text: str) -> dict:
    import re
    m = re.search(r"\{.*?\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except:
            pass
    return {}
