"""
Claude API KEY 用量面板 — 本地 CORS 代理
==========================================
解决 subclaude.tec-do.cn 的 CORS 限制，让本地 HTML 页面可以查询用量。

用法: python proxy.py [--port 8899] [--settings-path ~/.claude/settings.json]
端口: 默认 8899
配置路径: 可通过环境变量 CLAUDE_SETTINGS_PATH 或 --settings-path 指定
依赖: 仅 Python 标准库（无需 pip install）
"""

import json
import os
import shutil
import ssl
import sys
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode

TARGET_BASE = "https://subclaude.tec-do.cn"
SETTINGS_PATH = os.environ.get("CLAUDE_SETTINGS_PATH") or os.path.join(os.path.expanduser("~"), ".claude", "settings.json")


def read_claude_settings():
    """读取 Claude Code settings.json。"""
    if not os.path.exists(SETTINGS_PATH):
        return None, "settings.json not found"
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def write_claude_settings(settings):
    """写入 Claude Code settings.json。失败时自动回滚。"""
    if os.path.exists(SETTINGS_PATH):
        backup = SETTINGS_PATH + ".bak"
        try:
            shutil.copy2(SETTINGS_PATH, backup)
        except Exception:
            pass  # 备份失败不阻塞

    tmp = SETTINGS_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        os.replace(tmp, SETTINGS_PATH)  # 原子替换
        return True, None
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        return False, str(e)
ALLOWED_ORIGINS = ["null", "http://localhost:8899", "http://127.0.0.1:8899", "file://"]


def fetch_usage(start_date, end_date, api_key):
    """转发用量查询到 subclaude.tec.do.cn，返回 (status, headers, body_bytes)。"""
    params = {"start_date": start_date, "end_date": end_date}
    url = f"{TARGET_BASE}/v1/usage?{urlencode(params)}"

    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "ClaudeKeyPanel/1.0")

    ctx = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            body = resp.read()
            return resp.status, dict(resp.headers), body
    except urllib.error.HTTPError as e:
        body = e.read()
        return e.code, dict(e.headers), body
    except Exception as e:
        return 502, {}, json.dumps({"error": str(e)}).encode()


class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        """抑制默认日志，保护 KEY 隐私。"""
        pass

    def _cors_headers(self, origin=None):
        """返回 CORS 响应头。"""
        return {
            "Access-Control-Allow-Origin": origin or "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "86400",
        }

    def _send_json(self, status, data, extra_headers=None):
        """发送 JSON 响应。"""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        for k, v in (self._cors_headers()).items():
            self.send_header(k, v)
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        """预检请求。"""
        self.send_response(204)
        for k, v in self._cors_headers().items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        # health check
        if parsed.path == "/health":
            self._send_json(200, {"status": "ok", "target": TARGET_BASE})
            return

        # read current key from Claude config
        if parsed.path == "/current-key":
            settings, err = read_claude_settings()
            if err:
                self._send_json(500, {"error": err})
                return
            token = settings.get("env", {}).get("ANTHROPIC_AUTH_TOKEN", "")
            self._send_json(200, {"apiKey": token})
            return

        # usage proxy
        if parsed.path == "/proxy/usage":
            qs = parse_qs(parsed.query)
            start_date = qs.get("start_date", [None])[0]
            end_date = qs.get("end_date", [None])[0]
            api_key = qs.get("key", [None])[0]

            if not start_date or not end_date:
                self._send_json(400, {"error": "Missing start_date or end_date"})
                return
            if not api_key:
                self._send_json(400, {"error": "Missing key parameter"})
                return
            if not api_key.startswith("sk-"):
                self._send_json(400, {"error": "Invalid API key format"})
                return

            print(f"[proxy] querying usage: {start_date} ~ {end_date}  key=sk-...{api_key[-6:]}")
            status, resp_headers, body = fetch_usage(start_date, end_date, api_key)

            # 透传响应
            self.send_response(status)
            content_type = resp_headers.get("Content-Type", "application/json")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", len(body))
            for k, v in self._cors_headers().items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
            return

        # 未知路径
        self._send_json(404, {"error": "Not found", "usage": "/proxy/usage?start_date=...&end_date=...&key=sk-..."})

    def do_POST(self):
        """处理 POST 请求 — 切换 API KEY。"""
        parsed = urlparse(self.path)

        if parsed.path == "/switch":
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len) if content_len > 0 else b"{}"
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON"})
                return

            new_key = data.get("key", "")
            if not new_key or not new_key.startswith("sk-"):
                self._send_json(400, {"error": "Invalid key format"})
                return

            settings, err = read_claude_settings()
            if err:
                self._send_json(500, {"error": f"Failed to read settings: {err}"})
                return

            old_key = settings.get("env", {}).get("ANTHROPIC_AUTH_TOKEN", "")
            if new_key == old_key:
                self._send_json(200, {"switched": False, "message": "Key unchanged, already active"})
                return

            if "env" not in settings:
                settings["env"] = {}
            settings["env"]["ANTHROPIC_AUTH_TOKEN"] = new_key

            ok, err = write_claude_settings(settings)
            if not ok:
                self._send_json(500, {"error": f"Failed to write settings: {err}"})
                return

            print(f"[proxy] switched key: sk-...{old_key[-6:]} -> sk-...{new_key[-6:]}")
            self._send_json(200, {"switched": True, "message": "Key switched successfully"})
            return

        self._send_json(404, {"error": "Not found"})

def main():
    global SETTINGS_PATH

    port = 8899
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1]); i += 2
        elif args[i] == "--settings-path" and i + 1 < len(args):
            SETTINGS_PATH = args[i + 1]; i += 2
        else:
            i += 1

    server = HTTPServer(("127.0.0.1", port), ProxyHandler)
    print(f" Claude KEY 用量代理已启动")
    print(f"   地址: http://127.0.0.1:{port}")
    print(f"   配置: {SETTINGS_PATH}")
    print(f"   目标: {TARGET_BASE}")
    print(f"   健康检查: http://127.0.0.1:{port}/health")
    print(f"   Ctrl+C 停止")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n代理已停止")
        server.server_close()


if __name__ == "__main__":
    main()
