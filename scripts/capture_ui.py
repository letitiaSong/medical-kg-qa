"""用无头 Edge/Chrome 采集 TuGraph 管理界面的截图（报告用的 3 张浏览器截图）。

依赖：websocket-client（pip install websocket-client）；Edge 或 Chrome 任一即可。

用法：
    python scripts/capture_ui.py            # 采集 01 / 09 / 11 三张
    python scripts/capture_ui.py --probe    # 只打印页面文字与输入框，便于调试

原理：启动 --headless=new 的浏览器，用 CDP 打开 http://127.0.0.1:7070，
先截登录页；再用 JS 填账号密码登录；最后进入图查询面板截一张。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websocket

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "docs" / "images"
BASE = "http://127.0.0.1:7070"
PORT = 9333

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/microsoft-edge",
    "/usr/bin/google-chrome",
]


class CDP:
    def __init__(self, ws_url: str) -> None:
        self.ws = websocket.create_connection(ws_url, timeout=30)
        self.next_id = 0

    def call(self, method: str, **params):
        self.next_id += 1
        msg_id = self.next_id
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            data = json.loads(self.ws.recv())
            if data.get("id") == msg_id:
                if "error" in data:
                    raise RuntimeError(f"{method} 失败：{data['error']}")
                return data.get("result", {})

    def js(self, expression: str):
        res = self.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        return res.get("result", {}).get("value")

    def shot(self, path: Path) -> Path:
        data = self.call("Page.captureScreenshot", format="png", captureBeyondViewport=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(data["data"]))
        return path


def launch(width: int = 1600, height: int = 950) -> subprocess.Popen:
    exe = next((p for p in BROWSERS if os.path.exists(p)), None)
    if not exe:
        raise SystemExit("没找到 Edge/Chrome 可执行文件")
    profile = ROOT / "outputs" / "_edge_profile"
    shutil.rmtree(profile, ignore_errors=True)
    proc = subprocess.Popen(
        [
            exe,
            "--headless=new",
            f"--remote-debugging-port={PORT}",
            f"--user-data-dir={profile}",
            f"--window-size={width},{height}",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-gpu",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1) as resp:
                json.loads(resp.read())
                return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    proc.terminate()
    raise SystemExit("浏览器没能在 30s 内启动调试端口")


def page_ws() -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=5) as resp:
        targets = json.loads(resp.read())
    pages = [t for t in targets if t.get("type") == "page"]
    return pages[0]["webSocketDebuggerUrl"]


def wait_idle(cdp: CDP, seconds: float = 4.0) -> None:
    time.sleep(seconds)


LOGIN_JS = """
(() => {
  const inputs = [...document.querySelectorAll('input')];
  const addr = inputs.find(i => /数据库地址|地址|host/i.test(i.placeholder || ''));
  const user = inputs.find(i => /账号|用户名|user/i.test(i.placeholder || ''));
  const pass = inputs.find(i => i.type === 'password');
  if (!user || !pass) return 'no-form:' + inputs.length;
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  const fill = (el, v) => { setter.call(el, v); el.dispatchEvent(new Event('input', {bubbles: true})); };
  if (addr && !addr.value) fill(addr, '%ADDR%');
  fill(user, 'admin');
  fill(pass, '%PASSWORD%');
  const btn = [...document.querySelectorAll('button')].find(b => /登录|登 录|Login/i.test(b.innerText));
  if (btn) { btn.click(); return 'clicked'; }
  return 'no-button';
})()
"""


def mouse_click(cdp: CDP, selector: str) -> str:
    """对元素派发真实鼠标事件（antd 组件监听 mousedown，直接 .click() 无效）。"""
    return cdp.js(
        """
        (() => {
          const el = document.querySelector(%s);
          if (!el) return 'none';
          const r = el.getBoundingClientRect();
          const opts = {bubbles: true, cancelable: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2};
          ['mousedown', 'mouseup', 'click'].forEach(t => el.dispatchEvent(new MouseEvent(t, opts)));
          return 'ok';
        })()
        """
        % json.dumps(selector)
    )


def click_text(cdp: CDP, text: str, nth: int = 0) -> str:
    """点击 innerText 恰好等于 text 的最深层可见元素。"""
    return cdp.js(
        """
        (() => {
          const want = %s, nth = %d;
          const els = [...document.querySelectorAll('*')].filter(
            e => e.offsetParent && (e.innerText || '').trim() === want);
          const el = els[nth] || els[0];
          if (!el) return 'none:' + els.length;
          const r = el.getBoundingClientRect();
          const opts = {bubbles: true, cancelable: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2};
          ['mousedown', 'mouseup', 'click'].forEach(t => el.dispatchEvent(new MouseEvent(t, opts)));
          return el.tagName + '.' + (el.className || '').toString().slice(0, 40);
        })()
        """
        % (json.dumps(text), nth)
    )


QUERY = "MATCH (d:Disease {name: '癫痫'})-[r:HAS_SYMPTOM|REQUIRES_EXAM|USES_DRUG|BELONGS_TO]-(n)\nRETURN d, r, n LIMIT 40"


def main() -> int:
    parser = argparse.ArgumentParser(description="采集 TuGraph 管理界面截图")
    parser.add_argument("--probe", action="store_true", help="打印页面文字后退出")
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT))
    from medkg.config import TUGRAPH

    addr = f"{TUGRAPH.host}:{getattr(TUGRAPH, 'bolt_port', 7687)}"
    proc = launch()
    try:
        time.sleep(2)
        cdp = CDP(page_ws())
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("Emulation.setDeviceMetricsOverride", width=1600, height=950, deviceScaleFactor=1.5, mobile=False)

        cdp.call("Page.navigate", url=BASE + "/")
        wait_idle(cdp, 6)
        if args.probe:
            print("URL:", cdp.js("location.href"))
            print("TEXT:", (cdp.js("document.body.innerText") or "")[:2000])
            print("INPUTS:", cdp.js("[...document.querySelectorAll('input')].map(i=>i.type+':'+i.placeholder)"))
            return 0

        login_shot = IMAGES / "01-tugraph-login.png"
        cdp.shot(login_shot)
        print("[OK] 01 登录页 ->", login_shot.relative_to(ROOT))

        js = LOGIN_JS.replace("%PASSWORD%", TUGRAPH.password).replace("%ADDR%", addr)
        print("登录动作：", cdp.js(js))
        wait_idle(cdp, 7)
        print("默认密码提示：", click_text(cdp, "跳 过"))
        wait_idle(cdp, 6)
        print("URL:", cdp.js("location.href"))
        cdp.js("window.scrollTo(0, 260)")
        wait_idle(cdp, 1.5)
        cdp.shot(IMAGES / "09-graph-list.png")
        print("[OK] 09 图项目列表 -> docs/images/09-graph-list.png")

        cdp.js("location.hash='#/query'")
        wait_idle(cdp, 6)
        print("打开图库下拉：", mouse_click(cdp, ".ant-select .ant-select-selector"))
        wait_idle(cdp, 2)
        print("下拉项：", cdp.js("[...document.querySelectorAll('.rc-virtual-list-holder-inner > *')].map(e=>e.innerText)"))
        picked = cdp.js(
            """
            (() => {
              const opt = [...document.querySelectorAll('.rc-virtual-list-holder-inner > *')]
                .find(e => (e.innerText || '').trim() === %s);
              if (!opt) return 'none';
              const r = opt.getBoundingClientRect();
              const o = {bubbles: true, cancelable: true, clientX: r.x + 10, clientY: r.y + 10};
              ['mousedown', 'mouseup', 'click'].forEach(t => opt.dispatchEvent(new MouseEvent(t, o)));
              return 'picked';
            })()
            """
            % json.dumps(TUGRAPH.graph)
        )
        print("选择图库：", picked)
        wait_idle(cdp, 3)
        print("当前图库：", cdp.js("(document.querySelector('.ant-select-selection-item')||{}).innerText"))

        cdp.js("window.monaco.editor.getModels()[0].setValue(%s)" % json.dumps(QUERY))
        wait_idle(cdp, 1)
        print("执行查询：", click_text(cdp, "执行"))
        wait_idle(cdp, 8)
        print("结果片段：", (cdp.js("document.body.innerText") or "")[:300].replace("\n", " | "))
        print("切到图谱：", click_text(cdp, "图谱"))
        wait_idle(cdp, 6)
        cdp.shot(IMAGES / "11-cypher-console.png")
        print("[OK] 11 图查询面板 -> docs/images/11-cypher-console.png")
    finally:
        proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())