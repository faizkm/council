# Council Backend (Hackathon MVP)

This backend now supports a simple end-to-end flow:

- discover papers and download PDFs
- extract basic sections/claims/method keywords from PDFs
- generate a lightweight cross-paper analysis report

## Architecture

- `council_api/main.py`: FastAPI app and endpoints
- `council_api/extraction.py`: PDF extraction + simple report logic
- `research_crawler/`: reused discovery/downloader modules

## Stable ID

`paper_id = sha1(doi or normalized_title)[:16]` with `paper_` prefix.

This keeps PDF and metadata filenames stable for parser-team handoff.

## Metadata Schema

Each metadata file contains:

- `title`
- `authors`
- `doi`
- `year`
- `source`
- `pdf_url`
- `pdf_path`

## Run

Install dependencies:

```bash
pip install -r requirements.txt
```

Recommended on Windows when a global `pip` is also installed:

```bash
python -m pip install -r requirements.txt
```

Create `.env` from `.env.example` in the project root and set keys:

```bash
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.3-70b-versatile
CRAWL4AI_ENABLED=0
```

Both CLI and API auto-load `.env`.

`CRAWL4AI_ENABLED` is optional and defaults to `0` (off). This is recommended on Windows to avoid occasional subprocess teardown noise from browser-based crawling. Set it to `1` only when you want crawl4ai link discovery.

Start API:

```bash
uvicorn app:app --reload
```

Call crawl API:

```bash
curl -X POST http://127.0.0.1:8000/crawl \
  -H "Content-Type: application/json" \
  -d '{"query":"graph neural networks", "limit_per_source":10, "max_papers":20, "concurrency":6}'
```

List downloaded papers:

```bash
curl http://127.0.0.1:8000/papers
```

Extract one paper after crawl:

```bash
curl -X POST http://127.0.0.1:8000/extract/paper_1234567890abcdef
```

Analyze extracted papers:

```bash
curl -X POST http://127.0.0.1:8000/analyze \
   -H "Content-Type: application/json" \
   -d '{"paper_ids":[]}'
```

Read latest report:

```bash
curl http://127.0.0.1:8000/report
```

Run CLI (same pipeline, no parsing):

```bash
python -m research_crawler "graph neural networks" --max-papers 20 --concurrency 6
```

Question mode with Groq topic planning:

```bash
python -m research_crawler --question "How can graph neural networks improve traffic forecasting in smart cities?" --topic-count 4 --max-papers 20
```

Print JSON summary:

```bash
python -m research_crawler "10.48550/arXiv.1706.03762" --output-json
```

Question mode via API:

```bash
curl -X POST http://127.0.0.1:8000/crawl \
   -H "Content-Type: application/json" \
   -d '{"question":"How can graph neural networks improve traffic forecasting in smart cities?", "topic_count":4, "max_papers":20, "concurrency":6}'
```

## Data Output

The API writes:

```text
data/
   pdf/
      paper_001.pdf
      paper_002.pdf

   metadata/
      paper_001.json
      paper_002.json

   extracted/
      paper_001.json
      paper_002.json

   reports/
      latest_report.json
```
# council
# council
# council
