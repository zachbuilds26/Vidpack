"""Drive the vidpack UI over the Chrome DevTools Protocol (websocket).

Loads a page, waits for the app to settle, collects console errors and failed
network requests, evaluates DOM assertions, and writes a screenshot.
"""

import base64
import json
import sys
import time
import urllib.request

from websockets.sync.client import connect

CDP = "http://127.0.0.1:9333"


def new_target(url):
    req = urllib.request.Request(f"{CDP}/json/new?{url}", method="PUT")
    return json.loads(urllib.request.urlopen(req).read())


def close_target(tid):
    urllib.request.urlopen(f"{CDP}/json/close/{tid}").read()


class Session:
    def __init__(self, ws_url):
        self.ws = connect(ws_url, max_size=64 * 1024 * 1024)
        self.n = 0
        self.events = []

    def send(self, method, params=None, timeout=25):
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self.ws.recv(timeout=max(0.1, deadline - time.time()))
            msg = json.loads(raw)
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)
        raise TimeoutError(method)

    def drain(self, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                msg = json.loads(self.ws.recv(timeout=max(0.05, deadline - time.time())))
            except TimeoutError:
                break
            except Exception:
                break
            if "method" in msg:
                self.events.append(msg)

    def eval(self, expr):
        result = self.send(
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": True, "awaitPromise": True},
        )
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"].get("text"))
        return result["result"].get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def run(url, width, height, theme, shot_path, script=None, settle=3.0):
    target = new_target(url)
    session = Session(target["webSocketDebuggerUrl"])
    try:
        session.send("Runtime.enable")
        session.send("Log.enable")
        session.send("Network.enable")
        session.send("Page.enable")
        session.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 2, "mobile": width < 700},
        )
        if theme:
            session.send("Emulation.setEmulatedMedia",
                         {"features": [{"name": "prefers-color-scheme", "value": theme}]})
        session.send("Page.navigate", {"url": url})
        session.drain(settle)
        if script:
            session.eval(script)
            session.drain(1.6)

        console = []
        failures = []
        for event in session.events:
            method = event.get("method")
            params = event.get("params", {})
            if method == "Runtime.exceptionThrown":
                console.append("EXCEPTION: " + str(
                    params.get("exceptionDetails", {}).get("text", "")) + " " + str(
                    params.get("exceptionDetails", {}).get("exception", {}).get("description", "")))
            elif method == "Runtime.consoleAPICalled" and params.get("type") in ("error", "warning"):
                text = " ".join(str(a.get("value", a.get("description", ""))) for a in params.get("args", []))
                console.append(f"{params['type']}: {text}")
            elif method == "Log.entryAdded":
                entry = params.get("entry", {})
                if entry.get("level") in ("error", "warning"):
                    console.append(f"log-{entry['level']}: {entry.get('text')} {entry.get('url','')}")
            elif method == "Network.loadingFailed":
                failures.append(params.get("errorText", "") + " " + str(params.get("type")))

        shot = session.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
        with open(shot_path, "wb") as fh:
            fh.write(base64.b64decode(shot["data"]))

        report = session.eval(ASSERTIONS)
        return {"console": console, "netfail": failures, "dom": report}
    finally:
        session.close()
        close_target(target["id"])


ASSERTIONS = r"""
(() => {
  const out = {};
  const cs = getComputedStyle(document.body);
  out.bodyBg = cs.backgroundColor;
  out.bodyColor = cs.color;
  out.font = cs.fontFamily.split(",")[0];
  out.docW = document.documentElement.scrollWidth;
  out.winW = window.innerWidth;
  out.hOverflow = document.documentElement.scrollWidth > window.innerWidth + 1;
  const wide = [...document.querySelectorAll("body *")]
    .filter(n => n.getBoundingClientRect().right > window.innerWidth + 2)
    .slice(0, 5)
    .map(n => (n.tagName + "." + (n.className && n.className.baseVal !== undefined ? n.className.baseVal : n.className)).slice(0, 60));
  out.overflowing = wide;
  const unresolved = [...document.querySelectorAll("use")]
    .filter(u => {
      const id = (u.getAttribute("href") || "").slice(1);
      return id && !document.getElementById(id);
    })
    .map(u => u.getAttribute("href"));
  out.missingIcons = [...new Set(unresolved)];
  out.text = (document.body.innerText || "").replace(/\s+/g, " ").slice(0, 900);
  return out;
})()
"""


if __name__ == "__main__":
    cfg = json.loads(sys.argv[1])
    result = run(**cfg)
    print(json.dumps(result, indent=1)[:4000])
