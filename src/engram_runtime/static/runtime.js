const state = {
  dashboard: null,
  currentThreadId: null,
  thread: null,
  busy: false,
};

const $ = (selector) => document.querySelector(selector);
const els = {
  profile: $("#profile-select"),
  health: $("#health-strip"),
  threads: $("#thread-list"),
  title: $("#thread-title"),
  threadId: $("#thread-id"),
  runState: $("#run-state"),
  conversation: $("#conversation"),
  timeline: $("#record-timeline"),
  recordCount: $("#record-count"),
  form: $("#composer"),
  input: $("#request-input"),
  runButton: $("#run-button"),
  sideEffects: $("#allow-side-effects"),
  tokenInput: $("#token-input"),
  tokenSaved: $("#token-saved"),
  actionCount: $("#action-count"),
  actionChips: $("#action-chips"),
  procedureState: $("#procedure-state"),
  procedureCue: $("#procedure-cue"),
  experienceCount: $("#experience-count"),
  procedureCount: $("#procedure-count"),
  outputCount: $("#output-count"),
  runCount: $("#run-count"),
  capacity: $("#capacity-fill"),
  toast: $("#toast"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(detail.detail || "Runtime request failed");
  }
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(Number(value || 0));
}

function showToast(message, error = false, retry = null) {
  els.toast.replaceChildren();
  const copy = document.createElement("span");
  copy.textContent = message;
  els.toast.append(copy);
  if (retry) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Retry";
    button.addEventListener("click", () => {
      els.toast.classList.remove("show");
      retry();
    }, { once: true });
    els.toast.append(button);
  }
  els.toast.classList.toggle("error", error);
  els.toast.classList.toggle("has-action", Boolean(retry));
  els.toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  if (!retry) showToast.timer = window.setTimeout(() => els.toast.classList.remove("show"), 3200);
}

function renderHealth(health) {
  const items = [
    ["STATE CORE", health.state_core],
    ["OLLAMA", health.ollama],
    ["OPENAI KEY", health.openai_key],
  ];
  els.health.innerHTML = items.map(([label, ready]) =>
    `<span class="health-pill ${ready ? "ready" : ""}"><i></i>${label}</span>`
  ).join("");
}

function renderProfiles(profiles) {
  const previous = els.profile.value || "local";
  els.profile.innerHTML = profiles.map((profile) =>
    `<option value="${escapeHtml(profile.name)}">${escapeHtml(profile.name.toUpperCase())} · ${escapeHtml(profile.model)}</option>`
  ).join("");
  if (profiles.some((profile) => profile.name === previous)) els.profile.value = previous;
}

function renderThreads(threads) {
  els.threads.innerHTML = threads.map((thread) => {
    const active = thread.id === state.currentThreadId ? "active" : "";
    const status = thread.last_run_status || "ready";
    return `<button class="thread-item ${active}" data-thread="${thread.id}">
      <strong>${escapeHtml(thread.title)}</strong>
      <span><em>${escapeHtml(status)}</em><time>${formatTime(thread.updated_at)}</time></span>
    </button>`;
  }).join("") || `<div class="muted-copy">No runtime tasks yet.</div>`;
  els.threads.querySelectorAll("[data-thread]").forEach((button) => {
    button.addEventListener("click", () => selectThread(button.dataset.thread));
  });
}

function renderStats(stats) {
  els.experienceCount.textContent = formatNumber(stats.experiences);
  els.procedureCount.textContent = formatNumber(stats.verified_procedures);
  els.outputCount.textContent = formatNumber(stats.stored_outputs);
  els.runCount.textContent = `${formatNumber(stats.runs)} runs`;
  els.capacity.style.width = `${Math.min(100, 8 + Number(stats.runs || 0) * 2)}%`;
}

function renderConversation(entries) {
  if (!entries.length) {
    els.conversation.innerHTML = `<div class="empty-state">
      <div class="empty-orbit"><span></span></div>
      <div class="eyebrow">READY FOR A NEW SIGNAL</div>
      <h3>Direct the runtime.</h3>
      <p>Choose an inference profile, describe the outcome, and inspect every selected signal and action.</p>
    </div>`;
    return;
  }
  els.conversation.innerHTML = entries.map((entry) => `<article class="message ${escapeHtml(entry.speaker)}">
    <div class="message-label">${entry.speaker === "operator" ? "OPERATOR" : "ENGRAM WORKER"}</div>
    <div class="message-body">${escapeHtml(entry.body)}</div>
    <div class="message-time">${formatTime(entry.created_at)}</div>
  </article>`).join("");
  els.conversation.scrollTop = els.conversation.scrollHeight;
}

function recordLabel(kind) {
  return kind.replaceAll("_", " ").toUpperCase();
}

function renderRecords(records) {
  els.recordCount.textContent = records.length ? `${records.length} EVENTS` : "NO EVENTS";
  els.timeline.innerHTML = records.map((record, index) => {
    const hot = index === records.length - 1 || ["action_dispatch", "focus_packet", "pattern_distillation"].includes(record.record_kind);
    return `<div class="record-node ${hot ? "hot" : ""}" title="${escapeHtml(JSON.stringify(record.payload))}">
      <strong>${escapeHtml(recordLabel(record.record_kind))}</strong>
      <span>${formatTime(record.created_at)}</span>
    </div>`;
  }).join("") || `<span class="muted-copy">The execution trace will appear here.</span>`;
  els.timeline.scrollLeft = els.timeline.scrollWidth;
}

function renderFocus(records) {
  const record = [...records].reverse().find((item) => item.record_kind === "focus_packet");
  if (!record) {
    els.tokenInput.textContent = "—";
    els.tokenSaved.textContent = "—";
    els.actionCount.textContent = "0";
    els.actionChips.innerHTML = `<span class="muted-copy">Awaiting composition</span>`;
    els.procedureState.textContent = "NONE";
    els.procedureCue.classList.remove("active");
    els.procedureCue.innerHTML = `<span class="procedure-icon">◇</span><p>The first successful action sequence will crystallize here.</p>`;
    return;
  }
  const packet = record.payload;
  els.tokenInput.textContent = formatNumber(packet.estimated_tokens);
  els.tokenSaved.textContent = formatNumber(packet.estimated_tokens_avoided);
  els.actionCount.textContent = String(packet.actions?.length || 0);
  els.actionChips.innerHTML = (packet.actions || []).map((action) => `<span class="chip">${escapeHtml(action)}</span>`).join("") || `<span class="muted-copy">No actions selected</span>`;
  els.procedureState.textContent = packet.reused_procedure ? "REUSED" : "NEW";
  els.procedureCue.classList.toggle("active", packet.reused_procedure);
  els.procedureCue.innerHTML = packet.reused_procedure
    ? `<span class="procedure-icon">◆</span><p>A prior Procedure Cue replaced part of the raw history for this run.</p>`
    : `<span class="procedure-icon">◇</span><p>This run used direct signals. A successful action sequence can become a reusable cue.</p>`;
}

function setRunState(status) {
  const normalized = status || "idle";
  els.runState.className = `state-badge ${normalized}`;
  els.runState.innerHTML = `<i></i>${escapeHtml(normalized.toUpperCase())}`;
}

async function selectThread(threadId) {
  state.currentThreadId = threadId;
  renderThreads(state.dashboard.threads);
  const detail = await api(`/api/threads/${threadId}`);
  state.thread = detail;
  els.title.textContent = detail.thread.title;
  els.threadId.textContent = detail.thread.id.slice(0, 8).toUpperCase();
  const latest = detail.runs[0];
  setRunState(latest?.status || "idle");
  renderConversation(detail.entries);
  renderRecords(detail.records);
  renderFocus(detail.records);
}

async function refreshDashboard(selectNewest = false) {
  state.dashboard = await api("/api/dashboard");
  renderHealth(state.dashboard.health);
  renderProfiles(state.dashboard.profiles);
  renderStats(state.dashboard.stats);
  if (selectNewest && state.dashboard.threads.length) {
    state.currentThreadId = state.dashboard.threads[0].id;
  }
  renderThreads(state.dashboard.threads);
}

async function createThread() {
  const thread = await api("/api/threads", {
    method: "POST",
    body: JSON.stringify({ title: `Runtime task ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` }),
  });
  await refreshDashboard();
  await selectThread(thread.id);
  els.input.focus();
}

async function runCycle(event) {
  event.preventDefault();
  if (state.busy || !state.currentThreadId) return;
  const request = els.input.value.trim();
  if (!request) return;
  state.busy = true;
  els.runButton.disabled = true;
  els.runButton.querySelector("span").textContent = "Running";
  setRunState("running");
  try {
    const data = await api("/api/run", {
      method: "POST",
      body: JSON.stringify({
        thread_id: state.currentThreadId,
        request,
        profile: els.profile.value,
        allow_side_effects: els.sideEffects.checked,
      }),
    });
    els.input.value = "";
    state.thread = data.thread;
    renderConversation(data.thread.entries);
    renderRecords(data.thread.records);
    renderFocus(data.thread.records);
    setRunState(data.result.status);
    await refreshDashboard();
    showToast(data.result.status === "complete" ? "Cycle completed and recorded." : data.result.answer, data.result.status === "failed");
  } catch (error) {
    setRunState("failed");
    showToast(error.message, true, () => els.form.requestSubmit());
  } finally {
    state.busy = false;
    els.runButton.disabled = false;
    els.runButton.querySelector("span").textContent = "Run cycle";
    els.input.focus();
  }
}

async function initialize() {
  try {
    await refreshDashboard();
    if (!state.dashboard.threads.length) {
      await createThread();
    } else {
      await selectThread(state.dashboard.threads[0].id);
    }
  } catch (error) {
    showToast(error.message, true, initialize);
  }
}

$("#new-thread").addEventListener("click", createThread);
els.form.addEventListener("submit", runCycle);
els.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    runCycle(event);
  }
});

initialize();
