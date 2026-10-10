// ------------------------------------------------------------------
// Scam Sentry Frontend Application Logic
// Handles tab navigation, sample data loading, OCR drag-and-drop,
// API communication with Flask, and modern animated report rendering.
// ------------------------------------------------------------------

// 1. Tab Switching
const tabs = document.querySelectorAll(".tab-btn");
const panels = document.querySelectorAll(".tab-panel");

tabs.forEach(tab => {
  tab.addEventListener("click", () => {
    tabs.forEach(t => t.classList.remove("active"));
    panels.forEach(p => p.classList.remove("active"));
    tab.classList.add("active");
    const activePanel = document.querySelector(`.tab-panel[data-panel="${tab.dataset.tab}"]`);
    if (activePanel) activePanel.classList.add("active");
  });
});

// 2. Text Input & Counter
const pasteForm = document.getElementById("paste-form");
const jobText = document.getElementById("job-text");
const charCount = document.getElementById("char-count");
const btnClearText = document.getElementById("btn-clear-text");

function updateCharCount() {
  const len = jobText.value.length;
  charCount.textContent = `${len.toLocaleString()} character${len === 1 ? '' : 's'}`;
}

jobText.addEventListener("input", updateCharCount);

if (btnClearText) {
  btnClearText.addEventListener("click", () => {
    jobText.value = "";
    updateCharCount();
  });
}

// 3. Quick Test Sample Presets
const SAMPLE_LEGIT = `Senior Full-Stack Software Engineer
Company: Virtusa Technologies Inc.
Location: Colombo, Sri Lanka (Hybrid)

About the Role:
We are looking for an experienced Senior Full-Stack Software Engineer to join our cloud platform engineering team. You will be designing and building robust microservices, mentoring junior engineers, and collaborating with cross-functional product teams.

Requirements:
- 4+ years of hands-on experience with Python, Node.js, or Go.
- Solid experience with React, TypeScript, and modern frontend frameworks.
- Strong understanding of REST APIs, PostgreSQL, Docker, and AWS / GCP.
- Bachelor's degree in Computer Science, Software Engineering, or equivalent experience.

Benefits:
- Competitive industry salary and comprehensive medical insurance for you and your family.
- Annual performance bonuses, professional development allowance, and hybrid work flexibility.

How to Apply:
Please submit your resume and portfolio via our official careers portal at https://careers.virtusa.com/jobs/sr-eng-2026 or email jobs@virtusa.com. We never ask for any payment or application processing fees.`;

const SAMPLE_FAKE = `URGENT VACANCY: DATA ENTRY SPECIALIST - WORK FROM HOME!
Earn $850 - $1,200 Weekly! No Experience or Qualifications Needed!

Company: International Global Data Solutions Ltd.
Immediate vacancies for data entry operators, typists, and form fillers. Work only 2-3 hours per day from your mobile phone or laptop. Flexible hours, students and housewives welcome!

Requirements:
- Must have an internet connection and a bank account to receive weekly payments.
- Age 18+
- Immediate joining today! Only 3 positions left!

Application Instructions:
Before starting work and receiving your company equipment laptop, all selected applicants MUST pay a refundable Registration & Security Verification Fee of $50 (Rs. 15,000). Send receipt to our hiring manager via Telegram @GlobalHR_Admin or email globalcareer.hiring2026@gmail.com. Once fee is paid, your training kit and first assignment will be dispatched immediately.`;

const SAMPLE_WHATSAPP = `Online Part-Time Customer Assistant
Salary: $200 - $500 Daily! Daily cash payouts guaranteed!

Huge multinational corporation looking for energetic candidates to do simple rating and review tasks on your phone.
- No resume required!
- No interview!
- Zero experience required!
- Guaranteed instant income!

Hurry, apply immediately! Contact Miss Emily right now on WhatsApp at +94 71 999 8888 or Telegram to claim your spot and daily bonus.`;

document.getElementById("load-sample-legit")?.addEventListener("click", () => {
  switchTab("paste");
  jobText.value = SAMPLE_LEGIT;
  updateCharCount();
});

document.getElementById("load-sample-fake")?.addEventListener("click", () => {
  switchTab("paste");
  jobText.value = SAMPLE_FAKE;
  updateCharCount();
});

document.getElementById("load-sample-whatsapp")?.addEventListener("click", () => {
  switchTab("paste");
  jobText.value = SAMPLE_WHATSAPP;
  updateCharCount();
});

function switchTab(tabName) {
  tabs.forEach(t => {
    t.classList.toggle("active", t.dataset.tab === tabName);
  });
  panels.forEach(p => {
    p.classList.toggle("active", p.dataset.panel === tabName);
  });
}

// 4. Form Submission: Paste Text
pasteForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = jobText.value.trim();
  if (!text) {
    alert("Please enter or paste job advertisement text before examining.");
    return;
  }
  await runAnalysis(() =>
    fetch("/api/analyze/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    })
  );
});

// 5. File Upload & Drag-and-Drop
const uploadForm = document.getElementById("upload-form");
const fileInput = document.getElementById("file-input");
const dropzone = document.getElementById("dropzone");
const dzFilename = document.getElementById("dz-filename");
const fileHint = document.getElementById("file-hint");
const uploadBtn = document.getElementById("upload-btn");
const btnClearFile = document.getElementById("btn-clear-file");
let selectedFile = null;

function setSelectedFile(file) {
  selectedFile = file || null;
  if (selectedFile) {
    dzFilename.textContent = selectedFile.name;
    fileHint.textContent = `${(selectedFile.size / 1024).toFixed(1)} KB &bull; ${selectedFile.type || 'Document ready'}`;
    uploadBtn.disabled = false;
    if (btnClearFile) btnClearFile.style.display = "inline-block";
  } else {
    dzFilename.textContent = "Drop image or PDF flyer here";
    fileHint.textContent = "No file selected";
    uploadBtn.disabled = true;
    fileInput.value = "";
    if (btnClearFile) btnClearFile.style.display = "none";
  }
}

fileInput.addEventListener("change", () => setSelectedFile(fileInput.files[0]));

if (btnClearFile) {
  btnClearFile.addEventListener("click", (e) => {
    e.preventDefault();
    setSelectedFile(null);
  });
}

["dragenter", "dragover"].forEach(evt => {
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.add("drag");
  });
});

["dragleave", "drop"].forEach(evt => {
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag");
  });
});

dropzone.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) {
    fileInput.files = e.dataTransfer.files;
    setSelectedFile(file);
  }
});

uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!selectedFile) return;
  const formData = new FormData();
  formData.append("file", selectedFile);
  await runAnalysis(() =>
    fetch("/api/analyze/file", { method: "POST", body: formData })
  );
});

// 6. Analysis Execution State Management
const placeholder = document.getElementById("placeholder");
const scanning = document.getElementById("scanning");
const report = document.getElementById("report");
const errorBox = document.getElementById("error-box");

const SCAN_MESSAGES = [
  "Reading advertisement content…",
  "Running OCR & text extraction…",
  "Normalizing vocabulary & NLP parsing…",
  "Checking heuristic fraud rules…",
  "Evaluating with Gradient Boosting classifier…",
  "Synthesizing final risk assessment…",
];

async function runAnalysis(requestFn) {
  placeholder.hidden = true;
  report.hidden = true;
  errorBox.hidden = true;
  scanning.hidden = false;

  const scanningText = document.getElementById("scanning-text");
  let step = 0;
  scanningText.textContent = SCAN_MESSAGES[0];
  const interval = setInterval(() => {
    step = (step + 1) % SCAN_MESSAGES.length;
    scanningText.textContent = SCAN_MESSAGES[step];
  }, 500);

  try {
    const res = await requestFn();
    const data = await res.json();
    clearInterval(interval);
    scanning.hidden = true;

    if (!res.ok || data.error) {
      errorBox.hidden = false;
      errorBox.textContent = data.error || "An error occurred while analyzing the posting.";
      return;
    }
    renderReport(data);
  } catch (err) {
    clearInterval(interval);
    scanning.hidden = true;
    errorBox.hidden = false;
    errorBox.textContent = "Could not reach the analysis backend. Please check server status.";
  }
}

// 7. Render Verdict Report (v1.0 Risk Assessment + backward compat)
const RISK_META = {
  Critical: { emoji: "🚨", label: "CRITICAL RISK", cls: "HIGH", color: "#f43f5e" },
  High: { emoji: "🔴", label: "HIGH RISK", cls: "HIGH", color: "#f43f5e" },
  Medium: { emoji: "🟡", label: "MEDIUM RISK", cls: "MEDIUM", color: "#f59e0b" },
  Low: { emoji: "🟢", label: "LOW RISK", cls: "LOW", color: "#10b981" },
};

function renderReport(data) {
  report.hidden = false;

  // New primary fields with fallback to legacy.
  const level = data.overall_risk_level
    || (data.risk_level ? data.risk_level.charAt(0) + data.risk_level.slice(1).toLowerCase() : "Low");
  const meta = RISK_META[level] || RISK_META.Low;
  const isRisky = level === "Critical" || level === "High";
  const isFakeLegacy = data.prediction === "Fake";

  const banner = document.getElementById("verdict-banner");
  banner.className = "verdict-banner " + (isRisky || isFakeLegacy ? "fake" : "genuine");

  const stamp = document.getElementById("stamp");
  stamp.textContent = `${meta.emoji} ${level.toUpperCase()}`;
  stamp.className = "stamp-badge " + (isRisky || isFakeLegacy ? "fake" : "genuine");

  const riskChip = document.getElementById("risk-chip");
  riskChip.textContent = meta.label;
  riskChip.className = "risk-pill " + meta.cls;

  const caption = document.getElementById("score-caption");
  if (data.summary) {
    caption.textContent = data.summary;
  } else {
    caption.textContent = isFakeLegacy
      ? "Estimated Scam & Fraud Probability"
      : "Confidence this advertisement is genuine";
  }

  // Score & Dial animation (prefer hybrid_score 0-1, fallback legacy 0-100).
  let displayScore;
  if (typeof data.hybrid_score === "number") {
    displayScore = data.hybrid_score <= 1 ? data.hybrid_score * 100 : data.hybrid_score;
  } else {
    displayScore = isFakeLegacy ? data.fake_probability : data.confidence_score;
  }
  const scoreVal = document.getElementById("score-value");
  scoreVal.textContent = Math.round(displayScore);

  const dialFill = document.getElementById("dial-fill");
  // Circumference for r=50: 2 * PI * 50 = 314.159
  const circumference = 314.159;
  const offset = circumference - (circumference * displayScore) / 100;

  requestAnimationFrame(() => {
    dialFill.style.stroke = meta.color;
    dialFill.style.strokeDashoffset = offset;
  });

  // Technical Metric Cards (support both new 0-1 and legacy 0-100 fields).
  const ruleVal = typeof data.rule_score === "number" && data.rule_score <= 1
    ? `${Math.round(data.rule_score * 100)}/100`
    : (data.rule_score_100 != null ? `${data.rule_score_100}/100` : `${data.rule_score}/100`);
  const mlVal = typeof data.ml_score === "number" && data.ml_score <= 1
    ? `${Math.round(data.ml_score * 100)}%`
    : `${Math.round(data.ml_probability)}%`;
  document.getElementById("rule-score-val").textContent = ruleVal;
  document.getElementById("ml-score-val").textContent = mlVal;
  document.getElementById("company-val").textContent = data.company_detected || "Not identified";
  document.getElementById("source-val").textContent = data.source || "Text input";

  // Risk summary + categories + confidence.
  const summaryEl = document.getElementById("risk-summary");
  if (summaryEl) summaryEl.textContent = data.summary || data.indicators_message || "Assessment complete.";
  const confBadge = document.getElementById("confidence-badge");
  if (confBadge) confBadge.textContent = data.confidence ? `${data.confidence} confidence` : "—";
  const catsEl = document.getElementById("risk-categories");
  if (catsEl) {
    catsEl.innerHTML = "";
    (data.risk_categories || []).forEach(cat => {
      const s = document.createElement("span");
      s.className = "sample-chip legit";
      s.textContent = cat;
      catsEl.appendChild(s);
    });
  }

  // Evidence Cards (prefer key_indicators, fallback legacy indicators).
  const list = document.getElementById("evidence-list");
  const noEvidence = document.getElementById("no-evidence");
  const countBadge = document.getElementById("evidence-count-badge");
  list.innerHTML = "";

  const keyInds = data.key_indicators || data.indicators || [];
  if (keyInds.length > 0) {
    noEvidence.hidden = true;
    countBadge.textContent = `${keyInds.length} detected`;
    keyInds.forEach(ind => {
      const item = document.createElement("div");
      item.className = "evidence-item";
      const title = escapeHtml(ind.name || ind.label || ind.id || "Indicator");
      const idTag = ind.id ? ` [${escapeHtml(ind.id)}]` : "";
      const body = escapeHtml(ind.explanation || ind.detail || "");
      const ev = ind.evidence ? `<p style="opacity:.75"><em>"${escapeHtml(ind.evidence)}"</em></p>` : (ind.detail ? "" : "");
      const sev = escapeHtml((ind.severity || "").toUpperCase());
      item.innerHTML = `
        <div class="evidence-body">
          <strong>${title}${idTag}</strong>
          <p>${body}</p>
          ${ev}
        </div>
        <span class="ev-badge ${sev}">${sev}</span>
      `;
      list.appendChild(item);
    });
  } else {
    noEvidence.hidden = false;
    countBadge.textContent = "0 signals";
    const textMsg = data.summary || data.indicators_message || "No obvious fraud indicators or red flags found.";
    noEvidence.querySelector("span").textContent = textMsg;
  }

  // Employer verification.
  const verText = document.getElementById("verification-text");
  if (verText) {
    const v = data.employer_verification;
    if (v) {
      verText.textContent = `Website: ${v.company_website} • Email match: ${v.email_domain_match} • Careers page: ${v.role_on_careers_page}. ${v.notes || ""}`;
    } else {
      verText.textContent = "Could not check.";
    }
  }

  // Recommended actions.
  const actionsEl = document.getElementById("actions-list");
  if (actionsEl) {
    actionsEl.innerHTML = "";
    (data.recommended_actions || []).forEach(a => {
      const item = document.createElement("div");
      item.className = "evidence-item";
      item.innerHTML = `<div class="evidence-body"><p>${escapeHtml(a)}</p></div>`;
      actionsEl.appendChild(item);
    });
  }

  // Raw / Processed Text
  const rawPreview = document.getElementById("extracted-preview");
  rawPreview.textContent = data.raw_text_preview || data.extracted_text_preview || "No preview text available.";
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str || "";
  return div.innerHTML;
}

// ------------------------------------------------------------------
// 8. Cyber Security Constellation & Neural Network Background Animation
// ------------------------------------------------------------------
(function initCyberBackground() {
  const canvas = document.getElementById("bg-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  let width = (canvas.width = window.innerWidth);
  let height = (canvas.height = window.innerHeight);

  window.addEventListener("resize", () => {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
  });

  // Mouse interaction
  const mouse = { x: null, y: null, radius: 140 };
  window.addEventListener("mousemove", (e) => {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
  });
  window.addEventListener("mouseleave", () => {
    mouse.x = null;
    mouse.y = null;
  });

  const nodeCount = Math.min(55, Math.floor((width * height) / 24000));
  const nodes = [];

  const colors = [
    { r: 6, g: 182, b: 212 },   // Cyan
    { r: 99, g: 102, b: 241 },  // Indigo
    { r: 59, g: 130, b: 246 },  // Blue
    { r: 16, g: 185, b: 129 }   // Emerald
  ];

  for (let i = 0; i < nodeCount; i++) {
    const col = colors[Math.floor(Math.random() * colors.length)];
    nodes.push({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - 0.5) * 0.7,
      vy: (Math.random() - 0.5) * 0.7,
      radius: Math.random() * 2 + 1.2,
      color: col,
      baseAlpha: Math.random() * 0.5 + 0.3,
      pulse: Math.random() * Math.PI,
    });
  }

  function animate() {
    ctx.clearRect(0, 0, width, height);

    // Update and draw nodes
    for (let i = 0; i < nodes.length; i++) {
      const node = nodes[i];

      node.x += node.vx;
      node.y += node.vy;
      node.pulse += 0.02;

      // Bounce off screen edges
      if (node.x < 0 || node.x > width) node.vx *= -1;
      if (node.y < 0 || node.y > height) node.vy *= -1;

      // Mouse gentle interaction
      if (mouse.x !== null && mouse.y !== null) {
        const dx = node.x - mouse.x;
        const dy = node.y - mouse.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < mouse.radius) {
          const force = (1 - dist / mouse.radius) * 1.5;
          node.x += (dx / dist) * force;
          node.y += (dy / dist) * force;
        }
      }

      const alpha = node.baseAlpha + Math.sin(node.pulse) * 0.15;
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${node.color.r}, ${node.color.g}, ${node.color.b}, ${Math.max(0.1, alpha)})`;
      ctx.shadowBlur = 8;
      ctx.shadowColor = `rgba(${node.color.r}, ${node.color.g}, ${node.color.b}, 0.5)`;
      ctx.fill();
      ctx.shadowBlur = 0;
    }

    // Connect close nodes with cyber laser lines
    const maxDist = 135;
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[i].x - nodes[j].x;
        const dy = nodes[i].y - nodes[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < maxDist) {
          const lineAlpha = (1 - dist / maxDist) * 0.22;
          ctx.beginPath();
          ctx.moveTo(nodes[i].x, nodes[i].y);
          ctx.lineTo(nodes[j].x, nodes[j].y);
          ctx.strokeStyle = `rgba(6, 182, 212, ${lineAlpha})`;
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      }
    }

    requestAnimationFrame(animate);
  }

  animate();
})();

