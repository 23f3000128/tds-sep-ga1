"""TDS GA1 — one FastAPI app for Q6 (/effective-config) and Q14 (/mcp)."""
import hashlib
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

EMAIL = "23f3000128@ds.study.iitm.ac.in"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ---------------- Q6: 12-factor config precedence ----------------
DEFAULTS = {"port": 8000, "workers": 1, "debug": False, "log_level": "info", "api_key": "default-secret-000"}
FILE_YAML = {"workers": 15, "debug": False}                       # config.development.yaml
DOTENV = {"APP_PORT": "8028", "APP_DEBUG": "true", "APP_LOG_LEVEL": "warning", "APP_API_KEY": "key-d9sxwx375m"}
OS_ENV = {"APP_PORT": "8457", "APP_DEBUG": "true"}                # APP_* OS env layer


def coerce(key, value):
    if key in ("port", "workers"):
        return int(value)
    if key == "debug":
        return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "on")
    return str(value)


def env_layer(d, alias=False):
    out = {}
    for k, v in d.items():
        if alias and k == "NUM_WORKERS":
            out["workers"] = v
        elif k.startswith("APP_"):
            out[k[4:].lower()] = v
    return out


@app.get("/effective-config")
def effective_config(request: Request):
    cfg = dict(DEFAULTS)
    cfg.update(FILE_YAML)
    cfg.update(env_layer(DOTENV, alias=True))
    # real OS env vars too, falling back to the assigned OS layer
    osl = {k: v for k, v in os.environ.items() if k.startswith("APP_")} or OS_ENV
    cfg.update(env_layer(osl))
    for item in request.query_params.getlist("set"):
        if "=" in item:
            k, v = item.split("=", 1)
            k = k.strip()
            cfg["workers" if k == "num_workers" else k] = v
    out = {k: coerce(k, cfg[k]) for k in DEFAULTS}
    out["api_key"] = "****"
    return out


# ---------------- Q14: minimal MCP server (streamable HTTP, JSON responses) ----------------
TOOL = {
    "name": "solve_challenge",
    "description": "Return the first 16 hex chars of SHA-256('<X-Exam-Challenge>:<email>').",
    "inputSchema": {"type": "object", "properties": {}, "required": []},
}


def rpc(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def handle(msg, headers):
    method, id_ = msg.get("method"), msg.get("id")
    if id_ is None:  # notification (e.g. notifications/initialized)
        return None
    if method == "initialize":
        return rpc(id_, {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-03-26"),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "tds-ga1-mcp", "version": "1.0.0"},
        })
    if method == "ping":
        return rpc(id_, {})
    if method == "tools/list":
        return rpc(id_, {"tools": [TOOL]})
    if method == "tools/call":
        challenge = headers.get("x-exam-challenge", "").strip()
        text = hashlib.sha256(f"{challenge}:{EMAIL.strip().lower()}".encode()).hexdigest()[:16]
        return rpc(id_, {"content": [{"type": "text", "text": text}], "isError": False})
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32601, "message": f"Method not found: {method}"}}


@app.post("/mcp")
async def mcp(request: Request):
    body = await request.json()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if isinstance(body, list):
        out = [r for r in (handle(m, headers) for m in body) if r is not None]
        return JSONResponse(out) if out else Response(status_code=202)
    res = handle(body, headers)
    return JSONResponse(res) if res is not None else Response(status_code=202)


@app.get("/mcp")
def mcp_get():
    # No server-initiated SSE stream offered
    return Response(status_code=405)
