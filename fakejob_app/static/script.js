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

// 7. Render Verdict Report
function renderReport(data) {
  report.hidden = false;

  const isFake = data.prediction === "Fake";
  const banner = document.getElementById("verdict-banner");
  banner.className = "verdict-banner " + (isFake ? "fake" : "genuine");

  const stamp = document.getElementById("stamp");
  stamp.textContent = isFake ? "SUSPICIOUS / SCAM" : "LEGITIMATE / GENUINE";
  stamp.className = "stamp-badge " + (isFake ? "fake" : "genuine");

  const riskChip = document.getElementById("risk-chip");
  riskChip.textContent = `${data.risk_level} RISK`;
  riskChip.className = "risk-pill " + data.risk_level;

  const caption = document.getElementById("score-caption");
  caption.textContent = isFake
    ? "Estimated Scam & Fraud Probability"
    : "Confidence this advertisement is genuine";

  // Score & Dial animation
  const displayScore = isFake ? data.fake_probability : data.confidence_score;
  const scoreVal = document.getElementById("score-value");
  scoreVal.textContent = Math.round(displayScore);

  const dialFill = document.getElementById("dial-fill");
  // Circumference for r=50: 2 * PI * 50 = 314.159
  const circumference = 314.159;
  const offset = circumference - (circumference * displayScore) / 100;
  
  let dialColor = "#10b981"; // Emerald
  if (data.risk_level === "HIGH") {
    dialColor = "#f43f5e"; // Rose / Red
  } else if (data.risk_level === "MEDIUM") {
    dialColor = "#f59e0b"; // Amber
  }

  requestAnimationFrame(() => {
    dialFill.style.stroke = dialColor;
    dialFill.style.strokeDashoffset = offset;
  });

  // Technical Metric Cards
  document.getElementById("rule-score-val").textContent = `${data.rule_score}/100`;
  document.getElementById("ml-score-val").textContent = `${Math.round(data.ml_probability)}%`;
  document.getElementById("company-val").textContent = data.company_detected || "Not identified";
  document.getElementById("source-val").textContent = data.source || "Text input";

  // Evidence Cards
  const list = document.getElementById("evidence-list");
  const noEvidence = document.getElementById("no-evidence");
  const countBadge = document.getElementById("evidence-count-badge");
  list.innerHTML = "";

  if (data.indicators && data.indicators.length > 0) {
    noEvidence.hidden = true;
    countBadge.textContent = `${data.indicators.length} detected`;
    data.indicators.forEach(ind => {
      const item = document.createElement("div");
      item.className = "evidence-item";
      item.innerHTML = `
        <div class="evidence-body">
          <strong>${escapeHtml(ind.label)}</strong>
          <p>${escapeHtml(ind.detail || "")}</p>
        </div>
        <span class="ev-badge ${ind.severity}">${ind.severity}</span>
      `;
      list.appendChild(item);
    });
  } else {
    noEvidence.hidden = false;
    countBadge.textContent = "0 signals";
    const textMsg = data.indicators_message || "No obvious fraud indicators or red flags found.";
    noEvidence.querySelector("span").textContent = textMsg;
  }

  // Raw / Processed Text
  const rawPreview = document.getElementById("extracted-preview");
  rawPreview.textContent = data.extracted_text_preview || "No preview text available.";
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str || "";
  return div.innerHTML;
}

// ------------------------------------------------------------------
