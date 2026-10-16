// ------------------------------------------------------------------
// Scam Sentry — Frontend Application Logic & Threat Analysis Engine
// Handles tabs, samples, OCR drag-and-drop, API communication,
// animated report rendering, and interactive cyber canvas background.
// ------------------------------------------------------------------

// 1. Tab Navigation
const tabs = document.querySelectorAll(".tab-btn");
const panels = document.querySelectorAll(".tab-panel");

function switchTab(targetTab) {
  tabs.forEach(t => {
    if (t.dataset.tab === targetTab) t.classList.add("active");
    else t.classList.remove("active");
  });
  panels.forEach(p => {
    if (p.dataset.panel === targetTab) p.classList.add("active");
    else p.classList.remove("active");
  });
}

tabs.forEach(tab => {
  tab.addEventListener("click", () => {
    if (tab.dataset.tab) switchTab(tab.dataset.tab);
  });
});

// 2. Text Input & Counter
const pasteForm = document.getElementById("paste-form");
const jobText = document.getElementById("job-text");
const charCount = document.getElementById("char-count");
const btnClearText = document.getElementById("btn-clear-text");

function updateCharCount() {
  if (!jobText || !charCount) return;
  const len = jobText.value.length;
  charCount.textContent = `${len.toLocaleString()} character${len === 1 ? '' : 's'}`;
}

if (jobText) jobText.addEventListener("input", updateCharCount);

if (btnClearText) {
  btnClearText.addEventListener("click", () => {
    if (jobText) {
      jobText.value = "";
      updateCharCount();
      jobText.focus();
    }
  });
}

// 3. Realistic Test Sample Presets
const SAMPLE_LEGIT = `Senior Cloud Platform Engineer
Company: Virtusa Technologies Inc.
Location: Colombo, Sri Lanka (Hybrid)

About the Role:
We are looking for an experienced Senior Cloud Platform Engineer to join our enterprise cloud architecture team. You will be designing scalable cloud microservices, automating CI/CD pipelines, and collaborating with cross-functional engineering leads.

Requirements:
- 4+ years of hands-on experience with Python, Node.js, or Go.
- Solid experience with Docker, Kubernetes, Terraform, and AWS / GCP.
- Strong background in microservices, PostgreSQL, and distributed caching.
- Bachelor's degree in Computer Science, Software Engineering, or equivalent.

Benefits:
- Competitive industry salary and comprehensive medical insurance for you and your family.
- Annual performance bonuses, professional training budget, and hybrid work flexibility.

How to Apply:
Please submit your resume and portfolio via our official careers portal at https://careers.virtusa.com/jobs/cloud-eng-2026 or email jobs@virtusa.com. We never ask for any payment or application processing fees.`;

const SAMPLE_FAKE = `URGENT VACANCY: DATA ENTRY SPECIALIST - WORK FROM HOME!
Earn $850 - $1,200 Weekly! No Experience or Qualifications Needed!

Company: International Global Data Solutions Ltd.
Immediate vacancies for data entry operators, typists, and form fillers. Work only 2-3 hours per day from your mobile phone or laptop. Flexible hours, students and housewives welcome!

Requirements:
- Must have an internet connection and a bank account to receive weekly payments.
- Age 18+
- Immediate joining today! Only 3 positions left!

Application Instructions:
Before starting work and receiving your company equipment laptop, all selected applicants MUST pay a refundable Registration & Security Verification Fee of $50 (Rs. 15,000). Send payment receipt to our hiring manager via Telegram @GlobalHR_Admin or email globalcareer.hiring2026@gmail.com. Once fee is paid, your training kit and first assignment will be dispatched immediately.`;

const SAMPLE_WHATSAPP = `Online Part-Time Customer Review Assistant
Salary: $250 - $600 Daily! Instant daily cash payouts guaranteed!

Huge multinational corporation looking for energetic candidates to do simple product rating and review tasks on your smartphone.
- No resume required!
- No interview!
- Zero experience required!
- Guaranteed instant income deposited directly to your crypto wallet or bank!

Hurry, apply immediately! Contact Miss Emily right now on WhatsApp at +94 71 999 8888 or Telegram @Emily_VIP_Tasks to claim your sign-up bonus.`;

document.getElementById("load-sample-legit")?.addEventListener("click", () => {
  switchTab("paste");
  if (jobText) {
    jobText.value = SAMPLE_LEGIT;
    updateCharCount();
  }
});

document.getElementById("load-sample-fake")?.addEventListener("click", () => {
  switchTab("paste");
  if (jobText) {
    jobText.value = SAMPLE_FAKE;
    updateCharCount();
  }
});

document.getElementById("load-sample-whatsapp")?.addEventListener("click", () => {
  switchTab("paste");
  if (jobText) {
    jobText.value = SAMPLE_WHATSAPP;
    updateCharCount();
  }
});

// 4. File Drag & Drop Handling (OCR Intake)
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const dzFilename = document.getElementById("dz-filename");
const fileHint = document.getElementById("file-hint");
const btnClearFile = document.getElementById("btn-clear-file");
const uploadBtn = document.getElementById("upload-btn");
const uploadForm = document.getElementById("upload-form");

let currentFile = null;

function setFile(file) {
  if (!file) {
    currentFile = null;
    if (fileInput) fileInput.value = "";
    if (dzFilename) dzFilename.textContent = "Drop image or PDF flyer here";
    if (fileHint) fileHint.textContent = "No file selected";
    if (btnClearFile) btnClearFile.style.display = "none";
    if (uploadBtn) uploadBtn.disabled = true;
    return;
  }

  const validExts = [".pdf", ".png", ".jpg", ".jpeg"];
  const ext = "." + file.name.split(".").pop().toLowerCase();
  if (!validExts.includes(ext)) {
    alert("Unsupported file format. Please upload PDF, PNG, JPG, or JPEG.");
    return;
  }

  currentFile = file;
  const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
  if (dzFilename) dzFilename.textContent = `${file.name} (${sizeMb} MB)`;
  if (fileHint) fileHint.textContent = `Ready for OCR inspection &bull; ${file.type || ext.toUpperCase()}`;
  if (btnClearFile) btnClearFile.style.display = "inline-block";
  if (uploadBtn) uploadBtn.disabled = false;
}

if (dropzone) {
  ["dragenter", "dragover"].forEach(eventName => {
    dropzone.addEventListener(eventName, e => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.add("drag-active");
    });
  });

  ["dragleave", "drop"].forEach(eventName => {
    dropzone.addEventListener(eventName, e => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.remove("drag-active");
    });
  });

  dropzone.addEventListener("drop", e => {
    const files = e.dataTransfer.files;
    if (files && files.length > 0) setFile(files[0]);
  });
}

if (fileInput) {
  fileInput.addEventListener("change", () => {
    if (fileInput.files && fileInput.files.length > 0) {
      setFile(fileInput.files[0]);
    }
  });
}

if (btnClearFile) {
  btnClearFile.addEventListener("click", () => setFile(null));
}

// 5. Form Submissions
if (pasteForm) {
  pasteForm.addEventListener("submit", async e => {
    e.preventDefault();
    const text = jobText?.value?.trim();
    if (!text || text.length < 15) {
      alert("Please provide at least 15 characters of advertisement text to analyze.");
      return;
    }

    runAnalysis(() =>
      fetch("/api/analyze/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      })
    );
  });
}

if (uploadForm) {
  uploadForm.addEventListener("submit", async e => {
    e.preventDefault();
    if (!currentFile) {
      alert("Please choose a flyer image or PDF document first.");
      return;
    }

    const formData = new FormData();
    formData.append("file", currentFile);

    runAnalysis(() =>
      fetch("/api/analyze/file", {
        method: "POST",
        body: formData,
      })
    );
  });
}

// 6. Analysis Execution & Radar Cycling
const placeholder = document.getElementById("placeholder");
const scanning = document.getElementById("scanning");
const report = document.getElementById("report");
const errorBox = document.getElementById("error-box");

const SCAN_MESSAGES = [
  "Reading advertisement content & payload...",
  "Executing OCR and forensic image extraction...",
  "Normalizing vocabulary & running NLP parsing...",
  "Evaluating deterministic fraud rules C1-C4 / H1-H5...",
  "Calculating GradientBoosting ML probability...",
  "Verifying company domains & synthesizing verdict...",
];

async function runAnalysis(requestFn) {
  if (placeholder) placeholder.hidden = true;
  if (report) report.hidden = true;
  if (errorBox) errorBox.hidden = true;
  if (scanning) scanning.hidden = false;

  const scanningText = document.getElementById("scanning-text");
  let step = 0;
  if (scanningText) scanningText.textContent = SCAN_MESSAGES[0];
  const interval = setInterval(() => {
    step = (step + 1) % SCAN_MESSAGES.length;
    if (scanningText) scanningText.textContent = SCAN_MESSAGES[step];
  }, 450);

  try {
    const res = await requestFn();
    const data = await res.json();
    clearInterval(interval);
    if (scanning) scanning.hidden = true;

    if (!res.ok || data.error) {
      if (errorBox) {
        errorBox.hidden = false;
        errorBox.textContent = data.error || "An error occurred while evaluating the posting.";
      }
      return;
    }
    renderReport(data);
  } catch (err) {
    clearInterval(interval);
    if (scanning) scanning.hidden = true;
    if (errorBox) {
      errorBox.hidden = false;
      errorBox.textContent = "Could not reach the analysis backend. Please ensure the server is running.";
    }
  }
}

// 7. Render Verdict Report (Full Risk Engine + Backward Compatibility)
const RISK_META = {
  Critical: { emoji: "🚨", label: "CRITICAL THREAT", cls: "CRITICAL", color: "#ff2d55" },
  High:     { emoji: "🔴", label: "HIGH RISK",      cls: "HIGH",     color: "#f43f5e" },
  Medium:   { emoji: "🟡", label: "MEDIUM RISK",    cls: "MEDIUM",   color: "#f59e0b" },
  Low:      { emoji: "🟢", label: "LOW RISK / SAFE", cls: "LOW",     color: "#10b981" },
};

function renderReport(data) {
  if (!report) return;
  report.hidden = false;

  // Determine risk level (from new risk engine or legacy classifier)
  const level = data.overall_risk_level
    || (data.risk_level ? data.risk_level.charAt(0).toUpperCase() + data.risk_level.slice(1).toLowerCase() : "Low");
  const meta = RISK_META[level] || RISK_META.Low;
  const isRisky = level === "Critical" || level === "High";
  const isFakeLegacy = data.prediction === "Fake";

  // Banner
  const banner = document.getElementById("verdict-banner");
  if (banner) banner.className = "verdict-banner " + (isRisky || isFakeLegacy ? "fake" : "genuine");

  // Stamp badge
  const stamp = document.getElementById("stamp");
  if (stamp) {
    stamp.textContent = `${meta.emoji} ${level.toUpperCase()}`;
    stamp.className = "stamp-badge " + (isRisky || isFakeLegacy ? "fake" : "genuine");
  }

  // Risk Pill
  const riskChip = document.getElementById("risk-chip");
  if (riskChip) {
    riskChip.textContent = meta.label;
    riskChip.className = "risk-pill " + meta.cls;
  }

  // Caption / Summary
  const caption = document.getElementById("score-caption");
  if (caption) {
    if (data.summary) {
      caption.textContent = data.summary;
    } else {
      caption.textContent = isRisky || isFakeLegacy
        ? "Estimated Scam & Fraud Threat Probability"
        : "Confidence this advertisement is genuine & verified";
    }
  }

  // Score & Dial Gauge (0-100)
  let displayScore;
  if (typeof data.hybrid_score === "number") {
    displayScore = data.hybrid_score <= 1 ? data.hybrid_score * 100 : data.hybrid_score;
  } else {
    displayScore = isFakeLegacy ? data.fake_probability : data.confidence_score;
  }
  const scoreVal = document.getElementById("score-value");
  if (scoreVal) scoreVal.textContent = Math.round(displayScore || 0);

  const dialFill = document.getElementById("dial-fill");
  if (dialFill) {
    const circumference = 314.159;
    const offset = circumference - (circumference * (displayScore || 0)) / 100;
    requestAnimationFrame(() => {
      dialFill.style.stroke = meta.color;
      dialFill.style.strokeDashoffset = offset;
    });
  }

  // Technical Metric Cards
  const ruleVal = typeof data.rule_score === "number" && data.rule_score <= 1
    ? `${Math.round(data.rule_score * 100)}/100`
    : (data.rule_score_100 != null ? `${data.rule_score_100}/100` : `${data.rule_score || 0}/100`);

  const mlVal = typeof data.ml_score === "number" && data.ml_score <= 1
    ? `${Math.round(data.ml_score * 100)}%`
    : `${Math.round(data.ml_probability || 0)}%`;

  const elRule = document.getElementById("rule-score-val");
  if (elRule) elRule.textContent = ruleVal;

  const elMl = document.getElementById("ml-score-val");
  if (elMl) elMl.textContent = mlVal;

  const elComp = document.getElementById("company-val");
  if (elComp) elComp.textContent = data.company_detected || "Not identified";

  const elSrc = document.getElementById("source-val");
  if (elSrc) elSrc.textContent = data.source || "Direct text";

  // ML Transparency Details
  const mlCaveat = document.getElementById("ml-caveat");
  const mlRaw = document.getElementById("ml-raw-stats");
  if (data.ml_meta) {
    if (mlCaveat && data.ml_meta.caveat) mlCaveat.textContent = data.ml_meta.caveat;
    if (mlRaw) {
      mlRaw.textContent = `Raw ML: ${(data.ml_meta.raw_probability * 100).toFixed(1)}% | Calibrated: ${(data.ml_meta.calibrated_probability * 100).toFixed(1)}% | Training: ${data.ml_meta.training_dataset || "synthetic"}`;
    }
  }

  // Evidence Cards
  const list = document.getElementById("evidence-list");
  const noEvidence = document.getElementById("no-evidence");
  const countBadge = document.getElementById("evidence-count-badge");
  if (list) list.innerHTML = "";

  const indicators = data.key_indicators || data.indicators || [];
  if (indicators.length > 0) {
    if (noEvidence) noEvidence.hidden = true;
    if (countBadge) countBadge.textContent = `${indicators.length} detected`;
    indicators.forEach(ind => {
      const item = document.createElement("div");
      item.className = "evidence-item";
      const sev = (ind.severity || "Medium").toUpperCase();
      item.innerHTML = `
        <div class="evidence-body">
          <strong>${ind.id ? ind.id + " &bull; " : ""}${escapeHtml(ind.label || ind.indicator || "Indicator")}</strong>
          <p>${escapeHtml(ind.detail || ind.description || "")}</p>
          ${ind.quote ? `<div class="evidence-quote">&ldquo;${escapeHtml(ind.quote)}&rdquo;</div>` : ""}
        </div>
        <span class="ev-badge ${sev}">${sev}</span>
      `;
      list.appendChild(item);
    });
  } else {
    if (noEvidence) noEvidence.hidden = false;
    if (countBadge) countBadge.textContent = "0 signals";
    const textMsg = data.indicators_message || "No obvious fraud indicators or red flags found in this posting.";
    if (noEvidence) {
      const sp = noEvidence.querySelector("span");
      if (sp) sp.textContent = textMsg;
    }
  }

  // Recommended Actions Section
  const actionsSec = document.getElementById("actions-section");
  const actionsList = document.getElementById("actions-list");
  if (actionsSec && actionsList) {
    actionsList.innerHTML = "";
    const actions = data.recommended_actions || [];
    if (actions.length > 0) {
      actionsSec.hidden = false;
      actions.forEach(act => {
        const item = document.createElement("div");
        item.className = "action-item";
        const title = typeof act === "string" ? act : (act.action || act.title || "");
        const detail = typeof act === "object" ? (act.detail || "") : "";
        item.innerHTML = `
          <span class="action-bullet">&#10004;</span>
          <div class="action-content">
            <strong>${escapeHtml(title)}</strong>
            ${detail ? `<p>${escapeHtml(detail)}</p>` : ""}
          </div>
        `;
        actionsList.appendChild(item);
      });
    } else {
      actionsSec.hidden = true;
    }
  }

  // Raw / Extracted Text
  const rawPreview = document.getElementById("extracted-preview");
  if (rawPreview) {
    rawPreview.textContent = data.extracted_text_preview || data.extracted_text || "No preview text available.";
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str || "";
  return div.innerHTML;
}

// ------------------------------------------------------------------
// 8. Cyber Security Constellation & Neural Mesh Canvas Animation
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

  const mouse = { x: null, y: null, maxDist: 140 };
  window.addEventListener("mousemove", e => {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
  });
  window.addEventListener("mouseleave", () => {
    mouse.x = null;
    mouse.y = null;
  });

  const PARTICLE_COUNT = Math.min(80, Math.floor((width * height) / 16000));
  const particles = [];

  class Particle {
    constructor() {
      this.reset();
    }
    reset() {
      this.x = Math.random() * width;
      this.y = Math.random() * height;
      this.vx = (Math.random() - 0.5) * 0.55;
      this.vy = (Math.random() - 0.5) * 0.55;
      this.radius = Math.random() * 1.8 + 0.8;
      this.baseAlpha = Math.random() * 0.4 + 0.2;
    }
    update() {
      this.x += this.vx;
      this.y += this.vy;
      if (this.x < 0 || this.x > width) this.vx *= -1;
      if (this.y < 0 || this.y > height) this.vy *= -1;
    }
    draw() {
      ctx.beginPath();
      ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(0, 240, 255, ${this.baseAlpha})`;
      ctx.shadowBlur = 8;
      ctx.shadowColor = "#00f0ff";
      ctx.fill();
      ctx.shadowBlur = 0;
    }
  }

  for (let i = 0; i < PARTICLE_COUNT; i++) {
    particles.push(new Particle());
  }

  function animate() {
    ctx.clearRect(0, 0, width, height);

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      p.update();
      p.draw();

      // Inter-particle connections
      for (let j = i + 1; j < particles.length; j++) {
        const p2 = particles[j];
        const dx = p.x - p2.x;
        const dy = p.y - p2.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 110) {
          const alpha = (1 - dist / 110) * 0.22;
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.strokeStyle = `rgba(0, 240, 255, ${alpha})`;
          ctx.lineWidth = 0.8;
          ctx.stroke();
        }
      }

      // Mouse interactive links
      if (mouse.x !== null) {
        const mdx = p.x - mouse.x;
        const mdy = p.y - mouse.y;
        const mdist = Math.sqrt(mdx * mdx + mdy * mdy);
        if (mdist < mouse.maxDist) {
          const malpha = (1 - mdist / mouse.maxDist) * 0.4;
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(mouse.x, mouse.y);
          ctx.strokeStyle = `rgba(99, 102, 241, ${malpha})`;
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      }
    }

    requestAnimationFrame(animate);
  }

  animate();
})();
