"""PRISM API tester: sends HTTP requests from Python (no CORS limits) on a
worker thread and reports status, headers, timing and body."""

from __future__ import annotations

import json
import ssl
import threading
import time
import urllib.error
import urllib.request

from PyQt6.QtCore import QObject, pyqtSignal

from dohproxy import urllib_handlers

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
MAX_BODY = 2 * 1024 * 1024        # show at most 2 MB of a response
USER_AGENT = "PRISM-API-Tester/1.0"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # report 3xx instead of following
        return None


class ApiTester(QObject):
    finished = pyqtSignal(str)     # JSON result

    def send(self, spec: dict) -> None:
        threading.Thread(target=self._run, args=(spec,), daemon=True).start()

    def _run(self, spec: dict) -> None:
        req_id = spec.get("id")
        method = str(spec.get("method", "GET")).upper()
        url = str(spec.get("url", "")).strip()
        result: dict = {"id": req_id, "method": method, "url": url}
        try:
            if method not in METHODS:
                raise ValueError(f"Unsupported method {method}")
            if not url.lower().startswith(("http://", "https://")):
                url = "https://" + url
                result["url"] = url
            headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
            for h in spec.get("headers", []):
                if h.get("on", True) and str(h.get("name", "")).strip():
                    headers[str(h["name"]).strip()] = str(h.get("value", ""))
            body = spec.get("body") or ""
            data = None
            if method not in ("GET", "HEAD") and body:
                data = body.encode("utf-8")
                if not any(k.lower() == "content-type" for k in headers):
                    try:
                        json.loads(body)
                        headers["Content-Type"] = "application/json"
                    except ValueError:
                        headers["Content-Type"] = "text/plain; charset=utf-8"

            handlers = [urllib.request.HTTPSHandler(context=ssl.create_default_context()), *urllib_handlers()]
            if not spec.get("followRedirects", True):
                handlers.append(_NoRedirect())
            opener = urllib.request.build_opener(*handlers)
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            timeout = max(1, min(120, int(spec.get("timeout", 30))))
            t0 = time.perf_counter()
            try:
                resp = opener.open(req, timeout=timeout)
            except urllib.error.HTTPError as err:      # 4xx / 5xx still have a body
                resp = err
            ttfb = time.perf_counter() - t0
            raw = resp.read(MAX_BODY + 1) if method != "HEAD" else b""
            total = time.perf_counter() - t0
            truncated = len(raw) > MAX_BODY
            raw = raw[:MAX_BODY]
            ctype = resp.headers.get("Content-Type", "")
            charset = resp.headers.get_content_charset() or "utf-8"
            result.update(
                ok=True,
                status=resp.status if hasattr(resp, "status") else resp.code,
                reason=getattr(resp, "reason", "") or "",
                finalUrl=resp.geturl() if hasattr(resp, "geturl") else url,
                headers=[[k, v] for k, v in resp.headers.items()],
                contentType=ctype,
                size=len(raw),
                truncated=truncated,
                timeMs=round(total * 1000),
                ttfbMs=round(ttfb * 1000),
                body=raw.decode(charset, errors="replace"),
                binary=not _looks_textual(ctype, raw),
                sentHeaders=[[k, v] for k, v in headers.items()],
            )
            resp.close()
        except urllib.error.URLError as exc:
            result.update(ok=False, error=f"Connection failed: {exc.reason}")
        except Exception as exc:  # noqa: BLE001 - everything goes back to the UI
            result.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        self.finished.emit(json.dumps(result))


def _looks_textual(ctype: str, raw: bytes) -> bool:
    c = ctype.lower()
    if any(t in c for t in ("json", "text", "xml", "javascript", "html", "csv", "yaml", "graphql")):
        return True
    if not raw:
        return True
    sample = raw[:512]
    return b"\x00" not in sample
