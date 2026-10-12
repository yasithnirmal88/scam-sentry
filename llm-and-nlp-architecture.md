# career-ops — LLM, NLP, and what prompts cannot build

> Companion to `career-ops-guide.md` and `recreate-from-scratch.md`. Answers two questions: (1) where the LLMs/NLPs actually live in the career-ops files, and (2) which parts of a similar project must be written as real code because they **cannot** be built from prompts alone.

---

## Part 1 — Where the LLMs/NLPs are located

career-ops has **two "brains"**. The line between them is the whole architecture: prompts for open-ended judgment, code for everything that must be exactly right.

### A. The prompt-brain (judgment — executed by YOUR AI CLI's LLM)

These are not code. They are Markdown files the hosting AI reads and reasons over. This is the largest LLM surface in the system.

| File | What the LLM does |
|---|---|
| `modes/_shared.md` | Scoring system, archetype detection, posting-legitimacy signals, risk indicators, global rules |
| `modes/oferta.md` | The A–H evaluation prompt (the heart of the tool) |
| `modes/*.md` | All workflows: scan, pipeline, apply, pdf, cover, email, tracker, batch, interview, negotiation, outreach |
| `modes/<market>/*.md` | Localized market variants (19 markets) with local legal/salary vocabulary |
| `batch/batch-prompt.md` | Headless batch-worker prompt (complete evaluation + PDF + tracker line) |
| `AGENTS.md` / `CLAUDE.md` / `CODEX.md` / `OPENCODE.md` | Global agent instructions read at session start |

Here "NLP" is the model doing classification, scoring, summarization, and generation on the job description and the candidate's files.

### B. Code that calls an LLM API directly (the standalone evaluators)

These embed the same scoring prompt but call a model over HTTP on their own — no interactive AI CLI needed. They are the only `.mjs` files in the repo that make real model calls.

| File | Model / endpoint | Purpose |
|---|---|---|
| `gemini-eval.mjs` | Google Gemini (`@google/generative-ai` SDK) | Standalone job-offer evaluator (Google free tier) |
| `batch-evaluate-gemini.mjs` | Google Gemini SDK | Batch evaluation driver around Gemini |
| `scan-hn.mjs` | Google Gemini SDK | Classifies/filters Hacker News job listings |
| `openai-eval.mjs` | OpenAI-compatible `/chat/completions` (OpenAI, OpenRouter, Groq, vLLM, LM Studio) | Standalone evaluator against any compatible endpoint |
| `openai-tailor.mjs` | OpenAI-compatible `/chat/completions` | Headless CV tailoring from an evaluation report |
| `ollama-eval.mjs` | Ollama local server (`/v1/chat/completions`) | Fully local evaluation, no cloud |
| `openrouter-runner.mjs` | OpenRouter API (`chat/completions` + `models`) | One-command scan / evaluate / pipeline / apply / models |
| `eval-golden.mjs` | Replays recorded fixtures; `--live` shells out to `openai-eval.mjs` | Deterministic CI harness for the scoring prompt |
| `rank-pipeline.mjs` | *Opt-in* — shells out to your installed agent CLI (`claude -p`, `opencode run`, `codex exec`, …) | Adds `rank: {score}/5 — {reason}` annotations to pending pipeline rows; never filters. Off by default |

Tests that stub these calls hermetically: `tests/ollama-eval-endpoint.test.mjs`, `tests/hn-scanner.test.mjs`, `tests/ci-gemini-check.test.mjs` (the last pins the dependency only, no live call).

### C. NLP heuristics — deterministic algorithms, zero LLM tokens

Classic tokenization / similarity / extraction in pure Node. Use these when you want "NLP without a model" — testable, free, deterministic.

| File | Technique |
|---|---|
| `jd-skill-gap.mjs` | Regex JD skill extraction + CV classification (`existing / supportedByResume / gap`) |
| `jd-similarity.mjs` | Tokenization + Jaccard similarity → `reuse / reuse-with-edits / regenerate` |
| `skill-extract.mjs` | Skill tokenizer with acronym expansion (`llm → LLMs`) |
| `keyword-match.mjs` | Keyword coverage % from a report vs CV (present/thin/missing) |
| `match-star.mjs` | STAR-story ↔ behavioral-question matcher (tokenize + stopword-filtered overlap) |
| `role-matcher.mjs` | Job-title tokenizer + Jaccard, seniority-aware |
| `detect-reposts.mjs` | Title-identity index over scan history; flags 2+ relists/90d |
| `fingerprint-core.mjs` | Text fingerprinting + normalized `similarity()` for dedup |
| `invite-match.mjs` | Token-overlap similarity of company names to match invites |
| `linkedin-join.mjs` | Tokenizes/case+diacritic-folds LinkedIn exports vs tracker companies |
| `cv-title-check.mjs` | Exact (never fuzzy) title-consistency checker |
| `story-provenance-check.mjs` | Regex provenance-marker extraction over story-bank |
| `upskill.mjs` | Weighted skill-gap map (tokenizer shared with jd-skill-gap) |
| `ats-payload.mjs` | Deterministic payload transforms + lints |
| `analyze-patterns.mjs` | Per-ATS advance rates + rejection patterns |

### D. Everything else — no LLM, no NLP

Scanner + providers (including the SSRF-guarded transport `providers/_http.mjs`, `_ip-guard.mjs`, `_dns-cache.mjs`), tracker/merge/dedup/status scripts, liveness checker, PDF/LaTeX generation, stats, updater, dashboard, batch runner, and all test suites. The **zero-token guarantee is absolute in `providers/`**: no provider file calls an LLM, and a test (`tests/providers-http-coverage.test.mjs`) fails the suite if any provider calls the raw global `fetch()` instead of the guarded transport.

---

## Part 2 — What your project needs that CANNOT be built by prompts

This is the important design truth: **prompts can only produce judgment output. They cannot enforce, secure, or reproduce anything.** In a career-ops-like system, the parts below must be real, deterministic code — asking an LLM agent to do them via a prompt would be unreliable, unsafe, or prohibitively expensive.

| Component | Why a prompt cannot do it |
|---|---|
| **Scanner + SSRF-guarded HTTP transport** (`scan.mjs`, `providers/*`, `_http.mjs`, `_ip-guard.mjs`, `_dns-cache.mjs`) | Security is a hard guarantee, not a suggestion: host allowlists checked *before* fetch, `redirect:'error'` (never auto-follow), loopback/link-local/metadata addresses blocked, DNS resolved so the guard sees the real address. Also must be zero-token: one LLM call per listing would be slow and cost real money. |
| **Tracker / pipeline integrity** (`merge-tracker.mjs`, `set-status.mjs`, `dedup-tracker.mjs`, `verify-pipeline.mjs` 18 checks) | Atomic, locked, validated writes to `applications.md`. The whole point is that an LLM never hand-edits the tracker — that path is handled by code that normalizes, dedupes, sorts, and refuses malformed rows. |
| **PDF / LaTeX generation** (`generate-pdf.mjs`, `generate-latex.mjs`) | Playwright rendering and layout must be deterministic and byte-comparable across runs. |
| **Liveness checking** (`check-liveness.mjs` / `liveness-core.mjs`) | Exact HTTP semantics: only explicit closure evidence (404/410, expired message) = closed; anything unreadable is *unconfirmed*, never closed. Deterministic, zero-token. |
| **Output validators that catch LLM drift** (`verify-risk.mjs`, `check-jd-archive.mjs`) | The model will eventually drift or hallucinate. The fix is code that validates the model's output — section chain order, Machine Summary YAML schema, archived-JD presence — not more prompting. |
| **NLP heuristics** (`jd-similarity.mjs`, `match-star.mjs`, `keyword-match.mjs`, …) | If you want scoring that is testable, deterministic, and free, write algorithms (tokenize, Jaccard, regex), not prompts. |
| **Tests + CI** (`test-all.mjs`, `scripts/check-syntax.mjs`, GitHub Actions) | Deterministic by definition. Suites are discovered by glob in `tests/`, so a new test runs the moment it exists. |
| **Atomic report-number reservation** (`reserve-report-num.mjs`) | Parallel workers must not race on `max+1` — that is a code-level locking problem (#749). |
| **Updater** (`update-system.mjs`) | Backs up, re-execs the target updater, and checks out only system paths — file operations and path enforcement must be in code. |

### The division, in one sentence

- **Prompts (LLM)**: evaluation, scoring, archetype detection, CV tailoring, cover letters, form answers, interview prep, negotiation — every open-ended judgment call.
- **Code (deterministic)**: fetching and scoping what can be fetched (SSRF), storing and merging data (tracker), rendering PDFs, checking liveness, validating model output, all tests — everything that must be exact, secure, reproducible, or free.

An LLM evaluates and recommends; the deterministic backbone stores, protects, renders, and verifies. **Build both.** The lines are deliberately enforced: `verify-risk.mjs` is "a safety net, not a replacement" for the Risk Assessment layer, and `merge-tracker.mjs` is where every LLM-produced evaluation lands as a validated row.

---

## Implication for your university project

- The **judgment layers** (evaluation, drafting) can literally be a prompt file plus one small `chat/completions` caller (~60 lines in an OpenAI-compatible style) — same pattern as `openai-eval.mjs` / `ollama-eval.mjs`, but you write it yourself.
- The **deterministic backbone** (scanner, SSRF guard, tracker with dedup/merge, PDF, validators, tests) is code *you* must write — and it is also the strongest "engineering" content for a project report, because it is real software engineering rather than calling a model.
- Choose your own LLM: **free everywhere** — Ollama (local, $0), Google Gemini free tier, Antigravity CLI free tier, or OpenRouter's `:free` models. Scanner stays zero-token so daily scanning costs nothing even with a paid model.
- All commits done by you = you write the code and prompts yourself, referencing these ideas (patterns are not copyrightable), not copying the files. career-ops is MIT, so even reuse is legal — but only attribution of copied code, and never "all my work".

---

*Part of the Fake_job_detector project research set (career-ops v1.35.0).*