"""Temporary browser-test server with a private shutdown hook (not production)."""

import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.engine import Engine
from backend.server import make_server

server = make_server(Engine(sys.argv[1]), 8011)
original = server.RequestHandlerClass
secret = os.environ["TRADECHECK_TEST_SHUTDOWN"]


class TestHandler(original):
    def do_POST(self):
        if self.path == "/__test_shutdown" and self.headers.get("X-Test-Shutdown") == secret:
            self.reply(200, {"status": "stopping"})
            threading.Thread(target=server.shutdown, daemon=True).start()
            return
        super().do_POST()


server.RequestHandlerClass = TestHandler
try:
    server.serve_forever()
finally:
    server.server_close()
