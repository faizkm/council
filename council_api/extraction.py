from __future__ import annotations

import json
import os
import re
from pathlib import Path

import httpx
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
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
_GROQ_KEY_CURSOR = 0
STOPWORDS = {
    "about",
    "after",
    "also",
    "among",
    "been",
    "between",
    "both",
    "from",
    "have",
    "into",
    "more",
    "most",
    "only",
    "other",
    "over",
    "such",
    "than",
    "that",
    "their",
    "there",
    "these",
    "those",
    "very",
    "with",
}


def extract_from_pdf(paper_id: str, pdf_path: Path, output_dir: Path, metadata: dict) -> dict:
    text = _read_pdf_text(pdf_path)
    sections = _split_sections(text)
    abstract_intro = "\n".join(
        [
            sections.get("abstract", ""),
            sections.get("introduction", ""),
        ]
    ).strip()
    llm_extraction = _extract_with_groq(
        title=metadata.get("title", ""),
        text=abstract_intro,
    )
    combined_text = "\n".join(sections.values())

    claims = llm_extraction.get("claims", []) or _extract_claims(combined_text)
    methods = llm_extraction.get("methods", []) or _extract_keywords(combined_text, METHOD_HINTS)
    datasets = llm_extraction.get("datasets", []) or _extract_keywords(combined_text, DATASET_HINTS)
    references = _extract_reference_candidates(text)

    payload = {
        "paper_id": paper_id,
        "title": metadata.get("title", ""),
        "source": metadata.get("source", ""),
        "year": metadata.get("year", ""),
        "sections": sections,
        "claims": claims,
        "methods": methods,
        "datasets": datasets,
        "references": references,
        "extraction_model": llm_extraction.get("model", ""),
        "extraction_mode": llm_extraction.get("mode", "heuristic"),
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

    contradictions = _find_contradictions(all_claims)
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
    extracted_items = _load_extracted_items(extracted_dir=extracted_dir, paper_ids=paper_ids)
    references = _extract_reference_lines_from_items(extracted_items)
    reference_counter = _count_items(references)
    recent_works = _recent_works(extracted_items)
    citation_edges = _build_in_corpus_edges(extracted_items)
    decision_recommendations = _build_decision_recommendations(
        contradiction_count=len(base["contradictions"]),
        gap_count=len(base["gaps"]),
        method_count=len(base["top_methods"]),
        recent_count=len(recent_works),
    )

    return {
        "executive_summary": {
            "papers_considered": base["paper_count"],
            "unanswered_question_count": len(base["gaps"]),
            "decision_topic_count": len(base["top_methods"]),
            "contradicting_paper_count": len(base["contradictions"]),
            "recent_works_count": len(recent_works),
        },
        "which_question_has_been_circling_but_unanswered": base["gaps"],
        "topics_to_search_for_further_decision": [item["name"] for item in base["top_methods"][:top_k]],
        "contradicting_papers_defying_targeted_research": base["contradictions"][:top_k],
        "recent_works_last_2_years": recent_works,
        "citation_trail": {
            "top_cited_references": [
                {"reference": item["name"], "citation_count": item["count"]}
                for item in reference_counter[:top_k]
            ],
            "in_corpus_citation_edges": citation_edges[:top_k],
            "citation_links": citation_edges,
            "total_citation_links": len(citation_edges),
        },
        "seminal_papers": [
            {
                "reference": item["name"],
                "signal": "high_citation_frequency_in_collected_corpus",
                "citation_count": item["count"],
            }
            for item in reference_counter[:top_k]
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
        "decision_recommendations": decision_recommendations,
        "structured_debates": _load_recent_debates(),
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


def _find_contradictions(claims: list[dict]) -> list[dict]:
    llm_items = _find_contradictions_with_groq(claims)
    if llm_items:
        return llm_items
    return _find_simple_contradictions(claims)


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


def _load_extracted_items(extracted_dir: Path, paper_ids: list[str] | None = None) -> list[dict]:
    extracted: list[dict] = []
    for path in sorted(extracted_dir.glob("*.json")):
        if paper_ids and path.stem not in set(paper_ids):
            continue
        extracted.append(json.loads(path.read_text(encoding="utf-8")))
    return extracted


def _extract_reference_lines(extracted_dir: Path, paper_ids: list[str] | None = None) -> list[str]:
    return _extract_reference_lines_from_items(_load_extracted_items(extracted_dir, paper_ids))


def _extract_reference_lines_from_items(items: list[dict]) -> list[str]:
    references: list[str] = []
    for payload in items:
        for candidate in payload.get("references", []):
            compact = " ".join(str(candidate).split())
            if compact and compact not in references:
                references.append(compact)
        if len(references) >= 200:
            return references

        section_values = payload.get("sections", {}).values()
        text = " ".join(section_values) if section_values else ""
        for line in _extract_reference_candidates(text):
            if line not in references:
                references.append(line)
            if len(references) >= 200:
                return references

    return references


def _extract_with_groq(title: str, text: str) -> dict:
    if not _groq_api_keys() or not text.strip():
        return {"mode": "heuristic", "claims": [], "methods": [], "datasets": []}

    trimmed_text = text[:12000]
    prompt = (
        "Extract research signals from paper text. Return JSON only with schema "
        "{\"claims\": [string], \"methods\": [string], \"datasets\": [string]}. "
        "Use concise phrases, max 8 items per list, no duplicates.\n"
        f"Title: {title}\n"
        f"Text:\n{trimmed_text}"
    )

    payload = _groq_chat(
        messages=[
            {"role": "system", "content": "Return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=450,
    )
    if not payload:
        return {"mode": "heuristic", "claims": [], "methods": [], "datasets": []}

    content = _extract_chat_content(payload)
    parsed = _parse_json_object(content)
    if not parsed:
        return {"mode": "heuristic", "claims": [], "methods": [], "datasets": []}

    return {
        "mode": "groq",
        "model": payload.get("model", ""),
        "claims": _sanitize_text_list(parsed.get("claims", []), max_items=25, max_chars=420),
        "methods": _sanitize_text_list(parsed.get("methods", []), max_items=15, max_chars=120),
        "datasets": _sanitize_text_list(parsed.get("datasets", []), max_items=15, max_chars=120),
    }


def _find_contradictions_with_groq(claims: list[dict]) -> list[dict]:
    if not _groq_api_keys():
        return []

    candidate_pairs: list[dict] = []
    max_checks = 40
    for index, left in enumerate(claims):
        for right in claims[index + 1 :]:
            if left.get("paper_id") == right.get("paper_id"):
                continue
            if not _claims_are_related(left.get("claim", ""), right.get("claim", "")):
                continue
            candidate_pairs.append({"paper_a": left, "paper_b": right})
            if len(candidate_pairs) >= max_checks:
                break
        if len(candidate_pairs) >= max_checks:
            break

    if not candidate_pairs:
        return []

    verdicts = _batched_contradiction_verdicts(candidate_pairs=candidate_pairs)
    if not verdicts:
        return []

    by_index: dict[int, dict] = {}
    for item in verdicts:
        raw_index = item.get("index")
        if isinstance(raw_index, int):
            by_index[raw_index] = item

    contradictions: list[dict] = []
    for pair_index, pair in enumerate(candidate_pairs):
        verdict = by_index.get(pair_index, {})
        if not bool(verdict.get("contradiction", False)):
            continue
        contradictions.append(
            {
                "paper_a": pair["paper_a"],
                "paper_b": pair["paper_b"],
                "reason": str(verdict.get("reason", "")).strip()[:300],
                "mode": "groq",
            }
        )
        if len(contradictions) >= 20:
            break

    return contradictions


def _batched_contradiction_verdicts(candidate_pairs: list[dict]) -> list[dict]:
    pair_lines = []
    for index, pair in enumerate(candidate_pairs):
        left = pair["paper_a"]
        right = pair["paper_b"]
        pair_lines.append(
            {
                "index": index,
                "paper_a_id": left.get("paper_id", ""),
                "paper_b_id": right.get("paper_id", ""),
                "claim_a": left.get("claim", ""),
                "claim_b": right.get("claim", ""),
            }
        )

    compact_pairs = json.dumps(pair_lines, ensure_ascii=True)
    prompt = (
        "For each pair of claims, decide whether the claims directly contradict each other on the same topic. "
        "Be strict and only mark true for explicit conflict. "
        "Return JSON only with schema {\"pairs\": [{\"index\": int, \"contradiction\": boolean, \"reason\": string}]}.\n"
        f"Pairs JSON:\n{compact_pairs}"
    )

    payload = _groq_chat(
        messages=[
            {
                "role": "system",
                "content": "Return valid JSON only. Keep reasons short and factual.",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=1200,
    )
    if not payload:
        return []

    content = _extract_chat_content(payload)
    parsed = _parse_json_object(content)
    if not parsed:
        return []

    pairs_obj = parsed.get("pairs", [])
    if not isinstance(pairs_obj, list):
        return []

    verdicts: list[dict] = []
    for item in pairs_obj:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        contradiction = bool(item.get("contradiction", False))
        reason = str(item.get("reason", "")).strip()[:300]
        if not isinstance(index, int):
            continue
        verdicts.append(
            {
                "index": index,
                "contradiction": contradiction,
                "reason": reason,
            }
        )
    return verdicts


def _groq_chat(messages: list[dict], max_tokens: int) -> dict | None:
    model = os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    keys = _groq_api_keys()
    if not keys:
        return None

    with httpx.Client(timeout=25.0) as client:
        for _ in range(len(keys)):
            api_key = _next_groq_api_key(keys)
            try:
                response = client.post(
                    GROQ_URL,
                    headers={
                        "authorization": f"Bearer {api_key}",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model,
                        "temperature": 0,
                        "max_tokens": max_tokens,
                        "response_format": {"type": "json_object"},
                        "messages": messages,
                    },
                )
                if response.status_code == 429 or response.status_code >= 500:
                    continue
                response.raise_for_status()
                payload = response.json()
            except Exception:  # noqa: BLE001
                continue

            if isinstance(payload, dict):
                return payload

    return None


def _groq_api_keys() -> list[str]:
    pooled = os.getenv("GROQ_API_KEYS", "")
    keys = [item.strip() for item in pooled.split(",") if item.strip()]

    single = os.getenv("GROQ_API_KEY", "").strip()
    if single and single not in keys:
        keys.append(single)

    return keys


def _next_groq_api_key(keys: list[str]) -> str:
    global _GROQ_KEY_CURSOR
    key = keys[_GROQ_KEY_CURSOR % len(keys)]
    _GROQ_KEY_CURSOR += 1
    return key


def _extract_chat_content(payload: dict) -> str:
    choices = payload.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""

    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    if not isinstance(message, dict):
        return ""

    content = message.get("content", "")
    return content if isinstance(content, str) else ""


def _parse_json_object(text: str) -> dict | None:
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    return parsed if isinstance(parsed, dict) else None


def _sanitize_text_list(items: list, max_items: int, max_chars: int) -> list[str]:
    clean: list[str] = []
    for item in items:
        text = " ".join(str(item).split())
        if not text or text in clean:
            continue
        clean.append(text[:max_chars])
        if len(clean) >= max_items:
            break
    return clean


def _extract_reference_candidates(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    references: list[str] = []

    patterns = [
        re.compile(r"^\[\d+\]\s+.+"),
        re.compile(r"^[A-Z][A-Za-z\-\s,.'&]+\(?(19|20)\d{2}\)?.+"),
    ]

    for line in lines:
        normalized = " ".join(line.split())
        if len(normalized) < 25 or len(normalized) > 260:
            continue
        if any(pattern.match(normalized) for pattern in patterns) and normalized not in references:
            references.append(normalized)
        if len(references) >= 80:
            break
    return references


def _recent_works(items: list[dict]) -> list[dict]:
    years = []
    for item in items:
        year_str = str(item.get("year", "")).strip()
        if year_str.isdigit():
            years.append(int(year_str))
    if not years:
        return []

    latest = max(years)
    threshold = latest - 1
    recent = []
    for item in items:
        year_str = str(item.get("year", "")).strip()
        if not year_str.isdigit():
            continue
        year = int(year_str)
        if year >= threshold:
            recent.append(
                {
                    "paper_id": item.get("paper_id", ""),
                    "title": item.get("title", ""),
                    "year": year_str,
                    "source": item.get("source", ""),
                }
            )
    return recent


def _build_in_corpus_edges(items: list[dict]) -> list[dict]:
    by_title: dict[str, str] = {}
    for item in items:
        title = str(item.get("title", "")).strip().lower()
        paper_id = str(item.get("paper_id", "")).strip()
        if title and paper_id:
            by_title[title] = paper_id

    edges: list[dict] = []
    for item in items:
        source_id = str(item.get("paper_id", "")).strip()
        if not source_id:
            continue
        for ref in item.get("references", []):
            ref_lower = str(ref).lower()
            for title, target_id in by_title.items():
                if target_id == source_id:
                    continue
                if title and title in ref_lower:
                    edge = {"source_paper_id": source_id, "target_paper_id": target_id}
                    if edge not in edges:
                        edges.append(edge)
    return edges


def _build_decision_recommendations(
    contradiction_count: int,
    gap_count: int,
    method_count: int,
    recent_count: int,
) -> list[str]:
    recommendations: list[str] = []

    if contradiction_count > 0:
        recommendations.append("Prioritize replication studies for claims flagged as contradictory.")
    if gap_count > 0:
        recommendations.append("Address top unanswered questions before locking product direction.")
    if method_count <= 2:
        recommendations.append("Expand method diversity to reduce single-approach risk.")
    if recent_count == 0:
        recommendations.append("Add newer papers to reduce stale evidence risk.")

    if not recommendations:
        recommendations.append("Current evidence appears aligned; proceed with targeted validation experiments.")

    return recommendations


def _claims_are_related(left: str, right: str) -> bool:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens or not right_tokens:
        return False
    return len(left_tokens.intersection(right_tokens)) >= 1


def _token_set(text: str) -> set[str]:
    tokens = re.findall(r"[a-z]{5,}", text.lower())
    return {token for token in tokens if token not in STOPWORDS}


def _load_recent_debates() -> list[dict]:
    """Load recent structured debate results from disk."""
    root_dir = Path(__file__).resolve().parents[1]
    data_dir = root_dir / "data"
    debates_dir = data_dir / "debates"

    if not debates_dir.exists():
        return []

    debates = []
    for debate_file in sorted(debates_dir.glob("*.json"), reverse=True)[:5]:  # Last 5
        try:
            debate_data = json.loads(debate_file.read_text(encoding="utf-8"))
            verdict = debate_data.get("verdict_card", {})
            debates.append({
                "file": debate_file.name,
                "paper_A": debate_data.get("paper_A", {}),
                "paper_B": debate_data.get("paper_B", {}),
                "winner": verdict.get("winner"),
                "total_score_A": verdict.get("total_score_A"),
                "total_score_B": verdict.get("total_score_B"),
                "narrative": verdict.get("narrative", ""),
            })
        except Exception:
            pass

    return debates
