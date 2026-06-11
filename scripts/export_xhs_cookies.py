#!/usr/bin/env python3
"""
小红书Cookie导出工具 — 启动Edge CDP → 用户登录 → 提取cookie
用法: python export_xhs_cookies.py
"""

import subprocess, time, os, json, urllib.request, websocket
from pathlib import Path

# 集中路径 — 走 _path_setup（仅 Windows 可用，非 Windows 下直接报错）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import EDGE_PATH, COOKIE_FILE as _P_COOKIE

EDGE = EDGE_PATH
COOKIE_OUT = _P_COOKIE if os.path.exists(os.path.dirname(_P_COOKIE)) else r'C:\Users\Administrator\xiaohongshu_cookies.txt'
USER_DATA = os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\Edge\User Data\DebugProfile')

def main():
    print("=== 小红书Cookie导出 ===")
    print("正在启动Edge调试窗口...")
    
    # Kill any existing instance on port 9222
    r = subprocess.run(['netstat', '-ano', '|', 'findstr', ':9222'],
                      capture_output=True, text=True, shell=True, timeout=10)
    for line in r.stdout.split('\n'):
        if 'LISTENING' in line:
            pid = line.strip().split()[-1]
            subprocess.run(['taskkill', '/F', '/PID', pid],
                          capture_output=True, timeout=5)
            time.sleep(1)
            print(f"  已清理旧进程 PID={pid}")
    
    os.makedirs(USER_DATA, exist_ok=True)
    
    proc = subprocess.Popen([
        EDGE, '--remote-debugging-port=9222', '--remote-allow-origins=http://localhost',
        f'--user-data-dir={USER_DATA}', '--no-first-run', '--no-default-browser-check',
        'https://www.xiaohongshu.com'
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    print(f"Edge已启动 (PID={proc.pid})")
    print("请在打开的窗口中登录小红书...")
    input("登录完成后按 Enter 继续...")
    
    time.sleep(3)
    
    # Extract cookies via CDP
    pages = json.loads(urllib.request.urlopen("http://localhost:9222/json", timeout=10).read().decode())
    ws_url = pages[0]['webSocketDebuggerUrl']
    ws = websocket.create_connection(ws_url, timeout=15)
    
    ws.send(json.dumps({'id': 1, 'method': 'Network.getAllCookies', 'params': {}}))
    time.sleep(2)
    resp = json.loads(ws.recv())
    ws.close()
    
    all_cookies = resp.get('result', {}).get('cookies', [])
    xhs_cookies = [c for c in all_cookies if 'xiaohongshu' in c.get('domain', '')]
    
    netscape = ["# Netscape HTTP Cookie File", "# https://curl.haxx.se/rfc/cookie_spec.html"]
    for c in all_cookies:
        if 'xiaohongshu' in c.get('domain', ''):
            domain = c['domain']
            netscape.append(
                f"{domain}\t{'TRUE' if domain.startswith('.') else 'FALSE'}\t"
                f"{c.get('path', '/')}\t{'TRUE' if c.get('secure') else 'FALSE'}\t"
                f"{int(c.get('expires', 0)) if c.get('expires') else '0'}\t"
                f"{c['name']}\t{c['value']}"
            )
    
    with open(COOKIE_OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(netscape))
    
    print(f"\n✅ 已导出 {len(xhs_cookies)} 条cookie → {COOKIE_OUT}")
    
    # Cleanup tabs
    try:
        tabs = json.loads(urllib.request.urlopen("http://localhost:9222/json", timeout=5).read().decode())
        closed = 0
        for t in tabs:
            if 'xiaohongshu' in t.get('url', ''):
                urllib.request.urlopen(
                    f"http://localhost:9222/json/close/{t['id']}", timeout=3)
                closed += 1
        print(f"  已清理 {closed} 个标签页")
    except Exception:
        pass

if __name__ == "__main__":
    main()
