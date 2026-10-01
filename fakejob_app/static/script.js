// ------------------------------------------------------------------
// Scam Sentry frontend logic: tab switching, drag/drop upload,
// API calls to the Flask backend, and rendering the verdict report.
// ------------------------------------------------------------------

const tabs = document.querySelectorAll(".tab");
const panels = document.querySelectorAll(".tab-panel");

tabs.forEach(tab => {
  tab.addEventListener("click", () => {
    tabs.forEach(t => t.classList.remove("active"));
    panels.forEach(p => p.classList.remove("active"));
    tab.classList.add("active");
    document.querySelector(`.tab-panel[data-panel="${tab.dataset.tab}"]`).classList.add("active");
  });
});

// ---------------- paste-text form ----------------
const pasteForm = document.getElementById("paste-form");
const jobText = document.getElementById("job-text");
const charCount = document.getElementById("char-count");

jobText.addEventListener("input", () => {
  charCount.textContent = `${jobText.value.length} characters`;
});

pasteForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = jobText.value.trim();
  if (!text) return;
  await runAnalysis(() =>
    fetch("/api/analyze/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    })
  );
});

// ---------------- file-upload form ----------------
const uploadForm = document.getElementById("upload-form");
const fileInput = document.getElementById("file-input");
const dropzone = document.getElementById("dropzone");
const dzFilename = document.getElementById("dz-filename");
const fileHint = document.getElementById("file-hint");
const uploadBtn = document.getElementById("upload-btn");
let selectedFile = null;

function setSelectedFile(file) {
  selectedFile = file || null;
  if (selectedFile) {
    dzFilename.textContent = selectedFile.name;
    fileHint.textContent = `${(selectedFile.size / 1024).toFixed(0)} KB ready`;
    uploadBtn.disabled = false;
  } else {
    dzFilename.textContent = "Drop a PDF or image here";
    fileHint.textContent = "No file selected";
    uploadBtn.disabled = true;
  }
}

fileInput.addEventListener("change", () => setSelectedFile(fileInput.files[0]));

["dragenter", "dragover"].forEach(evt =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.add("drag");
  })
);
["dragleave", "drop"].forEach(evt =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag");
  })
);
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

// ---------------- shared analysis flow ----------------
const placeholder = document.getElementById("placeholder");
const scanning = document.getElementById("scanning");
const report = document.getElementById("report");
const errorBox = document.getElementById("error-box");

const SCAN_MESSAGES = [
  "Reading document…",
  "Running OCR and preprocessing…",
  "Extracting fraud-pattern indicators…",
  "Scoring with the text classifier…",
  "Compiling the evidence report…",
];

async function runAnalysis(requestFn) {
  placeholder.hidden = true;
  report.hidden = true;
  errorBox.hidden = true;
  scanning.hidden = false;

  const scanningText = document.getElementById("scanning-text");
  let i = 0;
  scanningText.textContent = SCAN_MESSAGES[0];
  const interval = setInterval(() => {
    i = (i + 1) % SCAN_MESSAGES.length;
    scanningText.textContent = SCAN_MESSAGES[i];
  }, 550);

  try {
    const res = await requestFn();
    const data = await res.json();
    clearInterval(interval);
    scanning.hidden = true;

    if (!res.ok || data.error) {
      errorBox.hidden = false;
      errorBox.textContent = data.error || "Something went wrong while analysing this posting.";
      return;
    }
    renderReport(data);
  } catch (err) {
    clearInterval(interval);
    scanning.hidden = true;
    errorBox.hidden = false;
    errorBox.textContent = "Could not reach the analysis server. Please try again.";
  }
}

function renderReport(data) {
  report.hidden = false;

  const stamp = document.getElementById("stamp");
  stamp.textContent = data.prediction.toUpperCase();
  stamp.className = "stamp " + (data.prediction === "Fake" ? "fake" : "genuine");

  const riskChip = document.getElementById("risk-chip");
  riskChip.textContent = `${data.risk_level} RISK`;
  riskChip.className = "risk-chip " + data.risk_level;

  const scoreVal = document.getElementById("score-value");
  const dialFill = document.getElementById("dial-fill");
  const caption = document.getElementById("score-caption");

  const displayScore = data.prediction === "Fake" ? data.fake_probability : data.confidence_score;
  scoreVal.textContent = Math.round(displayScore);
  caption.textContent = data.prediction === "Fake"
    ? "Estimated fraud probability"
    : "Confidence this posting is genuine";

  const circumference = 326.7;
  const offset = circumference - (circumference * displayScore) / 100;
  const dialColor = data.risk_level === "HIGH" ? "#B8433B"
    : data.risk_level === "MEDIUM" ? "#C98A2C" : "#2F9E6E";
  requestAnimationFrame(() => {
    dialFill.style.stroke = dialColor;
    dialFill.style.strokeDashoffset = offset;
  });

  const list = document.getElementById("evidence-list");
  const noEvidence = document.getElementById("no-evidence");
  list.innerHTML = "";
  if (data.indicators && data.indicators.length) {
    noEvidence.hidden = true;
    data.indicators.forEach(ind => {
      const li = document.createElement("li");
      li.innerHTML = `
        <span></span>
        <div class="ev-text"><strong>${escapeHtml(ind.label)}</strong><span>${escapeHtml(ind.detail || "")}</span></div>
        <span class="ev-badge ${ind.severity}">${ind.severity}</span>
      `;
      list.appendChild(li);
    });
  } else {
    noEvidence.hidden = false;
    noEvidence.textContent = data.indicators_message || "No fraud indicators detected.";
  }

  document.getElementById("rule-score-val").textContent = `${data.rule_score}/100`;
  document.getElementById("ml-score-val").textContent = `${data.ml_probability}%`;
  document.getElementById("company-val").textContent = data.company_detected || "Not found";
  document.getElementById("source-val").textContent = data.source || "—";
  document.getElementById("extracted-preview").textContent = data.extracted_text_preview || "";
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
