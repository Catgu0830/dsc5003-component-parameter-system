"""Serve the canonical frontend without stale HTML or JavaScript cache reuse."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from functools import partial
class FrontendHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control','no-store, max-age=0')
        super().end_headers()
    def do_GET(self):
        for key in ('If-Modified-Since','If-None-Match'):
            if key in self.headers:del self.headers[key]
        super().do_GET()
if __name__=='__main__':
    root=Path(__file__).resolve().parents[2]/'frontend'
    ThreadingHTTPServer(('127.0.0.1',5500),partial(FrontendHandler,directory=str(root))).serve_forever()
