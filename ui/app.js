const state = {
  debateReader: null,
  aiReader: null,
  busy: false,
};

const viewIds = [
  "home",
  "data-studio",
  "pipeline-builder",
  "investigation",
  "graph-analysis",
  "dashboards",
  "ai-assistant",
];

function qs(id) {
  return document.getElementById(id);
}

function getBaseUrl() {
  const input = qs("apiBaseUrl");
  const fallback = "http://127.0.0.1:8000";
  if (!input) return fallback;
  return (input.value || fallback).trim().replace(/\/+$/, "");
}

function setText(id, payload) {
  const node = qs(id);
  if (!node) return;
  if (typeof payload === "string") {
    node.textContent = payload;
    return;
  }
  node.textContent = JSON.stringify(payload, null, 2);
}

function parseIds(value) {
  return (value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function nowStamp() {
  const d = new Date();
  return d.toLocaleTimeString();
}

function showLoader(title) {
  const overlay = qs("loaderOverlay");
  const logs = qs("loaderLogs");
  const label = qs("loaderTitle");
  const stateBadge = qs("loaderState");

  if (!overlay || !logs || !label || !stateBadge) return;

  overlay.classList.remove("hidden");
  label.textContent = title;
  logs.textContent = "";
  stateBadge.textContent = "RUNNING";
  stateBadge.classList.remove("ok", "err");
}

function logLoader(message) {
  const logs = qs("loaderLogs");
  if (!logs) return;

  logs.textContent += `[${nowStamp()}] ${message}\n`;
  logs.scrollTop = logs.scrollHeight;
}

function finishLoader(ok, message) {
  const stateBadge = qs("loaderState");
  const overlay = qs("loaderOverlay");
  if (!stateBadge || !overlay) return;

  stateBadge.textContent = ok ? "DONE" : "FAILED";
  stateBadge.classList.remove("ok", "err");
  stateBadge.classList.add(ok ? "ok" : "err");
  if (message) logLoader(message);

  if (ok) {
    setTimeout(() => {
      overlay.classList.add("hidden");
    }, 700);
  }
}

async function runWithLogs(title, handler) {
  if (state.busy) {
    return;
  }

  state.busy = true;
  showLoader(title);
  logLoader("Action started.");

  try {
    const result = await handler(logLoader);
    finishLoader(true, "Action completed successfully.");
    return result;
  } catch (error) {
    finishLoader(false, `Action failed: ${String(error)}`);
    throw error;
  } finally {
    state.busy = false;
  }
}

async function api(method, path, body, log) {
  if (log) {
    log(`Preparing ${method} ${path}`);
    if (body) {
      log("Sending JSON payload.");
    }
  }

  const res = await fetch(`${getBaseUrl()}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (log) {
    log(`Received HTTP ${res.status}.`);
  }

  const text = await res.text();
  let data = text;
  try {
    data = text ? JSON.parse(text) : {};
  } catch (_err) {
    data = text;
  }

  if (!res.ok) {
    if (log) {
      log("Backend returned an error response.");
    }
    throw new Error(typeof data === "string" ? data : JSON.stringify(data));
  }

  if (log) {
    log("Response parsed successfully.");
  }
  return data;
}

function switchView(view) {
  for (const id of viewIds) {
    const section = qs(`view-${id}`);
    if (!section) continue;
    section.classList.toggle("hidden", id !== view);
  }

  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === view);
  });
}

function bindNavigation() {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => switchView(item.dataset.view));
  });

  document.querySelectorAll(".card-action").forEach((item) => {
    item.addEventListener("click", () => switchView(item.dataset.open));
  });
}

function renderTable(targetId, rows) {
  const target = qs(targetId);
  if (!target) return;

  if (!Array.isArray(rows) || rows.length === 0) {
    target.innerHTML = "No rows found.";
    return;
  }

  const cols = Object.keys(rows[0]);
  const head = `<thead><tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr></thead>`;
  const body = rows
    .map((row) => `<tr>${cols.map((c) => `<td>${String(row[c] ?? "")}</td>`).join("")}</tr>`)
    .join("");

  target.innerHTML = `<table>${head}<tbody>${body}</tbody></table>`;
}

function renderHeatmapGrid(targetId, payload) {
  const target = qs(targetId);
  if (!target) return;

  if (!payload || !Array.isArray(payload.paper_ids) || !Array.isArray(payload.matrix)) {
    target.textContent = "No heatmap data.";
    return;
  }

  const ids = payload.paper_ids;
  let html = '<table><thead><tr><th>from/to</th>';
  html += ids.map((id) => `<th>${id}</th>`).join("");
  html += "</tr></thead><tbody>";

  payload.matrix.forEach((row, rIdx) => {
    html += `<tr><th>${ids[rIdx] || "-"}</th>`;
    row.forEach((cell) => {
      const contradictionCount = Array.isArray(cell.contradictions) ? cell.contradictions.length : 0;
      const cls = cell.contradicts ? " style='background:#ffe7e3;color:#7b1e17'" : " style='background:#eaf5ec;color:#1f5526'";
      html += `<td${cls}>${cell.contradicts ? `YES (${contradictionCount})` : "NO"}</td>`;
    });
    html += "</tr>";
  });

  html += "</tbody></table>";
  target.innerHTML = html;
}

function renderKpis(report) {
  const el = qs("kpis");
  if (!el) return;

  const paperCount = report?.paper_count ?? 0;
  const claimCount = report?.claim_count ?? 0;
  const contradictionCount = Array.isArray(report?.contradictions) ? report.contradictions.length : 0;
  const gapCount = Array.isArray(report?.gaps) ? report.gaps.length : 0;

  el.innerHTML = [
    ["Papers", paperCount],
    ["Claims", claimCount],
    ["Contradictions", contradictionCount],
    ["Gaps", gapCount],
  ]
    .map(([k, v]) => `<div class='kpi'><div class='k'>${k}</div><div class='v'>${v}</div></div>`)
    .join("");
}

function appendStream(outId, text) {
  const out = qs(outId);
  if (!out) return;
  out.textContent += text;
  out.scrollTop = out.scrollHeight;
}

async function startDebateStream(a, b, outId, stateKey) {
  logLoader("Connecting to /feature/debate stream.");
  const out = qs(outId);
  if (out) out.textContent = "";

  const response = await fetch(`${getBaseUrl()}/feature/debate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paper_id_A: a, paper_id_B: b }),
  });

  if (!response.ok || !response.body) {
    const text = await response.text();
    throw new Error(text || "Failed to start debate stream");
  }

  const reader = response.body.getReader();
  state[stateKey] = reader;
  const decoder = new TextDecoder();
  let chunkCount = 0;

  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    chunkCount += 1;
    if (chunkCount % 25 === 0) {
      logLoader(`Debate stream chunks received: ${chunkCount}`);
    }

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";

    for (const evt of events) {
      const line = evt
        .split("\n")
        .find((item) => item.startsWith("data:"));
      if (!line) continue;
      const dataRaw = line.replace(/^data:\s*/, "");

      if (dataRaw === "[DONE]") {
        appendStream(outId, "\n\n[Debate completed]\n");
        logLoader("Debate stream finished.");
        continue;
      }

      try {
        const data = JSON.parse(dataRaw);
        if (data.token) appendStream(outId, data.token);
        if (data.error) appendStream(outId, `\n[Error] ${data.error}\n`);
      } catch (_err) {
        appendStream(outId, dataRaw);
      }
    }
  }
}

function bindDataStudio() {
  qs("btnHealth")?.addEventListener("click", async () => {
    try {
      const data = await runWithLogs("Health Check", async (log) => api("GET", "/health", null, log));
      setText("healthOut", data);
    } catch (err) {
      setText("healthOut", String(err));
    }
  });

  qs("btnLoadPapers")?.addEventListener("click", async () => {
    try {
      const data = await runWithLogs("Load Papers", async (log) => api("GET", "/papers", null, log));
      renderTable("papersOut", data.papers || []);
    } catch (err) {
      setText("papersOut", String(err));
    }
  });

  qs("btnExtractAllSync")?.addEventListener("click", async () => {
    try {
      const data = await runWithLogs("Extract All (Sync)", async (log) => api("POST", "/extract-all", null, log));
      setText("extractStatusOut", data);
    } catch (err) {
      setText("extractStatusOut", String(err));
    }
  });

  qs("btnExtractAllBg")?.addEventListener("click", async () => {
    try {
      const data = await runWithLogs("Extract All (Background)", async (log) =>
        api("POST", "/extract-all/background", null, log)
      );
      setText("extractStatusOut", data);
    } catch (err) {
      setText("extractStatusOut", String(err));
    }
  });

  qs("btnExtractStatus")?.addEventListener("click", async () => {
    try {
      const data = await runWithLogs("Extract Status", async (log) => api("GET", "/extract-all/status", null, log));
      setText("extractStatusOut", data);
    } catch (err) {
      setText("extractStatusOut", String(err));
    }
  });

  qs("btnExtractOne")?.addEventListener("click", async () => {
    const paperId = (qs("extractPaperId")?.value || "").trim();
    if (!paperId) {
      setText("extractOneOut", "Enter a paper id first.");
      return;
    }

    try {
      const data = await runWithLogs("Extract Single Paper", async (log) =>
        api("POST", `/extract/${paperId}`, null, log)
      );
      setText("extractOneOut", data);
    } catch (err) {
      setText("extractOneOut", String(err));
    }
  });
}

function bindPipelineBuilder() {
  qs("btnCrawlOnly")?.addEventListener("click", async () => {
    const payload = {
      query: (qs("crQuery")?.value || "").trim(),
      question: (qs("crQuestion")?.value || "").trim(),
      topic_count: Number(qs("crTopicCount")?.value || 4),
      limit_per_source: Number(qs("crLimit")?.value || 10),
      max_papers: Number(qs("crMaxPapers")?.value || 20),
      concurrency: Number(qs("crConcurrency")?.value || 6),
    };

    try {
      setText("crawlReportOut", "Running crawl only...");
      const data = await runWithLogs("Crawl Only", async (log) => api("POST", "/crawl", payload, log));
      setText("crawlReportOut", data);
    } catch (err) {
      setText("crawlReportOut", String(err));
    }
  });

  qs("btnCrawlReport")?.addEventListener("click", async () => {
    const payload = {
      query: (qs("crQuery")?.value || "").trim(),
      question: (qs("crQuestion")?.value || "").trim(),
      topic_count: Number(qs("crTopicCount")?.value || 4),
      limit_per_source: Number(qs("crLimit")?.value || 10),
      max_papers: Number(qs("crMaxPapers")?.value || 20),
      concurrency: Number(qs("crConcurrency")?.value || 6),
      target_research_finding: (qs("crTarget")?.value || "").trim(),
      top_k: Number(qs("crTopK")?.value || 10),
    };

    try {
      setText("crawlReportOut", "Running full pipeline...");
      const data = await runWithLogs("Crawl + Report", async (log) => api("POST", "/crawl-report", payload, log));
      setText("crawlReportOut", data);
    } catch (err) {
      setText("crawlReportOut", String(err));
    }
  });

  qs("btnAnalyze")?.addEventListener("click", async () => {
    const ids = parseIds(qs("anPaperIds")?.value || "");
    try {
      const data = await runWithLogs("Analyze", async (log) => api("POST", "/analyze", { paper_ids: ids }, log));
      setText("reportOut", data);
    } catch (err) {
      setText("reportOut", String(err));
    }
  });

  qs("btnGetReport")?.addEventListener("click", async () => {
    try {
      const data = await runWithLogs("Get Latest Report", async (log) => api("GET", "/report", null, log));
      setText("reportOut", data);
    } catch (err) {
      setText("reportOut", String(err));
    }
  });

  qs("btnFinalReport")?.addEventListener("click", async () => {
    const ids = parseIds(qs("anPaperIds")?.value || "");
    const payload = {
      target_research_finding: (qs("frTarget")?.value || "").trim(),
      top_k: Number(qs("frTopK")?.value || 10),
      paper_ids: ids,
    };

    try {
      const data = await runWithLogs("Final Report", async (log) => api("POST", "/final-report", payload, log));
      setText("reportOut", data);
    } catch (err) {
      setText("reportOut", String(err));
    }
  });
}

function bindInvestigation() {
  qs("btnCitation")?.addEventListener("click", async () => {
    const payload = {
      paper_id: (qs("citPaperId")?.value || "").trim(),
      claim_text: (qs("citClaimText")?.value || "").trim(),
    };

    if (!payload.paper_id || !payload.claim_text) {
      setText("citationOut", "Enter paper_id and claim_text.");
      return;
    }

    try {
      const data = await runWithLogs("Citation Jump", async (log) => api("POST", "/feature/citation", payload, log));
      setText("citationOut", data);
    } catch (err) {
      setText("citationOut", String(err));
    }
  });

  qs("btnHeatmap")?.addEventListener("click", async () => {
    const ids = parseIds(qs("heatPaperIds")?.value || "");
    if (ids.length < 2) {
      setText("heatmapOut", "Enter at least two paper ids.");
      return;
    }

    try {
      const data = await runWithLogs("Heatmap", async (log) =>
        api("POST", "/feature/heatmap", { paper_ids: ids }, log)
      );
      renderHeatmapGrid("heatmapOut", data);
    } catch (err) {
      setText("heatmapOut", String(err));
    }
  });

  qs("btnDebate")?.addEventListener("click", async () => {
    const a = (qs("debPaperA")?.value || "").trim();
    const b = (qs("debPaperB")?.value || "").trim();
    if (!a || !b) {
      setText("debateOut", "Enter paper IDs A and B.");
      return;
    }

    try {
      await runWithLogs("Live Debate Stream", async () => startDebateStream(a, b, "debateOut", "debateReader"));
    } catch (err) {
      setText("debateOut", String(err));
    }
  });

  qs("btnDebateStop")?.addEventListener("click", async () => {
    if (state.debateReader) {
      await state.debateReader.cancel();
      state.debateReader = null;
    }
    setText("debateOut", "");
  });
}

function bindGraphAnalysis() {
  qs("btnGraphHeatmap")?.addEventListener("click", async () => {
    const ids = parseIds(qs("graphPaperIds")?.value || "");
    if (ids.length < 2) {
      setText("graphOut", "Enter at least two paper ids.");
      return;
    }

    try {
      const data = await runWithLogs("Graph Heatmap", async (log) =>
        api("POST", "/feature/heatmap", { paper_ids: ids }, log)
      );
      renderHeatmapGrid("graphOut", data);
    } catch (err) {
      setText("graphOut", String(err));
    }
  });
}

function bindDashboards() {
  qs("btnDashboardRefresh")?.addEventListener("click", async () => {
    try {
      const report = await runWithLogs("Dashboard Refresh", async (log) => api("GET", "/report", null, log));
      renderKpis(report);
      setText("dashboardOut", report);
    } catch (err) {
      setText("dashboardOut", String(err));
      renderKpis({});
    }
  });
}

function bindAiAssistant() {
  qs("btnAiAsk")?.addEventListener("click", async () => {
    const question = (qs("aiQuestion")?.value || "").trim();
    const paperIds = parseIds(qs("aiPaperIds")?.value || "");
    if (!question) {
      setText("aiOut", "Enter a question first.");
      return;
    }

    try {
      const payload = { question, paper_ids: paperIds };
      const data = await runWithLogs("AI Assistant Question", async (log) => api("POST", "/feature/ask", payload, log));
      setText("aiOut", data);
    } catch (err) {
      setText("aiOut", String(err));
    }
  });
}

function bindLoaderClose() {
  qs("loaderClose")?.addEventListener("click", () => {
    qs("loaderOverlay")?.classList.add("hidden");
  });
}

function boot() {
  bindNavigation();
  bindDataStudio();
  bindPipelineBuilder();
  bindInvestigation();
  bindGraphAnalysis();
  bindDashboards();
  bindAiAssistant();
  bindLoaderClose();

  switchView("home");
  qs("btnDashboardRefresh")?.click();
}

boot();
