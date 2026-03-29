from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from research_crawler.config import load_environment
from research_crawler.pipeline import ResearchOrchestrator

from council_api.extraction import build_final_report, build_report, extract_from_pdf

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
PDF_DIR = DATA_DIR / "pdf"
METADATA_DIR = DATA_DIR / "metadata"
EXTRACTED_DIR = DATA_DIR / "extracted"
REPORTS_DIR = DATA_DIR / "reports"

load_environment()

app = FastAPI(title="Council API", version="0.1.0")
orchestrator = ResearchOrchestrator(pdf_dir=PDF_DIR, metadata_dir=METADATA_DIR)


class CrawlRequest(BaseModel):
    query: str = Field(default="", description="Topic, DOI, or title")
    question: str = Field(default="", description="Natural-language research question")
    topic_count: int = Field(default=4, ge=1, le=12)
    limit_per_source: int = Field(default=10, ge=1, le=50)
    max_papers: int = Field(default=20, ge=1, le=200)
    concurrency: int = Field(default=6, ge=1, le=20)


class AnalyzeRequest(BaseModel):
    paper_ids: list[str] = Field(default_factory=list)


class FinalReportRequest(BaseModel):
    target_research_finding: str = Field(default="", description="Main finding to validate")
    top_k: int = Field(default=10, ge=1, le=50)
    paper_ids: list[str] = Field(default_factory=list)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/crawl")
async def crawl(payload: CrawlRequest) -> dict:
    query = payload.query.strip()
    question = payload.question.strip()

    if not query and not question:
        raise HTTPException(status_code=422, detail="Provide either query or question.")

    if question:
        summary = await orchestrator.run_from_question(
            question=question,
            limit_per_source=payload.limit_per_source,
            max_papers=payload.max_papers,
            concurrency=payload.concurrency,
            topic_count=payload.topic_count,
        )
    else:
        summary = await orchestrator.run(
            query=query,
            limit_per_source=payload.limit_per_source,
            max_papers=payload.max_papers,
            concurrency=payload.concurrency,
        )

    return {
        "query": summary.query,
        "topics": summary.topics,
        "discovered": summary.discovered,
        "deduped": summary.deduped,
        "attempted": summary.attempted,
        "saved": summary.saved,
        "skipped": summary.skipped,
        "failed": summary.failed,
        "results": [
            {
                "paper_id": item.paper_id,
                "status": item.status,
                "reason": item.reason,
                "pdf_path": str(item.pdf_path) if item.pdf_path else "",
                "metadata_path": str(item.metadata_path) if item.metadata_path else "",
            }
            for item in summary.results
        ],
    }


@app.get("/papers")
def list_papers() -> dict:
    papers = []
    for path in sorted(METADATA_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        paper_id = path.stem
        papers.append(
            {
                "paper_id": paper_id,
                "title": payload.get("title", ""),
                "year": payload.get("year", ""),
                "source": payload.get("source", ""),
                "pdf_path": payload.get("pdf_path", ""),
                "metadata_path": str(path),
            }
        )
    return {"count": len(papers), "papers": papers}


@app.post("/extract/{paper_id}")
def extract_paper(paper_id: str) -> dict:
    metadata_path = METADATA_DIR / f"{paper_id}.json"
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail="Metadata file not found.")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    pdf_path = Path(metadata.get("pdf_path", ""))
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found.")

    extracted = extract_from_pdf(
        paper_id=paper_id,
        pdf_path=pdf_path,
        output_dir=EXTRACTED_DIR,
        metadata=metadata,
    )

    return {
        "paper_id": paper_id,
        "extracted_path": str(EXTRACTED_DIR / f"{paper_id}.json"),
        "claim_count": len(extracted.get("claims", [])),
        "method_count": len(extracted.get("methods", [])),
        "dataset_count": len(extracted.get("datasets", [])),
    }


@app.post("/extract-all")
def extract_all_papers() -> dict:
    processed = []
    skipped = []

    for metadata_path in sorted(METADATA_DIR.glob("*.json")):
        paper_id = metadata_path.stem
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        pdf_path = Path(metadata.get("pdf_path", ""))

        if not pdf_path.exists():
            skipped.append({"paper_id": paper_id, "reason": "PDF file not found"})
            continue

        extracted = extract_from_pdf(
            paper_id=paper_id,
            pdf_path=pdf_path,
            output_dir=EXTRACTED_DIR,
            metadata=metadata,
        )

        processed.append(
            {
                "paper_id": paper_id,
                "claim_count": len(extracted.get("claims", [])),
                "method_count": len(extracted.get("methods", [])),
                "dataset_count": len(extracted.get("datasets", [])),
            }
        )

    return {
        "processed_count": len(processed),
        "skipped_count": len(skipped),
        "processed": processed,
        "skipped": skipped,
    }


@app.post("/analyze")
def analyze(payload: AnalyzeRequest) -> dict:
    report = build_report(EXTRACTED_DIR, paper_ids=payload.paper_ids or None)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = REPORTS_DIR / "latest_report.json"
    output_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")

    return {
        "report_path": str(output_path),
        "paper_count": report["paper_count"],
        "claim_count": report["claim_count"],
        "contradiction_count": len(report["contradictions"]),
        "gaps": report["gaps"],
    }


@app.get("/report")
def get_latest_report() -> dict:
    path = REPORTS_DIR / "latest_report.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No report generated yet.")
    return json.loads(path.read_text(encoding="utf-8"))


@app.post("/final-report")
def final_report(payload: FinalReportRequest) -> dict:
    report = build_final_report(
        extracted_dir=EXTRACTED_DIR,
        target_research_finding=payload.target_research_finding.strip(),
        top_k=payload.top_k,
        paper_ids=payload.paper_ids or None,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = REPORTS_DIR / "final_report.json"
    output_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")

    return {
        "report_path": str(output_path),
        "report": report,
    }
