"""Groq-compatible test double for the LLM-provider-failure chaos scenario.

Not a general Groq mock - it only has to make llm.py's generate() (Multi Agent
Intelligence Platform repo, backend/app/llm.py) either succeed with a benign
completion or raise the specific groq-sdk exception classes that
groq_error_kind() (backend/app/metrics.py) buckets into timeout | rate_limit |
5xx. Tool-calling responses are out of scope - "healthy" mode returns plain
content only, so it only round-trips nodes that don't require tool_calls.

Modes (POST /mode {"mode": ..., "kind": "5xx"|"rate_limit"}):
  healthy      -> 200 with a fixed chat completion (default)
  error        -> 500 ("kind": "rate_limit" -> 429 instead)
  slow         -> sleeps past the client's 30s timeout (llm.py always passes
                  timeout=30) so the groq SDK raises APITimeoutError itself;
                  this process never has to construct that exception.
"""

import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

_state = {"mode": "healthy", "kind": "5xx"}


@app.get("/health")
def health():
    return {"status": "ok", **_state}


@app.get("/mode")
def get_mode():
    return _state


@app.post("/mode")
async def set_mode(request: Request):
    body = await request.json()
    mode = body.get("mode")
    if mode not in ("healthy", "error", "slow"):
        return JSONResponse({"error": "mode must be healthy|error|slow"}, status_code=400)
    _state["mode"] = mode
    _state["kind"] = body.get("kind", "5xx")
    return _state


@app.post("/openai/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", "mock")

    if _state["mode"] == "slow":
        # SLOW_SLEEP_SEC > llm.py's client-side timeout=30 kwarg, so the groq
        # SDK times out and raises APITimeoutError on its own - no error body
        # needed here.
        time.sleep(35)

    if _state["mode"] == "error":
        if _state["kind"] == "rate_limit":
            return JSONResponse(
                {"error": {"message": "mock rate limit", "type": "rate_limit_error"}},
                status_code=429,
            )
        return JSONResponse(
            {"error": {"message": "mock upstream failure", "type": "internal_error"}},
            status_code=500,
        )

    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "mock-llm: healthy mode response"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
