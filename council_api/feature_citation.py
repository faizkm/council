from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fitz
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/feature", tags=["feature"])

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
METADATA_DIR = DATA_DIR / "metadata"


class CitationRequest(BaseModel):
    paper_id: str = Field(..., min_length=1)
    claim_text: str = Field(..., min_length=1)


class CitationResponse(BaseModel):
    paper_id: str
    claim_text: str
    pdf_path: str
    page_number: int
    bbox: list[float]


def _resolve_metadata_path(paper_id: str) -> Path:
    direct = METADATA_DIR / f"{paper_id}.json"
    if direct.exists():
        return direct

    matches = list(METADATA_DIR.glob(f"*{paper_id}*.json"))
    if matches:
        return matches[0]

    raise HTTPException(status_code=404, detail=f"Metadata not found for paper_id '{paper_id}'")


def _extract_pdf_path(metadata: dict[str, Any]) -> str:
    if isinstance(metadata.get("pdf_path"), str) and metadata["pdf_path"].strip():
        return metadata["pdf_path"].strip()

    paper_obj = metadata.get("paper")
    if isinstance(paper_obj, dict):
        candidate = paper_obj.get("pdf_path")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    raise HTTPException(status_code=422, detail="pdf_path missing in metadata")


def _first_match_bbox(pdf_path: Path, claim_text: str) -> tuple[int, list[float]]:
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"PDF file not found: {pdf_path}")

    doc = fitz.open(pdf_path)
    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            hits = page.search_for(claim_text)
            if hits:
                rect = hits[0]
                return page_index + 1, [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]
    finally:
        doc.close()

    raise HTTPException(status_code=404, detail="claim_text not found in PDF")


@router.post("/citation", response_model=CitationResponse)
def citation_jump(payload: CitationRequest) -> CitationResponse:
    metadata_path = _resolve_metadata_path(payload.paper_id)

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid metadata JSON: {metadata_path}") from exc

    pdf_path_str = _extract_pdf_path(metadata)
    pdf_path = Path(pdf_path_str)
    if not pdf_path.is_absolute():
        pdf_path = ROOT_DIR / pdf_path

    page_number, bbox = _first_match_bbox(pdf_path, payload.claim_text)

    return CitationResponse(
        paper_id=payload.paper_id,
        claim_text=payload.claim_text,
        pdf_path=str(pdf_path),
        page_number=page_number,
        bbox=bbox,
    )
