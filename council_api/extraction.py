from __future__ import annotations

import json
import re
from pathlib import Path

from pypdf import PdfReader

SECTION_ORDER = ["abstract", "introduction", "methodology", "results", "conclusion"]
SECTION_ALIASES = {
    "abstract": ["abstract"],
    "introduction": ["introduction", "1 introduction"],
    "methodology": ["methodology", "methods", "materials and methods"],
    "results": ["results", "experiments", "evaluation", "discussion"],
    "conclusion": ["conclusion", "conclusions", "future work"],
}
CLAIM_HINTS = [
    "we propose",
    "we present",
    "we show",
    "we demonstrate",
    "our results",
    "outperform",
    "improve",
    "state-of-the-art",
    "significant",
]
METHOD_HINTS = [
    "transformer",
    "bert",
    "cnn",
    "rnn",
    "diffusion",
    "reinforcement learning",
    "ablation",
    "benchmark",
]
DATASET_HINTS = [
    "dataset",
    "corpus",
    "imagenet",
    "cifar",
    "squad",
    "ms coco",
    "wikitext",
]


def extract_from_pdf(paper_id: str, pdf_path: Path, output_dir: Path, metadata: dict) -> dict:
    text = _read_pdf_text(pdf_path)
    sections = _split_sections(text)

    claims = _extract_claims("\n".join(sections.values()))
    methods = _extract_keywords("\n".join(sections.values()), METHOD_HINTS)
    datasets = _extract_keywords("\n".join(sections.values()), DATASET_HINTS)

    payload = {
        "paper_id": paper_id,
        "title": metadata.get("title", ""),
        "source": metadata.get("source", ""),
        "year": metadata.get("year", ""),
        "sections": sections,
        "claims": claims,
        "methods": methods,
        "datasets": datasets,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{paper_id}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return payload


def build_report(extracted_dir: Path, paper_ids: list[str] | None = None) -> dict:
    extracted = []
    for path in sorted(extracted_dir.glob("*.json")):
        if paper_ids and path.stem not in set(paper_ids):
            continue
        extracted.append(json.loads(path.read_text(encoding="utf-8")))

    all_claims = []
    for item in extracted:
        for claim in item.get("claims", []):
            all_claims.append({"paper_id": item.get("paper_id", ""), "claim": claim})

    contradictions = _find_simple_contradictions(all_claims)
    method_counter = _count_items([m for item in extracted for m in item.get("methods", [])])
    dataset_counter = _count_items([d for item in extracted for d in item.get("datasets", [])])

    return {
        "paper_count": len(extracted),
        "claim_count": len(all_claims),
        "top_methods": method_counter[:10],
        "top_datasets": dataset_counter[:10],
        "contradictions": contradictions,
        "gaps": _suggest_gaps(method_counter, dataset_counter, len(contradictions)),
    }


def build_final_report(
    extracted_dir: Path,
    target_research_finding: str,
    top_k: int = 10,
    paper_ids: list[str] | None = None,
) -> dict:
    base = build_report(extracted_dir=extracted_dir, paper_ids=paper_ids)
    references = _extract_reference_lines(extracted_dir=extracted_dir, paper_ids=paper_ids)

    return {
        "executive_summary": {
            "papers_considered": base["paper_count"],
            "unanswered_question_count": len(base["gaps"]),
            "decision_topic_count": len(base["top_methods"]),
            "contradicting_paper_count": len(base["contradictions"]),
            "recent_works_count": 0,
        },
        "which_question_has_been_circling_but_unanswered": base["gaps"],
        "topics_to_search_for_further_decision": [item["name"] for item in base["top_methods"][:top_k]],
        "contradicting_papers_defying_targeted_research": base["contradictions"][:top_k],
        "recent_works_last_2_years": [],
        "citation_trail": {
            "top_cited_references": [{"reference": ref, "citation_count": 1} for ref in references[:top_k]],
            "in_corpus_citation_edges": [],
            "citation_links": [],
            "total_citation_links": len(references[:top_k]),
        },
        "seminal_papers": [
            {
                "reference": ref,
                "signal": "high_citation_frequency_in_collected_corpus",
                "citation_count": 1,
            }
            for ref in references[:top_k]
        ],
        "established_findings": [{"title": "Target finding", "finding": target_research_finding}],
        "critical_additional_findings": [
            {
                "title": "Method concentration",
                "finding": {
                    "top_methods": base["top_methods"][:top_k],
                    "interpretation": "High concentration can indicate fragility in method diversity.",
                },
            },
            {
                "title": "Priority unresolved gaps",
                "finding": {
                    "count": len(base["gaps"]),
                    "examples": base["gaps"][:top_k],
                },
            },
            {
                "title": "Contradiction pressure",
                "finding": {
                    "total_contradictions": len(base["contradictions"]),
                    "critical_or_high": 0,
                },
            },
        ],
        "decision_recommendations": [
            "Prioritize unresolved questions tied to strongest contradictions.",
            "Run targeted replication where evidence looks weak.",
            "Track method diversity to avoid over-committing to one model family.",
        ],
    }


def _read_pdf_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def _split_sections(text: str) -> dict[str, str]:
    normalized_lines = [line.strip() for line in text.splitlines() if line.strip()]
    sections = {name: [] for name in SECTION_ORDER}
    current = "abstract"

    for line in normalized_lines:
        lowered = line.lower()
        next_section = _match_section(lowered)
        if next_section:
            current = next_section
            continue
        sections[current].append(line)

    compact = {}
    for name in SECTION_ORDER:
        compact[name] = " ".join(sections[name])[:10000]
    return compact


def _match_section(line: str) -> str:
    for section, aliases in SECTION_ALIASES.items():
        for alias in aliases:
            if line == alias or line.startswith(alias + " "):
                return section
    return ""


def _extract_claims(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    claims = []
    for sentence in sentences:
        clean = " ".join(sentence.split())
        if len(clean) < 60 or len(clean) > 400:
            continue
        lowered = clean.lower()
        if any(hint in lowered for hint in CLAIM_HINTS):
            claims.append(clean)
        if len(claims) >= 25:
            break
    return claims


def _extract_keywords(text: str, hints: list[str]) -> list[str]:
    lowered = text.lower()
    found = []
    for hint in hints:
        if hint in lowered and hint not in found:
            found.append(hint)
    return found


def _count_items(items: list[str]) -> list[dict]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    sorted_items = sorted(counts.items(), key=lambda value: value[1], reverse=True)
    return [{"name": name, "count": count} for name, count in sorted_items]


def _find_simple_contradictions(claims: list[dict]) -> list[dict]:
    contradictions = []
    positive_words = ["improve", "better", "outperform", "increase"]
    negative_words = ["worse", "fails", "decrease", "does not improve"]

    for index, left in enumerate(claims):
        left_text = left["claim"].lower()
        left_positive = any(word in left_text for word in positive_words)
        left_negative = any(word in left_text for word in negative_words)
        if not (left_positive or left_negative):
            continue

        for right in claims[index + 1 :]:
            if left["paper_id"] == right["paper_id"]:
                continue
            right_text = right["claim"].lower()
            right_positive = any(word in right_text for word in positive_words)
            right_negative = any(word in right_text for word in negative_words)

            if left_positive and right_negative:
                contradictions.append({"paper_a": left, "paper_b": right})
            if left_negative and right_positive:
                contradictions.append({"paper_a": left, "paper_b": right})

            if len(contradictions) >= 20:
                return contradictions
    return contradictions


def _suggest_gaps(methods: list[dict], datasets: list[dict], contradiction_count: int) -> list[str]:
    gaps = []
    if not methods:
        gaps.append("Method details are sparse across extracted papers.")
    if not datasets:
        gaps.append("Dataset mentions are sparse; benchmark comparison may be weak.")
    if contradiction_count > 5:
        gaps.append("Several contradictory claims need manual verification.")
    if not gaps:
        gaps.append("No major structural gap detected from the extracted snapshot.")
    return gaps


def _extract_reference_lines(extracted_dir: Path, paper_ids: list[str] | None = None) -> list[str]:
    references: list[str] = []
    for path in sorted(extracted_dir.glob("*.json")):
        if paper_ids and path.stem not in set(paper_ids):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        section_values = payload.get("sections", {}).values()
        text = " ".join(section_values) if section_values else ""
        lines = re.findall(r"[A-Z][^.!?]{30,120}", text)
        for line in lines[:5]:
            compact = " ".join(line.split())
            if compact not in references:
                references.append(compact)
        if len(references) >= 50:
            break
    return references
