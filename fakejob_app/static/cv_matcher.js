// ------------------------------------------------------------------
// Scam Sentry — CV-based job matching panel.
// Uploads a CV to POST /api/match/cv and renders ranked matches.
// Matching is a RELEVANCE aid: the risk badge shown is the job's
// stored Risk Engine verdict and is never altered here.
// ------------------------------------------------------------------

(function () {
  "use strict";

  const panel = document.getElementById("cv-matcher");
  if (!panel) return;

  const fileInput = document.getElementById("cv-file");
  const textInput = document.getElementById("cv-text");
  const matchBtn = document.getElementById("btn-match");
  const matchLabel = document.getElementById("btn-match-label");
  const statusEl = document.getElementById("cv-status");
  const signalsEl = document.getElementById("cv-signals");
  const resultsEl = document.getElementById("cv-results");
  const minFitEl = document.getElementById("cv-min-fit");
  const riskEl = document.getElementById("cv-risk");
  const hideRiskyEl = document.getElementById("cv-hide-risky");

  const LEVEL_EMOJI = { Critical: "🚨", High: "🔴", Medium: "🟡", Low: "🟢" };

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function setStatus(message, isError) {
    statusEl.textContent = message;
    statusEl.classList.toggle("is-error", !!isError);
  }

  function setBusy(busy) {
    matchBtn.disabled = busy;
    matchLabel.textContent = busy ? "Matching…" : "Match Jobs";
  }

  function signalsBlock(cv) {
    const chips = [];
    const push = (label, list) => {
      (list || []).forEach((t) => chips.push(
        `<span class="cv-chip">${escapeHtml(t)}</span>`));
    };
    push("skill", cv.skills);
    push("tool", cv.tools);
    push("role", cv.role_titles);
    if (!chips.length) return "";
    return `
      <div class="cv-signals-head">${escapeHtml(cv.summary || "")}</div>
      <div class="cv-chips">${chips.join("")}</div>`;
  }

  function resultCard(match) {
    const card = document.createElement("div");
    card.className = "job-card cv-result";
    const level = match.risk_level || "Low";
    const emoji = LEVEL_EMOJI[level] || "";
    const matched = (match.matched_terms || []).length
      ? `<div class="cv-matched">Matched: ${escapeHtml(match.matched_terms.join(", "))}</div>`
      : "";
    const place = [match.company, match.location].filter(Boolean).join(" • ");
    card.innerHTML = `
      <div class="job-card-top">
        <strong class="job-card-title">${escapeHtml(match.title || "Untitled role")}</strong>
        <span class="cv-fit" title="Relevance fit to your CV">${match.fit_score}%</span>
      </div>
      <div class="job-card-meta">${escapeHtml(place || "Unknown company")}</div>
      <div class="cv-result-badges">
        <span class="risk-pill ${escapeHtml(level.toUpperCase())}">${emoji} ${escapeHtml(level)}</span>
        <span class="cv-role">${escapeHtml(match.job_role && match.job_role !== "Other" ? match.job_role : (match.industry || "Other"))}</span>
      </div>
      <div class="cv-reason">${escapeHtml(match.reason || "")}</div>
      ${matched}
      <div class="job-card-foot">
        <span class="job-source">${escapeHtml(match.source || "")}</span>
        <a class="cv-link" href="/dashboard/jobs/${encodeURIComponent(match.job_id)}">View details &rarr;</a>
      </div>`;
    return card;
  }

  function renderResults(data) {
    resultsEl.innerHTML = "";
    const matches = data.matches || [];
    if (signalsEl) {
      signalsEl.innerHTML = signalsBlock(data.cv || {});
      signalsEl.hidden = !signalsEl.innerHTML;
    }
    if (!matches.length) {
      const empty = document.createElement("div");
      empty.className = "no-evidence-box";
      empty.innerHTML = "<span>No scanned jobs match these filters yet. Lower the minimum fit, allow higher risk levels, or run a scan to add more listings.</span>";
      resultsEl.appendChild(empty);
      return;
    }
    matches.forEach((m) => resultsEl.appendChild(resultCard(m)));
  }

  async function runMatch() {
    const file = fileInput && fileInput.files && fileInput.files[0];
    const text = textInput ? textInput.value.trim() : "";
    if (!file && !text) {
      setStatus("Choose a CV file or paste CV text first.", true);
      return;
    }

    const form = new FormData();
    if (file) form.append("file", file);
    else form.append("cv_text", text);
    if (minFitEl) form.append("min_fit", minFitEl.value || "0");
    if (riskEl && riskEl.value) form.append("risk_level", riskEl.value);
    if (hideRiskyEl && hideRiskyEl.checked) form.append("exclude_risky", "1");

    setBusy(true);
    setStatus("Reading your CV and scoring scanned jobs…", false);
    resultsEl.innerHTML = "";
    if (signalsEl) signalsEl.hidden = true;
    try {
      const res = await fetch("/api/match/cv", { method: "POST", body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Could not match jobs right now.");
      const n = data.total_matches || 0;
      const candidates = data.candidate_jobs || 0;
      setStatus(
        n
          ? `Found ${n} match${n === 1 ? "" : "es"} among ${candidates} scanned job${candidates === 1 ? "" : "s"}.`
          : `No matches found among ${candidates} scanned job${candidates === 1 ? "" : "s"}.`,
        false);
      renderResults(data);
    } catch (err) {
      setStatus(err.message || "Could not match jobs right now.", true);
      resultsEl.innerHTML = "";
      if (signalsEl) signalsEl.hidden = true;
    } finally {
      setBusy(false);
    }
  }

  if (matchBtn) matchBtn.addEventListener("click", runMatch);
  if (fileInput) {
    fileInput.addEventListener("change", () => {
      const file = fileInput.files && fileInput.files[0];
      if (file) {
        setStatus(`Selected: ${file.name}. Click “Match Jobs".`, false);
        if (textInput) textInput.value = "";
      }
    });
  }
})();
