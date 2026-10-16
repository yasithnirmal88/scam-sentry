// ------------------------------------------------------------------
// Scam Sentry Job Risk Dashboard
// Fetches scanned jobs from /api/jobs, renders grouped cards,
// handles risk/source/keyword filters, and triggers POST /api/scan.
// ------------------------------------------------------------------

const LEVELS = ["Critical", "High", "Medium", "Low"];
const LEVEL_EMOJI = { Critical: "🚨", High: "🔴", Medium: "🟡", Low: "🟢" };

const state = { jobs: [], risk: "", source: "", q: "", industry: "", role: "",
                country: "", region: "", remote: "" };

const groupsEl = document.getElementById("job-groups");
const errorBox = document.getElementById("dash-error");
const scanStatus = document.getElementById("scan-status");
const scanBtn = document.getElementById("btn-scan");
const scanLabel = document.getElementById("btn-scan-label");
const industrySel = document.getElementById("filter-industry");
const roleSel = document.getElementById("filter-role");
const countrySel = document.getElementById("filter-country");
const regionSel = document.getElementById("filter-region");

function statusClass(status) {
  const s = (status || "unknown").toLowerCase();
  if (s === "success") return "status-ok";
  if (s === "partial") return "status-partial";
  if (s === "running") return "status-busy";
  if (s === "failed") return "status-fail";
  if (s === "empty") return "status-empty";
  return "status-unknown";
}

function runRow(run) {
  const el = document.createElement("div");
  el.className = "scan-run";
  const start = (run.started_at || "").replace("T", " ").slice(0, 16);
  const finish = (run.finished_at || "").replace("T", " ").slice(0, 16);
  const sources = (run.sources || []).join(" + ") || "unknown sources";
  el.innerHTML = `
    <div class="scan-run-head">
      <span class="status-chip ${statusClass(run.status)}">${escapeHtml(run.status || "unknown")}</span>
      <span class="scan-run-id">run #${run.id}</span>
      <span class="scan-run-time">${escapeHtml(start)}${finish && finish !== start ? " &rarr; " + escapeHtml(finish) : ""}</span>
    </div>
    <div class="scan-run-meta">
      <span>${run.stored} stored</span><span>${run.fetched} fetched</span>
      <span>${run.skipped || 0} skipped</span><span>${run.duplicates || 0} duplicates</span>
      <span class="scan-run-sources">${escapeHtml(sources)}</span>
    </div>`;
  return el;
}

async function loadHistory() {
  const wrap = document.getElementById("scan-runs");
  const empty = document.getElementById("history-empty");
  const countBadge = document.getElementById("history-count");
  if (!wrap) return;
  try {
    const res = await fetch("/api/scan/history?limit=15");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to load scan history");
    const runs = data.runs || [];
    if (countBadge) countBadge.textContent = `${runs.length} run${runs.length === 1 ? "" : "s"}`;
    wrap.innerHTML = "";
    if (empty) empty.hidden = runs.length > 0;
    runs.forEach((r) => wrap.appendChild(runRow(r)));
  } catch (err) {
    if (empty) empty.hidden = false;
    if (empty) empty.querySelector("span").textContent = "Could not load scan history.";
  }
}

function setScanning(active) {
  scanBtn.disabled = active;
  scanLabel.textContent = active ? "Scanning…" : "Run New Scan";
  let bar = document.getElementById("scan-progress");
  if (active && !bar) {
    bar = document.createElement("div");
    bar.className = "scan-progress";
    bar.id = "scan-progress";
    bar.innerHTML = "<div></div>";
    scanStatus.after(bar);
  } else if (!active && bar) {
    bar.remove();
  }
}

function dismissWelcomeIfJobs() {
  const welcome = document.getElementById("welcome-banner");
  if (welcome && state.jobs.length > 0) welcome.remove();
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str || "";
  return div.innerHTML;
}

function pillClass(level) {
  return (level || "Low").toUpperCase();
}

function jobCard(job) {
  const el = document.createElement("div");
  el.className = "job-card";
  const detailUrl = `/dashboard/jobs/${job.id}`;
  el.tabIndex = 0;
  el.setAttribute("role", "link");
  el.setAttribute("aria-label", `Open risk report for ${job.title || "this job"}`);
  el.addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    window.location.href = detailUrl;
  });
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      window.location.href = detailUrl;
    }
  });
  const posted = (job.posted_at || "").slice(0, 10);
  const taxonomy = `"${escapeHtml(job.industry || "Other")} \u203a ${escapeHtml(job.job_role || "Other")}"`;
  const taxLine = (job.industry && job.industry !== "Other")
    ? `<div class="job-tax">${taxonomy}</div>` : "";
  const source = job.url
    ? `<a class="job-source job-source-link" href="${escapeHtml(job.url)}" target="_blank" rel="noopener noreferrer" title="Open the original posting on ${escapeHtml(job.source || "the source site")}">${escapeHtml(job.source || "source")} &#8599;</a>`
    : `<span class="job-source">${escapeHtml(job.source || "")}</span>`;
  el.innerHTML = `
    <div class="job-card-top">
      <strong class="job-card-title">${escapeHtml(job.title || "Untitled role")}</strong>
      <span class="risk-pill ${pillClass(job.overall_risk_level)}">${LEVEL_EMOJI[job.overall_risk_level] || ""} ${escapeHtml(job.overall_risk_level)}</span>
    </div>
    <div class="job-card-meta">${escapeHtml(job.company || "Unknown company")}${job.location ? " &bull; " + escapeHtml(job.location) : ""}</div>
    ${taxLine}
    <div class="job-card-foot">
      ${source}
      <span class="job-date">${escapeHtml(posted || "date unknown")}</span>
    </div>`;
  return el;
}

// ---- Industry / role search sections -----------------------------------
let TAXONOMY = { industries: {} };
let LOOKUPS = { countries: [], regions: [] };

function rebuildRoleOptions() {
  if (!roleSel) return;
  const selected = state.industry;
  let roles = [];
  if (selected) {
    roles = (TAXONOMY.industries[selected] || []).slice();
  } else {
    const seen = new Set();
    Object.values(TAXONOMY.industries).forEach((list) => {
      (list || []).forEach((r) => { if (!seen.has(r)) { seen.add(r); roles.push(r); } });
    });
    roles.sort();
  }
  roles.push("Other");
  roleSel.innerHTML = "";
  const any = document.createElement("option");
  any.value = "";
  any.textContent = "All roles";
  roleSel.appendChild(any);
  roles.forEach((r) => {
    const opt = document.createElement("option");
    opt.value = r;
    opt.textContent = r;
    roleSel.appendChild(opt);
  });
}

function populateIndustryOptions() {
  if (!industrySel) return;
  industrySel.innerHTML = "";
  const any = document.createElement("option");
  any.value = "";
  any.textContent = "All industries";
  industrySel.appendChild(any);
  Object.keys(TAXONOMY.industries).forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    industrySel.appendChild(opt);
  });
}

// ---- Country / region filter options ------------------------------------
// Options are the distinct countries/regions present in the store, refreshed
// on every load (the API returns them unfiltered, so the lists stay stable).
function rebuildLocationOptions(select, values, allLabel, current) {
  if (!select) return;
  select.innerHTML = "";
  const any = document.createElement("option");
  any.value = "";
  any.textContent = allLabel;
  select.appendChild(any);
  (values || []).forEach((v) => {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v;
    select.appendChild(opt);
  });
  select.value = (values || []).includes(current) ? current : "";
}

function populateLocationOptions() {
  rebuildLocationOptions(countrySel, LOOKUPS.countries, "All countries", state.country);
  rebuildLocationOptions(regionSel, LOOKUPS.regions, "All regions", state.region);
}

async function loadTaxonomy() {
  try {
    const res = await fetch("/api/taxonomy");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to load industry/role options");
    TAXONOMY = data || { industries: {} };
    populateIndustryOptions();
    rebuildRoleOptions();
  } catch (err) {
    // Options stay empty; industry/role filters then simply match nothing.
  }
}

if (industrySel) {
  industrySel.addEventListener("change", (e) => {
    state.industry = e.target.value;
    state.role = "";
    if (roleSel) roleSel.value = "";
    rebuildRoleOptions();
    loadJobs();
  });
}
if (roleSel) {
  roleSel.addEventListener("change", (e) => {
    state.role = e.target.value;
    loadJobs();
  });
}
if (countrySel) {
  countrySel.addEventListener("change", (e) => {
    state.country = e.target.value;
    loadJobs();
  });
}
if (regionSel) {
  regionSel.addEventListener("change", (e) => {
    state.region = e.target.value;
    loadJobs();
  });
}
const remoteSel = document.getElementById("filter-remote");
if (remoteSel) {
  remoteSel.addEventListener("change", (e) => {
    state.remote = e.target.value;
    loadJobs();
  });
}

// Industry / role / source / keyword are filtered SERVER-SIDE (see loadJobs)
// so a search is not silently limited to the client-side 200-row window and
// can match the description too. Only the risk tab is applied locally.
function filteredJobs() {
  return state.jobs.filter((j) => {
    if (state.risk && j.overall_risk_level !== state.risk) return false;
    return true;
  });
}

function jobsQueryString() {
  const params = new URLSearchParams({ limit: "200" });
  if (state.industry) params.set("industry", state.industry);
  if (state.role) params.set("role", state.role);
  if (state.source) params.set("source", state.source);
  if (state.country) params.set("country", state.country);
  if (state.region) params.set("region", state.region);
  if (state.remote) params.set("remote", state.remote);
  const q = state.q.trim();
  if (q) params.set("q", q);
  return params.toString();
}

function render() {
  const jobs = filteredJobs();
  const byLevel = { Critical: [], High: [], Medium: [], Low: [] };
  jobs.forEach((j) => { (byLevel[j.overall_risk_level] || byLevel.Low).push(j); });

  const filtering = state.risk || state.source || state.q.trim()
    || state.industry || state.role || state.country || state.region
    || state.remote;

  // When a filter matches nothing, every group would be hidden below, leaving
  // a blank page. Show one explicit "no matches" notice instead.
  let empty = document.getElementById("jobs-empty");
  if (filtering && jobs.length === 0) {
    if (!empty) {
      empty = document.createElement("div");
      empty.id = "jobs-empty";
      empty.className = "no-evidence-box";
      groupsEl.before(empty);
    }
    empty.textContent = "";
    const s = document.createElement("span");
    s.textContent = "No jobs match the current filters.";
    empty.appendChild(s);
  } else if (empty) {
    empty.remove();
  }

  groupsEl.querySelectorAll(".dash-group").forEach((section) => {
    const level = section.dataset.group;
    const list = byLevel[level] || [];
    section.querySelector(".group-count").textContent = `${list.length}`;
    // Hide empty groups only when a filter is active; otherwise show headers with 0.
    section.style.display = filtering && list.length === 0 ? "none" : "";
    const wrap = section.querySelector(".job-cards");
    wrap.innerHTML = "";
    if (list.length === 0) {
      const p = document.createElement("div");
      p.className = "no-evidence-box";
      const s = document.createElement("span");
      s.textContent = filtering ? "No jobs match the current filters." : "No jobs at this risk level yet — run a scan.";
      p.appendChild(s);
      wrap.appendChild(p);
    } else {
      list.forEach((j) => wrap.appendChild(jobCard(j)));
    }
  });

  // When a single risk tab is active, scroll emphasis: hide other groups.
  if (state.risk) {
    groupsEl.querySelectorAll(".dash-group").forEach((section) => {
      if (section.dataset.group !== state.risk) section.style.display = "none";
    });
  }
}

function updateStatusStrip(status) {
  if (!status) return;
  const last = status.last_scan;
  const timeEl = document.getElementById("last-scan-time");
  const detailEl = document.getElementById("last-scan-detail");
  const statusEl = document.getElementById("last-scan-status");
  if (last) {
    if (timeEl) timeEl.textContent = (last.finished_at || last.started_at || "").slice(0, 16).replace("T", " ");
    if (detailEl) detailEl.textContent = `${last.stored} stored • ${last.fetched} fetched`;
    if (statusEl) statusEl.textContent = status.running ? "running…" : last.status;
  } else if (statusEl && !status.running) {
    statusEl.textContent = "—";
  } else if (statusEl) {
    statusEl.textContent = "running…";
  }
}

async function refreshScanStatus() {
  try {
    const res = await fetch("/api/scan/status");
    const data = await res.json();
    if (res.ok) updateStatusStrip(data);
    return res.ok ? data : null;
  } catch (err) {
    return null;
  }
}

let loadSeq = 0;
async function loadJobs() {
  const seq = ++loadSeq;
  errorBox.hidden = true;
  try {
    const res = await fetch(`/api/jobs?${jobsQueryString()}`);
    const data = await res.json();
    if (seq !== loadSeq) return; // a newer request superseded this one
    if (!res.ok) throw new Error(data.error || "Failed to load jobs");
    state.jobs = data.jobs || [];
    LOOKUPS = { countries: data.countries || [], regions: data.regions || [] };
    populateLocationOptions();
    const counts = data.counts || {};
    ["critical", "high", "medium", "low"].forEach((k) => {
      const el = document.getElementById(`count-${k}`);
      if (el && counts[k.charAt(0).toUpperCase() + k.slice(1)] != null) {
        el.textContent = counts[k.charAt(0).toUpperCase() + k.slice(1)];
      }
    });
    // "Total Jobs Stored" is a global figure ("across all sources"), so it
    // must not be overwritten by the filtered result count.
    const totalEl = document.getElementById("total-jobs");
    if (totalEl && data.global_total != null) totalEl.textContent = data.global_total;
    const summaryEl = document.getElementById("filter-summary");
    if (summaryEl) {
      const shown = state.jobs.length;
      const matching = data.total != null ? data.total : shown;
      summaryEl.textContent = matching === 0
        ? "No jobs match the current filters"
        : `Showing ${shown} of ${matching} matching job${matching === 1 ? "" : "s"}`;
    }
    render();
    dismissWelcomeIfJobs();
  } catch (err) {
    if (seq !== loadSeq) return;
    errorBox.hidden = false;
    errorBox.textContent = "Could not load scanned jobs. Is the backend running?";
  }
}

function selectedSources() {
  const boxes = document.querySelectorAll("#scan-sources input[type=checkbox]:checked");
  return Array.from(boxes).map((b) => b.value);
}

// Filters
document.querySelectorAll("#risk-tabs .tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#risk-tabs .tab-btn").forEach((b) => {
      b.classList.remove("active");
      b.setAttribute("aria-pressed", "false");
    });
    btn.classList.add("active");
    btn.setAttribute("aria-pressed", "true");
    state.risk = btn.dataset.risk || "";
    render();
  });
});

document.getElementById("filter-source").addEventListener("change", (e) => {
  state.source = e.target.value;
  loadJobs();
});

let searchTimer = null;
document.getElementById("filter-q").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.q = e.target.value;
    loadJobs();
  }, 180);
});

// Clicking a count card toggles the matching risk tab.
document.querySelectorAll(".dash-count").forEach((card) => {
  card.addEventListener("click", () => {
    const level = card.dataset.level;
    const btn = document.querySelector(`#risk-tabs .tab-btn[data-risk="${level}"]`);
    if (state.risk === level) {
      document.querySelector('#risk-tabs .tab-btn[data-risk=""]').click();
    } else if (btn) {
      btn.click();
    }
  });
});

// Scan trigger (async: POST returns 202, then poll status until idle)
async function startScan(sources) {
  if (sources.length === 0) {
    scanStatus.textContent = "Select at least one source first.";
    return;
  }
  setScanning(true);
  scanStatus.textContent = `Scanning ${sources.join(", ")} — fetching, evaluating, storing…`;
  errorBox.hidden = true;
  try {
    const res = await fetch("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sources, limit: 20 }),
    });
    const data = await res.json();
    if (res.status === 409) {
      scanStatus.textContent = "A scan is already running — results will appear below when it finishes.";
      await pollUntilIdle();
      return;
    }
    if (res.status === 401) {
      // Fail-closed scan hardening (F-01): the dashboard never sends a token.
      // Surface the server's setup hint so local/demo users know the two ways
      // to enable scanning without weakening the default.
      const hint = data.hint || data.error || "This server requires scan authentication.";
      scanStatus.textContent = "Scan blocked — authentication required.";
      throw new Error(hint);
    }
    if (!res.ok && res.status !== 202) throw new Error(data.error || data.reason || "Scan failed");
    if (res.status === 202 || data.status === "running") {
      await pollUntilIdle();
    } else {
      scanStatus.textContent = `Done: ${data.stored} stored (${data.fetched} fetched).`;
      await loadJobs();
      await loadHistory();
      await refreshScanStatus();
    }
  } catch (err) {
    errorBox.hidden = false;
    errorBox.textContent = err.message || "Scan failed. Check your connection and try again.";
    scanStatus.textContent = "Scan failed — see error above.";
  } finally {
    setScanning(false);
  }
}

scanBtn.addEventListener("click", () => startScan(selectedSources()));

const firstScanBtn = document.getElementById("btn-first-scan");
if (firstScanBtn) {
  firstScanBtn.addEventListener("click", () => {
    document.querySelector(".dash-controls").scrollIntoView({ behavior: "smooth", block: "center" });
    startScan(selectedSources());
  });
}

async function pollUntilIdle() {
  for (let i = 0; i < 120; i++) {
    await new Promise((r) => setTimeout(r, 3000));
    const status = await refreshScanStatus();
    if (!status) break;
    // Refresh the job groups + history on every tick so new listings appear
    // live while the background scan stores them.
    await loadJobs();
    await loadHistory();
    if (!status.running) {
      const last = status.last_scan;
      if (last) {
        scanStatus.textContent = `Done (${last.status}): ${last.stored} stored, ${last.fetched} fetched.`;
      } else {
        scanStatus.textContent = "Scan finished.";
      }
      await loadJobs();
      break;
    }
    const last = status.last_scan;
    scanStatus.textContent = last
      ? `Scanning… (${last.stored} stored so far, started ${String(last.started_at).slice(11, 16)})`
      : "Scanning…";
  }
}

loadJobs();
loadHistory();
refreshScanStatus();
loadTaxonomy();
