from __future__ import annotations

import json
import os
from pathlib import Path
from typing import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(tags=["feature-debate"])

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
EXTRACTED_DIR = DATA_DIR / "extracted"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


class DebateRequest(BaseModel):
    paper_id_A: str = Field(min_length=1)
    paper_id_B: str = Field(min_length=1)


@router.post("/feature/debate")
async def live_debate(payload: DebateRequest) -> StreamingResponse:
    paper_a = _load_extracted(payload.paper_id_A.strip())
    paper_b = _load_extracted(payload.paper_id_B.strip())

    prompt = _build_debate_prompt(paper_a=paper_a, paper_b=paper_b)

    async def event_stream() -> AsyncIterator[str]:
        async for chunk in _stream_groq_debate(prompt):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _load_extracted(paper_id: str) -> dict:
    path = EXTRACTED_DIR / f"{paper_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Extracted JSON not found for {paper_id}.")
    return json.loads(path.read_text(encoding="utf-8"))


def _build_debate_prompt(paper_a: dict, paper_b: dict) -> str:
    claims_a = _short_claims(paper_a)
    claims_b = _short_claims(paper_b)

    return (
        "You are simulating a strict two-agent scientific debate.\n"
        "Agent A defends Paper A claims. Agent B attacks Paper A claims using Paper B.\n"
        "Output as plain text with alternating turns: A1, B1, A2, B2, A3, B3, then Verdict.\n"
        "Each turn must be concise, evidence-grounded, and cite claim snippets in quotes.\n\n"
        f"Paper A (paper_id={paper_a.get('paper_id', '')}, title={paper_a.get('title', '')}) claims:\n"
        + "\n".join(f"- {item}" for item in claims_a)
        + "\n\n"
        + f"Paper B (paper_id={paper_b.get('paper_id', '')}, title={paper_b.get('title', '')}) claims:\n"
        + "\n".join(f"- {item}" for item in claims_b)
        + "\n"
    )


def _short_claims(payload: dict, max_items: int = 8, max_chars: int = 260) -> list[str]:
    claims: list[str] = []
    for claim in payload.get("claims", []):
        text = " ".join(str(claim).split())
        if not text:
            continue
        claims.append(text[:max_chars])
        if len(claims) >= max_items:
            break
    return claims or ["No extracted claims available."]


async def _stream_groq_debate(prompt: str) -> AsyncIterator[str]:
    keys = _groq_api_keys()
    if not keys:
        yield _sse_data({"error": "No Groq API key found in environment."})
        return

    payload = {
        "model": os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL),
        "temperature": 0.2,
        "stream": True,
        "messages": [
            {
                "role": "system",
                "content": "You are an expert scientific debate assistant. Stay factual and concise.",
            },
            {"role": "user", "content": prompt},
        ],
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        for api_key in keys:
            try:
                async with client.stream(
                    "POST",
                    GROQ_URL,
                    headers={
                        "authorization": f"Bearer {api_key}",
                        "content-type": "application/json",
                    },
                    json=payload,
                ) as response:
                    if response.status_code >= 400:
                        continue

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue

                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            yield "event: done\ndata: [DONE]\n\n"
                            return

                        try:
                            chunk = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        delta = (
                            chunk.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if delta:
                            yield _sse_data({"token": delta})

                    yield "event: done\ndata: [DONE]\n\n"
                    return
            except Exception:  # noqa: BLE001
                continue

    yield _sse_data({"error": "Failed to stream debate from Groq."})


def _groq_api_keys() -> list[str]:
    pooled = os.getenv("GROQ_API_KEYS", "")
    keys = [item.strip() for item in pooled.split(",") if item.strip()]

    single = os.getenv("GROQ_API_KEY", "").strip()
    if single and single not in keys:
        keys.append(single)

    return keys


def _sse_data(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=True)}\\n\\n"
