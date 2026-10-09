const chat = document.getElementById("chat");
const chatEmpty = document.getElementById("chatEmpty");
const statusTag = document.getElementById("statusTag");
const statusMeta = document.getElementById("statusMeta");
const statusStepper = document.getElementById("statusStepper");
const appRoot = document.querySelector(".app");
const envStatus = document.getElementById("envStatus");
const questionInput = document.getElementById("question");
const sendBtn = document.getElementById("sendBtn");
const provider = document.getElementById("provider");
const apiKey = document.getElementById("apiKey");
const toggleApiKey = document.getElementById("toggleApiKey");
const topK = document.getElementById("topK");
const topKBadge = document.getElementById("topKBadge");
const resetBtn = document.getElementById("resetBtn");
const schemaToggle = document.getElementById("schemaToggle");
const schemaBlock = document.getElementById("schemaBlock");
const table = document.getElementById("table");
const resultLabel = document.getElementById("resultLabel");
const typingIndicator = document.getElementById("typingIndicator");
const errorCard = document.getElementById("errorCard");
const errorMessage = document.getElementById("errorMessage");
const errorTrace = document.getElementById("errorTrace");
const errorRetryBtn = document.getElementById("errorRetryBtn");
const sqlEditorElement = document.getElementById("sqlEditor");
const copySqlBtn = document.getElementById("copySqlBtn");
const rerunSqlBtn = document.getElementById("rerunSqlBtn");
const sqlHint = document.getElementById("sqlHint");
const downloadCsvBtn = document.getElementById("downloadCsvBtn");
const toolbarCopySqlBtn = document.getElementById("toolbarCopySqlBtn");
const shareLinkBtn = document.getElementById("shareLinkBtn");
const fullscreenBtn = document.getElementById("fullscreenBtn");
const configToggle = document.getElementById("configToggle");
const mobileConfigToggle = document.getElementById("mobileConfigToggle");
const mobileResultsToggle = document.getElementById("mobileResultsToggle");
const examplesBtn = document.getElementById("examplesBtn");
const examplesPopover = document.getElementById("examplesPopover");
const examplesList = document.getElementById("examplesList");

const pipelineSteps = [
  { key: "retrieve_schema", label: "Retrieve schemas" },
  { key: "generate_sql", label: "Generate SQL" },
  { key: "execute_sql", label: "Execute SQL" },
  { key: "self_correct", label: "Self-correct (if needed)" },
  { key: "generate_visual_and_summary", label: "Generate output" },
  { key: "graceful_failure", label: "Graceful failure" },
];

const CHART_TYPE_LABELS = {
  bar: "📊 Bar",
  line: "📈 Line",
  pie: "🥧 Pie",
  histogram: "📉 Histogram",
  table: "🗃 Table",
  metric: "🔢 KPI",
};

const exampleCarousel = [
  "Which department has the highest average salary?",
  "Show total project budget by department.",
  "How many employees are on leave by department?",
  "List active projects and their start dates.",
  "Top 5 cities by employee count.",
  "Average bonus by pay grade.",
];

const exampleTemplates = [
  "Which department has the highest average salary?",
  "Show total project budget by department.",
  "How many employees are on leave by department?",
  "List active projects with assigned employee count.",
  "Average base salary by job title.",
  "Top 5 cities by employee count.",
  "Projects ending this year with total budget.",
  "Employees hired after 2022 by department.",
  "Average bonus by pay grade.",
  "Department headcount and average salary.",
];

let lastQuestion = "";
let lastSchema = "";
let lastResult = null;
let sqlEditor = null;
let originalSql = "";
let markedLines = [];
let resultsHistory = [];
let activeResultIndex = -1;
let turnCount = 0;
let carouselIndex = 0;

function setStatus(tagText, state) {
  statusTag.textContent = tagText;
  if (state === "error") {
    envStatus.textContent = "Attention";
    envStatus.style.color = "var(--error)";
    envStatus.style.background = "rgba(248, 113, 113, 0.18)";
  } else {
    envStatus.textContent = "Ready";
    envStatus.style.color = "var(--accent)";
    envStatus.style.background = "rgba(212, 169, 77, 0.18)";
  }
}

function updateTopKBadge() {
  const min = Number(topK.min);
  const max = Number(topK.max);
  const value = Number(topK.value);
  const percent = (value - min) / (max - min);
  topKBadge.textContent = value;
  const sliderWidth = topK.offsetWidth || 1;
  const thumbOffset = 18;
  const left = percent * (sliderWidth - thumbOffset) + thumbOffset / 2;
  topKBadge.style.left = `${left}px`;
}

function setCardOpen(cardId, open) {
  const card = document.querySelector(`[data-card="${cardId}"]`);
  if (!card) return;
  card.classList.toggle("collapsed", !open);
  card.dataset.collapsed = open ? "false" : "true";
  const toggle = card.querySelector(".card-toggle");
  if (toggle) {
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.textContent = open ? "Collapse" : "Expand";
  }
}

function syncCardToggles() {
  document.querySelectorAll(".card").forEach((card) => {
    const collapsed = card.dataset.collapsed === "true";
    card.classList.toggle("collapsed", collapsed);
    const toggle = card.querySelector(".card-toggle");
    if (toggle) {
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      toggle.textContent = collapsed ? "Expand" : "Collapse";
    }
  });
}

function renderStepper(statusUpdates, finalStatus) {
  statusStepper.innerHTML = "";
  const updateMap = new Map();
  statusUpdates.forEach((update) => {
    updateMap.set(update.node, update);
  });
  const lastUpdate = statusUpdates[statusUpdates.length - 1];
  pipelineSteps.forEach((step) => {
    const li = document.createElement("li");
    li.className = "step";
    const update = updateMap.get(step.key);
    const isLast = lastUpdate && lastUpdate.node === step.key;
    if (update) {
      li.classList.add(isLast ? "active" : "complete");
    } else {
      li.classList.add("pending");
    }

    const dot = document.createElement("span");
    dot.className = "step-dot";
    const label = document.createElement("span");
    label.className = "step-label";
    label.textContent = step.label;
    li.appendChild(dot);
    li.appendChild(label);

    if (update && !isLast && typeof update.elapsed_s === "number") {
      const time = document.createElement("span");
      time.className = "step-time";
      time.textContent = `${update.elapsed_s}s`;
      li.appendChild(time);
    }

    statusStepper.appendChild(li);
  });
}

function formatRelativeTime(timestamp) {
  const seconds = Math.floor((Date.now() - timestamp) / 1000);
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function updateRelativeTimes() {
  document.querySelectorAll("[data-time]").forEach((node) => {
    const timestamp = Number(node.dataset.time || "0");
    if (!timestamp) return;
    node.textContent = formatRelativeTime(timestamp);
  });
}

function setConfigCollapsed(collapsed) {
  if (!appRoot || !configToggle) return;
  appRoot.classList.toggle("app--collapsed-left", collapsed);
  configToggle.setAttribute("aria-pressed", collapsed ? "true" : "false");
  configToggle.setAttribute(
    "aria-label",
    collapsed ? "Expand sidebar" : "Collapse sidebar",
  );
}

// ── Mobile sidebar backdrop ─────────────────────────────────────────
const backdrop = document.createElement("div");
backdrop.className = "sidebar-backdrop";
document.body.appendChild(backdrop);

function closeMobileSidebars() {
  appRoot.classList.remove("app--config-visible");
  appRoot.classList.remove("app--results-visible");
  backdrop.classList.remove("visible");
}

mobileConfigToggle.addEventListener("click", () => {
  const opening = !appRoot.classList.contains("app--config-visible");
  closeMobileSidebars();
  if (opening) {
    appRoot.classList.add("app--config-visible");
    backdrop.classList.add("visible");
  }
});

mobileResultsToggle.addEventListener("click", () => {
  const opening = !appRoot.classList.contains("app--results-visible");
  closeMobileSidebars();
  if (opening) {
    appRoot.classList.add("app--results-visible");
    backdrop.classList.add("visible");
  }
});

backdrop.addEventListener("click", closeMobileSidebars);

function createTurn(questionText, index) {
  const turn = document.createElement("div");
  turn.className = "turn";
  turn.dataset.turn = String(index);

  const userMessage = document.createElement("div");
  userMessage.className = "message user";
  const userMeta = document.createElement("div");
  userMeta.className = "message-meta";
  const badge = document.createElement("a");
  badge.className = "query-badge";
  badge.href = "#resultsPanel";
  badge.textContent = `Query #${index}`;
  badge.addEventListener("click", (event) => {
    event.preventDefault();
    renderResult(index - 1);
    document
      .getElementById("resultsPanel")
      .scrollIntoView({ behavior: "smooth" });
  });
  const timeStamp = document.createElement("span");
  timeStamp.dataset.time = String(Date.now());
  timeStamp.textContent = formatRelativeTime(Number(timeStamp.dataset.time));
  userMeta.appendChild(badge);
  userMeta.appendChild(timeStamp);
  const userText = document.createElement("div");
  userText.textContent = questionText;
  userMessage.appendChild(userMeta);
  userMessage.appendChild(userText);

  const assistantMessage = document.createElement("div");
  assistantMessage.className = "message assistant";
  const assistantMeta = document.createElement("div");
  assistantMeta.className = "message-meta";
  const assistantLabel = document.createElement("span");
  assistantLabel.textContent = "Assistant";
  const assistantTime = document.createElement("span");
  assistantTime.dataset.time = String(Date.now());
  assistantTime.textContent = formatRelativeTime(
    Number(assistantTime.dataset.time),
  );
  assistantMeta.appendChild(assistantLabel);
  assistantMeta.appendChild(assistantTime);
  const assistantText = document.createElement("div");
  assistantText.className = "assistant-text";
  assistantText.classList.add("hidden");

  const assistantLoading = document.createElement("div");
  assistantLoading.className = "assistant-loading";
  assistantLoading.innerHTML = `
    <div class="typing">
      <span class="dot"></span>
      <span class="dot"></span>
      <span class="dot"></span>
      <span>Assistant is thinking...</span>
    </div>
  `;
  const summaryBlock = document.createElement("div");
  summaryBlock.className = "assistant-block assistant-summary";
  const summaryBody = document.createElement("div");
  summaryBody.className = "summary";
  summaryBlock.appendChild(summaryBody);

  const chartBlock = document.createElement("div");
  chartBlock.className = "assistant-block assistant-chart";
  const chartBody = document.createElement("div");
  chartBody.className = "chart";
  chartBlock.appendChild(chartBody);

  const confidenceBlock = document.createElement("div");
  confidenceBlock.className = "assistant-block assistant-confidence";
  const confidenceBody = document.createElement("div");
  confidenceBlock.appendChild(confidenceBody);

  assistantText.appendChild(summaryBlock);
  assistantText.appendChild(chartBlock);
  assistantText.appendChild(confidenceBlock);
  assistantMessage.appendChild(assistantMeta);
  assistantMessage.appendChild(assistantLoading);
  assistantMessage.appendChild(assistantText);

  turn.appendChild(userMessage);
  turn.appendChild(assistantMessage);
  chat.appendChild(turn);
  chat.scrollTop = chat.scrollHeight;
  chatEmpty.style.display = "none";

  return {
    summaryBody,
    chartBody,
    confidenceBody,
    assistantText,
    assistantLoading,
  };
}

function setAssistantReady(turn) {
  if (!turn) return;
  if (turn.assistantLoading) {
    turn.assistantLoading.remove();
  }
  if (turn.assistantText) {
    turn.assistantText.classList.remove("hidden");
  }
}

function buildTable(result) {
  if (!result || !result.columns || !result.rows) {
    table.innerHTML = '<div class="empty">No rows returned.</div>';
    return;
  }

  const tableEl = document.createElement("table");
  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  result.columns.forEach((col) => {
    const th = document.createElement("th");
    th.textContent = col;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  tableEl.appendChild(thead);

  const tbody = document.createElement("tbody");
  result.rows.forEach((row) => {
    const tr = document.createElement("tr");
    row.forEach((cell) => {
      const td = document.createElement("td");
      td.textContent = cell === null ? "" : String(cell);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  tableEl.appendChild(tbody);

  table.innerHTML = "";
  table.appendChild(tableEl);
}

function renderAssistantSummary(target, result) {
  if (!target) return;
  const text =
    result.summary ||
    (result.error ? result.error.message : "No summary returned.");
  target.textContent = text;
}

function renderConfidence(target, score, explanation) {
  if (!target) return;
  target.innerHTML = "";
  const wrapper = document.createElement("div");
  wrapper.className = "confidence";

  const scoreBlock = document.createElement("div");
  const meta = document.createElement("div");
  meta.className = "card-meta";
  meta.textContent = "Confidence score";
  const scoreValue = document.createElement("div");
  scoreValue.className = "confidence-score";

  let percent = 0;
  if (typeof score === "number" && Number.isFinite(score)) {
    if (score <= 1) {
      percent = Math.max(0, Math.min(1, score)) * 100;
    } else {
      percent = Math.max(0, Math.min(100, score));
    }
    scoreValue.textContent = `${Math.round(percent)}%`;
  } else {
    scoreValue.textContent = "--";
  }

  scoreBlock.appendChild(meta);
  scoreBlock.appendChild(scoreValue);

  const bar = document.createElement("div");
  bar.className = "confidence-bar";
  const fill = document.createElement("span");
  fill.style.width = `${percent}%`;
  bar.appendChild(fill);

  wrapper.appendChild(scoreBlock);
  wrapper.appendChild(bar);

  const explanationText = document.createElement("p");
  explanationText.className = "explanation";
  explanationText.textContent =
    explanation || "Confidence details will appear after execution.";

  target.appendChild(wrapper);
  target.appendChild(explanationText);
}

function renderChart(target, figure) {
  if (!target) return;
  if (!figure || !figure.data) {
    target.innerHTML = '<div class="empty">No chart available.</div>';
    return;
  }
  Plotly.newPlot(target, figure.data, figure.layout || {}, {
    displaylogo: false,
    responsive: true,
  });
}

function pulseStepper(activeNode) {
  statusStepper.querySelectorAll(".step").forEach((step) => {
    const dot = step.querySelector(".step-dot");
    if (!dot) return;
    if (step.classList.contains("active")) {
      dot.classList.add("pulsing");
    } else {
      dot.classList.remove("pulsing");
    }
  });
}

function renderHistoryList() {
  const historyList = document.getElementById("historyList");
  if (!historyList) return;

  if (resultsHistory.length === 0) {
    historyList.innerHTML = '<li class="history-empty">No queries yet</li>';
    return;
  }

  historyList.innerHTML = "";
  [...resultsHistory].reverse().forEach((result, reversedIndex) => {
    const realIndex = resultsHistory.length - 1 - reversedIndex;
    const li = document.createElement("li");
    li.className =
      "history-item" + (realIndex === activeResultIndex ? " active" : "");

    const statusIcon = result.error ? "❌" : "✅";
    const qText =
      (result.question || "").slice(0, 46) +
      ((result.question || "").length > 46 ? "…" : "");
    const timeText = formatRelativeTime(result.timestamp || Date.now());

    li.innerHTML = `
      <span class="history-status">${statusIcon}</span>
      <div class="history-info">
        <span class="history-query">${qText}</span>
        <span class="history-time">${timeText}</span>
      </div>
    `;

    li.addEventListener("click", () => {
      renderResult(realIndex);
      document
        .getElementById("resultsPanel")
        ?.scrollIntoView({ behavior: "smooth" });
      renderHistoryList();
    });

    historyList.appendChild(li);
  });
}

function renderChartInPane(pane, figure) {
  if (!figure || !figure.data) {
    pane.innerHTML = '<div class="empty">No data for this chart type.</div>';
    return;
  }
  Plotly.newPlot(pane, figure.data, figure.layout || {}, {
    displaylogo: false,
    responsive: true,
  });
}

function renderMultiChart(container, figures, autoChartType) {
  if (!container) return;
  container.innerHTML = "";

  const types = Object.keys(figures || {});
  if (types.length === 0) {
    container.innerHTML = '<div class="empty">No chart available.</div>';
    return;
  }

  const activeType =
    autoChartType && types.includes(autoChartType) ? autoChartType : types[0];

  const tabBar = document.createElement("div");
  tabBar.className = "chart-tab-bar";

  const paneContainer = document.createElement("div");
  paneContainer.className = "chart-panes";

  types.forEach((type) => {
    const btn = document.createElement("button");
    btn.className = "chart-tab-btn" + (type === activeType ? " active" : "");
    btn.type = "button";
    btn.textContent = CHART_TYPE_LABELS[type] || type;

    const pane = document.createElement("div");
    pane.className = "chart-tab-pane" + (type === activeType ? " active" : "");

    let rendered = false;
    if (type === activeType) {
      renderChartInPane(pane, figures[type]);
      rendered = true;
    }

    btn.addEventListener("click", () => {
      tabBar
        .querySelectorAll(".chart-tab-btn")
        .forEach((b) => b.classList.remove("active"));
      paneContainer
        .querySelectorAll(".chart-tab-pane")
        .forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      pane.classList.add("active");

      if (!rendered) {
        renderChartInPane(pane, figures[type]);
        rendered = true;
      }
      // Fix Plotly sizing after tab reveal
      const plotEl = pane.querySelector(".js-plotly-plot");
      if (plotEl) Plotly.relayout(plotEl, { autosize: true });
    });

    tabBar.appendChild(btn);
    paneContainer.appendChild(pane);
  });

  container.appendChild(tabBar);
  container.appendChild(paneContainer);
}

function clearChangedLines() {
  markedLines.forEach((handle) => {
    if (handle) {
      sqlEditor.removeLineClass(handle, "background", "line-changed");
    }
  });
  markedLines = [];
}

function updateChangedLines() {
  if (!sqlEditor) return;
  clearChangedLines();
  const currentSql = sqlEditor.getValue();
  const originalLines = originalSql.split("\n");
  const currentLines = currentSql.split("\n");
  const maxLines = Math.max(originalLines.length, currentLines.length);
  let changed = false;

  for (let i = 0; i < maxLines; i += 1) {
    if ((currentLines[i] || "") !== (originalLines[i] || "")) {
      const handle = sqlEditor.addLineClass(i, "background", "line-changed");
      markedLines.push(handle);
      changed = true;
    }
  }

  sqlHint.textContent = changed ? "Edited SQL detected." : "";
}

function setSqlValue(sql) {
  if (!sqlEditor) return;
  originalSql = sql || "";
  sqlEditor.setValue(originalSql);
  clearChangedLines();
  sqlHint.textContent = "";
}

function showErrorCard(error) {
  if (!error) {
    errorCard.classList.add("hidden");
    return;
  }
  errorCard.classList.remove("hidden");
  setCardOpen("error", true);
  errorMessage.textContent = error.message;
  errorTrace.textContent = error.trace || "No error trace available.";
}

function renderResult(index) {
  if (index < 0 || index >= resultsHistory.length) return;
  const result = resultsHistory[index];
  activeResultIndex = index;
  lastResult = result;
  resultLabel.textContent = `Result #${index + 1}`;

  renderStepper(result.status_updates || [], result.status || "");
  statusMeta.textContent =
    result.status_meta ||
    (result.status === "failed" ? "Query failed" : "Query completed");
  statusTag.textContent = result.status || "Completed";

  const hasSql = Boolean(result.sql_query);
  const hasSchema = Boolean(result.schema_context);

  setSqlValue(result.sql_query || "");
  buildTable(result.db_result);

  lastSchema = result.schema_context || "";
  schemaBlock.textContent = schemaToggle.checked ? lastSchema : "";

  setCardOpen("status", true);
  setCardOpen("result", true);
  setCardOpen("sql", hasSql);
  setCardOpen("schema", schemaToggle.checked && hasSchema);

  showErrorCard(result.error);

  if (result.error) {
    setStatus("Error", "error");
  } else {
    setStatus("Complete", "ok");
  }

  renderHistoryList();
}

function clearOutputs() {
  setSqlValue("");
  table.innerHTML = '<div class="empty">No rows returned.</div>';
  schemaBlock.textContent = "";
  if (typingIndicator) {
    typingIndicator.classList.add("hidden");
  }
  showErrorCard(null);
}

function initSqlEditor() {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  sqlEditor = CodeMirror.fromTextArea(sqlEditorElement, {
    mode: "text/x-sql",
    lineNumbers: true,
    theme: prefersDark ? "material-palenight" : "default",
    lineWrapping: true,
  });
  sqlEditor.on("change", updateChangedLines);
}

function encodeState(state) {
  const json = JSON.stringify(state);
  return btoa(unescape(encodeURIComponent(json)));
}

function decodeState(encoded) {
  try {
    const json = decodeURIComponent(escape(atob(encoded)));
    return JSON.parse(json);
  } catch (error) {
    return null;
  }
}

async function runQuery(options = {}) {
  const question = (options.question || questionInput.value).trim();
  const sqlOverride = options.sqlOverride || null;
  if (!question) return;

  lastQuestion = question;
  turnCount += 1;
  const assistantTurn = createTurn(question, turnCount);
  questionInput.value = "";
  clearOutputs();
  setStatus("Running", "ok");
  statusMeta.textContent = "Submitting request...";
  renderStepper([], "running");
  if (typingIndicator) typingIndicator.classList.remove("hidden");

  sendBtn.disabled = true;
  sendBtn.textContent = "Running...";

  const currentStatusUpdates = [];
  const turnTimestamp = Date.now();

  try {
    const response = await fetch("/api/query/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        provider: provider.value,
        api_key: apiKey.value || null,
        top_k: Number(topK.value),
        sql_override: sqlOverride,
      }),
    });

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.error || "Request failed");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE events are separated by double newlines
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";

      for (const part of parts) {
        if (!part.startsWith("data: ")) continue;
        let eventData;
        try {
          eventData = JSON.parse(part.slice(6));
        } catch {
          continue;
        }

        if (eventData.type === "node_update") {
          currentStatusUpdates.push({
            node: eventData.node,
            message: eventData.message,
            elapsed_s: eventData.elapsed_s,
          });
          renderStepper(currentStatusUpdates, "running");
          statusMeta.textContent = eventData.message;
          pulseStepper(eventData.node);
        } else if (eventData.type === "done") {
          const errorPayload = eventData.error_type
            ? {
                type: eventData.error_type,
                message: eventData.error_message || "Something went wrong.",
                trace: eventData.error_trace || "",
              }
            : null;

          const result = {
            question,
            timestamp: turnTimestamp,
            status: eventData.status || "completed",
            status_meta: eventData.status_meta || "",
            status_updates: eventData.status_updates || currentStatusUpdates,
            sql_query: eventData.sql_query || "",
            summary: eventData.summary || "",
            db_result: eventData.db_result || null,
            figure: eventData.figure || null,
            figures: eventData.figures || {},
            chart_type_auto: eventData.chart_type_auto || "table",
            schema_context: eventData.schema_context || "",
            confidence_score: null,
            confidence_explanation: "",
            error: errorPayload,
          };

          resultsHistory.push(result);
          renderResult(resultsHistory.length - 1);
          renderAssistantSummary(assistantTurn.summaryBody, result);
          renderMultiChart(
            assistantTurn.chartBody,
            result.figures,
            result.chart_type_auto,
          );
          renderConfidence(
            assistantTurn.confidenceBody,
            result.confidence_score,
            result.confidence_explanation,
          );
          setAssistantReady(assistantTurn);
          renderHistoryList();
        } else if (eventData.type === "error") {
          throw new Error(eventData.message || "Stream error");
        }
      }
    }
  } catch (error) {
    const fallback = {
      question,
      timestamp: turnTimestamp,
      status: "failed",
      status_meta: "Request failed",
      status_updates: currentStatusUpdates,
      sql_query: "",
      summary: "",
      db_result: null,
      figure: null,
      figures: {},
      chart_type_auto: "table",
      schema_context: "",
      confidence_score: null,
      confidence_explanation: "",
      error: {
        type: "unknown_error",
        message: error.message || "Something went wrong.",
        trace: error.message || "",
      },
    };
    resultsHistory.push(fallback);
    renderResult(resultsHistory.length - 1);
    renderAssistantSummary(assistantTurn.summaryBody, fallback);
    renderMultiChart(assistantTurn.chartBody, {}, null);
    renderConfidence(
      assistantTurn.confidenceBody,
      fallback.confidence_score,
      fallback.confidence_explanation,
    );
    setAssistantReady(assistantTurn);
    renderHistoryList();
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = "Run query";
    if (typingIndicator) typingIndicator.classList.add("hidden");
    updateRelativeTimes();
  }
}

function downloadCsv() {
  if (!lastResult || !lastResult.db_result) return;
  const { columns, rows } = lastResult.db_result;
  if (!columns || !rows) return;
  const csvRows = [columns.join(",")];
  rows.forEach((row) => {
    const escaped = row.map((cell) => {
      const text = cell === null ? "" : String(cell);
      if (text.includes(",") || text.includes('"') || text.includes("\n")) {
        return `"${text.replace(/\"/g, '""')}"`;
      }
      return text;
    });
    csvRows.push(escaped.join(","));
  });
  const blob = new Blob([csvRows.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "nl2sql-results.csv";
  link.click();
  URL.revokeObjectURL(url);
}

async function copySqlFromEditor(targetButton) {
  const text = sqlEditor ? sqlEditor.getValue().trim() : "";
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    if (targetButton) {
      targetButton.textContent = "Copied";
      setTimeout(() => {
        targetButton.textContent = "Copy SQL";
      }, 1200);
    }
  } catch (error) {
    if (targetButton) {
      targetButton.textContent = "Failed";
      setTimeout(() => {
        targetButton.textContent = "Copy SQL";
      }, 1200);
    }
  }
}

function copyShareLink() {
  const state = {
    question: lastQuestion,
    provider: provider.value,
    top_k: Number(topK.value),
    sql: sqlEditor ? sqlEditor.getValue() : "",
  };
  const url = new URL(window.location.href);
  url.searchParams.set("state", encodeState(state));
  navigator.clipboard.writeText(url.toString());
}

function openFullscreen() {
  let chartTarget = null;
  if (activeResultIndex >= 0) {
    const turn = document.querySelector(
      `.turn[data-turn="${activeResultIndex + 1}"]`,
    );
    if (turn) {
      chartTarget = turn.querySelector(".assistant-chart .chart");
      if (chartTarget && !chartTarget.querySelector(".js-plotly-plot")) {
        chartTarget = null;
      }
    }
  }
  const target = chartTarget || table;
  if (target && target.requestFullscreen) {
    target.requestFullscreen();
  }
}

function populateExamples() {
  examplesList.innerHTML = "";
  exampleTemplates.forEach((template) => {
    const button = document.createElement("button");
    button.className = "example-btn";
    button.type = "button";
    button.textContent = template;
    button.addEventListener("click", () => {
      questionInput.value = template;
      examplesPopover.classList.add("hidden");
      questionInput.focus();
    });
    examplesList.appendChild(button);
  });
}

function rotatePlaceholder() {
  if (document.activeElement === questionInput || questionInput.value) {
    return;
  }
  questionInput.placeholder = exampleCarousel[carouselIndex];
  carouselIndex = (carouselIndex + 1) % exampleCarousel.length;
}

function applySharedState() {
  const params = new URLSearchParams(window.location.search);
  const stateParam = params.get("state");
  if (!stateParam) return;
  const state = decodeState(stateParam);
  if (!state) return;
  if (state.provider) provider.value = state.provider;
  if (state.top_k) topK.value = String(state.top_k);
  if (state.question) questionInput.value = state.question;
  if (state.sql && sqlEditor) setSqlValue(state.sql);
  updateTopKBadge();
}

document.querySelectorAll(".card-toggle").forEach((toggle) => {
  toggle.addEventListener("click", () => {
    const cardId = toggle.dataset.toggle;
    const card = document.querySelector(`[data-card="${cardId}"]`);
    if (!card) return;
    const collapsed = card.dataset.collapsed === "true";
    setCardOpen(cardId, collapsed);
  });
});

sendBtn.addEventListener("click", () => runQuery());
questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    runQuery();
  }
});

copySqlBtn.addEventListener("click", () => copySqlFromEditor(copySqlBtn));
toolbarCopySqlBtn.addEventListener("click", () => copySqlFromEditor(null));
rerunSqlBtn.addEventListener("click", () =>
  runQuery({ question: lastQuestion, sqlOverride: sqlEditor.getValue() }),
);

downloadCsvBtn.addEventListener("click", downloadCsv);
shareLinkBtn.addEventListener("click", copyShareLink);
fullscreenBtn.addEventListener("click", openFullscreen);

if (configToggle) {
  configToggle.addEventListener("click", () => {
    const collapsed = appRoot?.classList.contains("app--collapsed-left");
    setConfigCollapsed(!collapsed);
  });
}

errorRetryBtn.addEventListener("click", () =>
  runQuery({ question: lastQuestion }),
);

resetBtn.addEventListener("click", () => {
  chat.innerHTML = "";
  chatEmpty.style.display = "block";
  resultsHistory = [];
  activeResultIndex = -1;
  turnCount = 0;
  clearOutputs();
  renderStepper([], "idle");
  statusMeta.textContent = "Waiting for a question";
  resultLabel.textContent = "Result #0";
  renderHistoryList();
});

schemaToggle.addEventListener("change", () => {
  schemaBlock.textContent = schemaToggle.checked ? lastSchema : "";
  setCardOpen("schema", schemaToggle.checked && Boolean(lastSchema));
});

topK.addEventListener("input", updateTopKBadge);

// Resize: reflow Plotly charts so they fill their containers correctly
let _resizeTimer;
window.addEventListener("resize", () => {
  updateTopKBadge();
  clearTimeout(_resizeTimer);
  _resizeTimer = setTimeout(() => {
    document.querySelectorAll(".js-plotly-plot").forEach((el) => {
      if (typeof Plotly !== "undefined") {
        Plotly.relayout(el, { autosize: true });
      }
    });
  }, 150);
});
examplesBtn.addEventListener("click", () => {
  examplesPopover.classList.toggle("hidden");
});

if (toggleApiKey) {
  toggleApiKey.addEventListener("click", () => {
    const isHidden = apiKey.type === "password";
    apiKey.type = isHidden ? "text" : "password";
    toggleApiKey.setAttribute("aria-pressed", isHidden ? "true" : "false");
  });
}

document.addEventListener("click", (event) => {
  if (!examplesPopover.contains(event.target) && event.target !== examplesBtn) {
    examplesPopover.classList.add("hidden");
  }
});

initSqlEditor();
syncCardToggles();
populateExamples();
rotatePlaceholder();
setInterval(rotatePlaceholder, 4000);
setInterval(updateRelativeTimes, 60000);
updateTopKBadge();
renderStepper([], "idle");
statusMeta.textContent = "Waiting for a question";
applySharedState();
renderHistoryList();

const clearHistoryBtn = document.getElementById("clearHistoryBtn");
if (clearHistoryBtn) {
  clearHistoryBtn.addEventListener("click", () => {
    resultsHistory = [];
    activeResultIndex = -1;
    renderHistoryList();
  });
}

