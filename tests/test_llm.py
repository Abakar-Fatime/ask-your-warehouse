import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ayw.llm import LLMError, OllamaClient, extract_sql


def test_extract_sql_variants():
    assert extract_sql("Sure!\n```sql\nSELECT 1\n```\nDone") == "SELECT 1"
    assert extract_sql("```\nSELECT 2\n```") == "SELECT 2"
    assert extract_sql("Here: SELECT 3 FROM t") == "SELECT 3 FROM t"
    assert extract_sql("WITH a AS (SELECT 1) SELECT * FROM a") .startswith("WITH")
    assert extract_sql("no query here") == "no query here"


class _Fake(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Fake.seen.append((self.path, body))
        if body["model"] == "missing":
            self.send_response(404); self.end_headers(); return
        out = json.dumps({"message": {"role": "assistant", "content": "```sql\nSELECT 1\n```"},
                          "prompt_eval_count": 12, "eval_count": 5}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture()
def server():
    srv = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Fake.seen.clear()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_ollama_client_request_and_response(server):
    r = OllamaClient("tiny:1b", host=server).generate([{"role": "user", "content": "hi"}])
    assert r.text.startswith("```sql") and (r.prompt_tokens, r.completion_tokens) == (12, 5)
    path, body = _Fake.seen[0]
    assert path == "/api/chat" and body["stream"] is False and body["model"] == "tiny:1b"
    assert body["options"]["temperature"] == 0 and body["messages"][0]["content"] == "hi"


def test_unknown_model_suggests_pulling_it(server):
    with pytest.raises(LLMError, match="ollama pull missing"):
        OllamaClient("missing", host=server).generate([{"role": "user", "content": "hi"}])


def test_unreachable_server_gives_a_helpful_message():
    with pytest.raises(LLMError, match="ollama serve"):
        OllamaClient("x", host="http://127.0.0.1:9", timeout_s=2).generate([{"role": "user", "content": "hi"}])
