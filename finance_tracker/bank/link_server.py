"""Short-lived localhost server that hosts Plaid Link and returns public_token."""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import urlparse


LINK_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Connect bank — Finance Tracker</title>
  <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
  <style>
    body {{
      font-family: system-ui, sans-serif;
      background: #1e1e1e;
      color: #f3f3f3;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      margin: 0;
    }}
    .card {{
      background: #2d2d30;
      padding: 2rem 2.5rem;
      border-radius: 12px;
      max-width: 420px;
      text-align: center;
    }}
    button {{
      background: #0a84ff;
      color: white;
      border: 0;
      padding: 0.75rem 1.5rem;
      border-radius: 8px;
      font-size: 1rem;
      cursor: pointer;
    }}
    button:disabled {{ opacity: 0.5; cursor: default; }}
    #status {{ margin-top: 1rem; color: #9d9d9d; min-height: 1.5rem; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Connect your bank</h1>
    <p>Link Chase, Capital One, or another US account via Plaid.</p>
    <button id="link-btn">Open Plaid Link</button>
    <p id="status"></p>
  </div>
  <script>
    const linkToken = {link_token_json};
    const statusEl = document.getElementById('status');
    const btn = document.getElementById('link-btn');

    function setStatus(msg) {{ statusEl.textContent = msg; }}

    const handler = Plaid.create({{
      token: linkToken,
      onSuccess: async (public_token, metadata) => {{
        setStatus('Saving connection…');
        btn.disabled = true;
        try {{
          const resp = await fetch('/success', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{
              public_token: public_token,
              institution: metadata && metadata.institution
                ? metadata.institution.name
                : ''
            }})
          }});
          if (!resp.ok) throw new Error('Server rejected token');
          setStatus('Connected. You can close this tab and return to the app.');
        }} catch (err) {{
          setStatus('Failed to send token: ' + err);
          btn.disabled = false;
        }}
      }},
      onExit: (err) => {{
        if (err) {{
          setStatus('Link exited: ' + (err.display_message || err.error_message || err.error_code));
          fetch('/cancel', {{ method: 'POST' }}).catch(() => {{}});
        }}
      }},
    }});

    btn.addEventListener('click', () => handler.open());
    // Auto-open Link shortly after load.
    setTimeout(() => handler.open(), 400);
  </script>
</body>
</html>
"""


class LinkSession:
    """Runs a one-shot Plaid Link capture on localhost."""

    def __init__(self, link_token: str, host: str = "127.0.0.1", port: int = 0) -> None:
        self.link_token = link_token
        self.host = host
        self.port = port
        self.public_token: Optional[str] = None
        self.institution_name: str = ""
        self.error: Optional[str] = None
        self._done = threading.Event()
        self._httpd: Optional[HTTPServer] = None

    def run(self, timeout_sec: float = 300.0) -> Optional[str]:
        session = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

            def do_GET(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if path in ("/", "/link"):
                    body = LINK_HTML.format(
                        link_token_json=json.dumps(session.link_token)
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

            def do_POST(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                if path == "/success":
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                        session.public_token = str(payload.get("public_token") or "")
                        session.institution_name = str(payload.get("institution") or "")
                        if not session.public_token:
                            raise ValueError("missing public_token")
                    except Exception as exc:
                        session.error = str(exc)
                        self.send_response(400)
                        self.end_headers()
                        session._done.set()
                        return
                    body = b'{"ok":true}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    session._done.set()
                    return
                if path == "/cancel":
                    session.error = session.error or "Link cancelled"
                    self.send_response(200)
                    self.end_headers()
                    session._done.set()
                    return
                self.send_response(404)
                self.end_headers()

        self._httpd = HTTPServer((self.host, self.port), Handler)
        self.port = self._httpd.server_address[1]
        thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        thread.start()

        url = f"http://{self.host}:{self.port}/"
        webbrowser.open(url)

        finished = self._done.wait(timeout=timeout_sec)
        try:
            self._httpd.shutdown()
        except Exception:
            pass

        if not finished:
            self.error = self.error or "Timed out waiting for Plaid Link"
            return None
        return self.public_token


def run_plaid_link(link_token: str, timeout_sec: float = 300.0) -> tuple[Optional[str], str, Optional[str]]:
    """
    Open Plaid Link in the browser and wait for a public_token.

    Returns (public_token, institution_name, error).
    """
    session = LinkSession(link_token)
    token = session.run(timeout_sec=timeout_sec)
    return token, session.institution_name, session.error
