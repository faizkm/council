from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
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


class CrawlAndReportRequest(CrawlRequest):
    target_research_finding: str = Field(default="", description="Main finding to validate")
    top_k: int = Field(default=10, ge=1, le=50)


class ExtractTaskStatus(BaseModel):
    status: str = "idle"
    started_at: str = ""
    finished_at: str = ""
    processed_count: int = 0
    skipped_count: int = 0
    processed: list[dict] = Field(default_factory=list)
    skipped: list[dict] = Field(default_factory=list)
    error: str = ""


extract_all_task_status = ExtractTaskStatus()


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
    return _extract_all_papers_sync()


@app.post("/extract-all/background")
def extract_all_papers_background(background_tasks: BackgroundTasks) -> dict:
    if extract_all_task_status.status == "running":
        raise HTTPException(status_code=409, detail="extract-all background task is already running")

    extract_all_task_status.status = "running"
    extract_all_task_status.error = ""
    extract_all_task_status.started_at = _now_iso()
    extract_all_task_status.finished_at = ""
    extract_all_task_status.processed_count = 0
    extract_all_task_status.skipped_count = 0
    extract_all_task_status.processed = []
    extract_all_task_status.skipped = []

    background_tasks.add_task(_run_extract_all_background)
    return {"status": "accepted", "message": "extract-all started in background"}


@app.get("/extract-all/status")
def extract_all_status() -> dict:
    return extract_all_task_status.model_dump()


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


@app.post("/crawl-report")
async def crawl_report(payload: CrawlAndReportRequest) -> dict:
    query = payload.query.strip()
    question = payload.question.strip()

    if not query and not question:
        raise HTTPException(status_code=422, detail="Provide either query or question.")

    if question:
        crawl_summary = await orchestrator.run_from_question(
            question=question,
            limit_per_source=payload.limit_per_source,
            max_papers=payload.max_papers,
            concurrency=payload.concurrency,
            topic_count=payload.topic_count,
        )
    else:
        crawl_summary = await orchestrator.run(
            query=query,
            limit_per_source=payload.limit_per_source,
            max_papers=payload.max_papers,
            concurrency=payload.concurrency,
        )

    extract_summary = await asyncio.to_thread(_extract_all_papers_sync)

    analyze_report = build_report(EXTRACTED_DIR)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    latest_path = REPORTS_DIR / "latest_report.json"
    latest_path.write_text(json.dumps(analyze_report, ensure_ascii=True, indent=2), encoding="utf-8")

    final_payload = build_final_report(
        extracted_dir=EXTRACTED_DIR,
        target_research_finding=payload.target_research_finding.strip(),
        top_k=payload.top_k,
    )
    final_path = REPORTS_DIR / "final_report.json"
    final_path.write_text(json.dumps(final_payload, ensure_ascii=True, indent=2), encoding="utf-8")

    return {
        "crawl": {
            "query": crawl_summary.query,
            "topics": crawl_summary.topics,
            "discovered": crawl_summary.discovered,
            "deduped": crawl_summary.deduped,
            "attempted": crawl_summary.attempted,
            "saved": crawl_summary.saved,
            "skipped": crawl_summary.skipped,
            "failed": crawl_summary.failed,
        },
        "extract": extract_summary,
        "analyze": {
            "report_path": str(latest_path),
            "paper_count": analyze_report["paper_count"],
            "claim_count": analyze_report["claim_count"],
            "contradiction_count": len(analyze_report["contradictions"]),
        },
        "final_report": {
            "report_path": str(final_path),
            "executive_summary": final_payload.get("executive_summary", {}),
        },
    }


def _extract_all_papers_sync() -> dict:
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


def _run_extract_all_background() -> None:
    try:
        result = _extract_all_papers_sync()
        extract_all_task_status.status = "completed"
        extract_all_task_status.processed_count = result["processed_count"]
        extract_all_task_status.skipped_count = result["skipped_count"]
        extract_all_task_status.processed = result["processed"]
        extract_all_task_status.skipped = result["skipped"]
    except Exception as exc:  # noqa: BLE001
        extract_all_task_status.status = "failed"
        extract_all_task_status.error = str(exc)
    finally:
        extract_all_task_status.finished_at = _now_iso()


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
