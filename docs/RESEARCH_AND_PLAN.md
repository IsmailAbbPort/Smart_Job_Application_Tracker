# Smart Job Application Tracker — Research Briefing & Build Plan

> Reference doc for the portfolio project. Two parts:
> **Part A** is the concept briefing (understand *why* each piece exists, with citations).
> **Part B** is the phased build plan.
>
> Decisions locked up front: **Python-first (FastAPI) backend + thin React frontend**, **API-first job data with selective polite scraping**, built as a **polished showcase**, dogfooded during a real EU remote job search.
>
> **New to embeddings / RAG / rerank / pgvector / evals? Read [CONCEPTS_PRIMER.md](CONCEPTS_PRIMER.md) first** — it explains every fundamental this plan assumes, from zero, and maps each to the build phase that uses it.

---

## Part A — Concept Briefing

Everything below that has a source was adversarially fact-checked (3-vote verification) during research. Uncited lines are my own architectural judgement, flagged where it matters.

### A1. The job data problem (this is 60% of the real work)

The headline says "scrape job boards," but scraping is the *last* resort, not the first. The order of preference is: **official API → public JSON feed → polite scrape**. Reasons: APIs are stable, legal, and don't break mid-demo; scraping the big boards (LinkedIn, Indeed) is a losing fight (see A2).

**Free, no-auth sources that are genuinely good for EU + remote — use these as the backbone:**

| Source | Endpoint / access | Auth | EU/remote fit | Notes |
|---|---|---|---|---|
| **Arbeitnow** | `arbeitnow.com/api/job-board-api` | None | **Best EU fit.** "Contains some of the latest jobs in Europe," has a `remote` field | Aggregates from Greenhouse, SmartRecruiters, Join, TeamTailor, Recruitee, Comeet. [1] |
| **Remotive** | `remotive.com/api/remote-jobs` | None | Remote-only, global incl. EU | **Strict limit: >2 req/min blocked; they ask you query ~4×/day.** Cache aggressively. [2] |
| **Himalayas** | `himalayas.app/jobs/api` (browse) + `/jobs/api/search` | None | Remote-only, filter by country/seniority/type | **Requires attribution + link-back; forbids re-submitting jobs elsewhere.** [3] |
| **Adzuna** | `developer.adzuna.com` | App ID + key (free) | Strong EU country coverage | Free tier: 25/min, 250/day, 1000/week, 2500/month. "Personal research" + republishing listings explicitly allowed → fine for a portfolio, not for a commercial product. [4] |

**ATS public endpoints — the hidden gold for a *targeted* search.** Many companies host their jobs on an ATS with a public, no-auth JSON endpoint. You hit the endpoint for a *specific company* you want to work at:
- **Greenhouse:** `GET https://boards-api.greenhouse.io/v1/boards/{company}/jobs` [5]
- **Lever:** `GET https://api.lever.co/v0/postings/{company}?mode=json`
- **Ashby:** `GET https://api.ashbyhq.com/posting-api/job-board/{company}?includeCompensation=true` (returns JSON; no filtering/search server-side) [5]

This is a great story for the README: "I don't just pull from aggregators, I monitor the ATS boards of my ~30 target EU companies directly." That's exactly how a motivated candidate actually job-hunts, and it shows you understand the ecosystem.

**Normalization is the real engineering.** Every source returns a different shape. You need one canonical `Job` schema and a per-source adapter that maps into it. Dedup is non-trivial: the same role shows up on Arbeitnow *and* the company's Greenhouse board. Dedup on `(normalized_company, normalized_title, location)` + fuzzy match on description. This unglamorous layer is what separates a real project from a tutorial.

### A2. Scraping: legality and the anti-bot reality (2026)

You chose "hybrid: APIs first, scrape 1-2 boards to show the skill." Correct call. Here's the ground truth so you scope it defensibly:

- **The big boards are effectively unscrapeable at portfolio effort.** As of early 2026, ~87% of sites run at least one anti-bot system, and every Playwright instance ships with `navigator.webdriver = true` — the cheapest possible automation tell, which LinkedIn/Indeed check on the first request. [6] Don't build your project's spine on beating these; you'll spend all your time on cat-and-mouse and it'll break during a demo.
- **Legally, in the EU, honoring `robots.txt` is not optional-ish — it's load-bearing.** France's CNIL (the data-protection regulator) states that if you scrape without excluding sites that object via `robots.txt`/CAPTCHA, the processing "cannot fall within the reasonable expectations of data subjects," and your GDPR *legitimate-interest* legal basis collapses. [7] They also require data-minimization: define what you collect in advance, filter out everything else, delete irrelevant data you grabbed by accident. [8]
- **What this means for you concretely:** pick 1-2 *scraping-tolerant* boards (e.g. WeWorkRemotely's public RSS, or a small niche board whose `robots.txt` permits it), fetch a `robots.txt` and honor it programmatically, set a real `User-Agent` that identifies your project, rate-limit to human speed (~1 req / several seconds), cache, and never touch anything behind a login. Write this policy down *in the repo* (`SCRAPING_POLICY.md`). A hiring manager who sees you proactively reason about GDPR + robots.txt trusts you more than one who shows off a LinkedIn scraper — the latter reads as a liability in the EU.

**The framing that makes this a strength:** your scraper module is small, polite, well-documented, and legally defensible — and everything else runs on APIs. That's a *senior* judgement call, and you should say so explicitly in the README.

### A3. The AI core — how CV↔job matching actually works

This is the part that signals "AI engineer," so understand the tradeoffs rather than reaching for the obvious "dump both into GPT and ask for a score."

**Three approaches, and why the answer is a hybrid:**

1. **Embeddings / semantic similarity (retrieval).** Turn CV and each job into vectors; cosine similarity ranks relevance. Cheap, fast, scales to thousands of jobs. **But** it's a black box — it gives you a number with no *why*, and it can't be steered ("I care about seniority fit more than keyword overlap"). Research consensus: embedding-only methods "efficiently retrieve candidates at scale, [but] the lack of controllability and explainability limits their real-world adaptation." [9]
2. **LLM-as-judge (reasoning).** Give an LLM the CV + one job, ask for a structured verdict: score + matched skills + gaps + seniority fit + reasons. Explainable and steerable. **But** expensive and slow if you run it on every job in the feed.
3. **Hybrid: retrieve-then-rerank (the actual answer).** Use embeddings to cheaply shortlist the top ~N relevant jobs from the whole feed, then run the expensive LLM judge only on that shortlist. This is the dominant modern architecture. The Synapse paper (2026) separates "high-recall candidate generation from high-precision semantic reranking." [10] ConFit v3 shows the rerank stage measurably beats embedding-only: nDCG@10 **61.37 vs 52.33** on a recruiting benchmark. [11]

**For explainability (your differentiator), ground the score in evidence — this is RAG applied to matching.** Instead of the LLM emitting an opaque 78/100, it cites *which CV lines* support *which job requirements*. The Synapse system adds "a retrieval-augmented explanation layer that grounds recommendations in explicit evidence" rather than opaque scores. [10] JobMatchAI (2026) combines knowledge graphs + semantic search + explainable AI specifically to avoid keyword-only matching. [12] You don't need a knowledge graph, but the principle — **every score must come with its receipts** — is what you implement.

**Concrete design for your matcher:**
- Stage 1 (retrieve): embed CV + all jobs, cosine-rank, keep top N.
- Stage 2 (judge): for each of the N, LLM returns structured JSON: `overall_score` (0-100), `dimension_scores` (skills / seniority / domain / location-remote), `matched_requirements[]` (each with the CV evidence line), `gaps[]`, `one_line_verdict`.
- Force **structured output** (JSON schema / tool-use) so scores are parseable and you can't get prose slop. A zero-shot structured-prompt + embedding pipeline is a validated approach — one 2026 paper does exactly this with chain-of-thought structuring then embedding similarity, no fine-tuning needed. [13]

### A4. The cover-letter drafter — and the fabrication problem

Drafting is easy; *not lying* is the engineering. Left alone, an LLM will happily invent "5 years of Kubernetes" you don't have — which, in a real application you send, is catastrophic. Your job is to make fabrication structurally hard:

- **Constrain the model to CV-grounded facts only.** Feed it your CV as the sole source of truth for claims about you; instruct it to draft using *only* experience present there, and to leave a `[NEEDS INPUT: ...]` placeholder rather than invent.
- **Add a verification pass (this is the portfolio-worthy bit).** After drafting, run a second LLM call (or a claim-checker) that extracts every factual claim about you from the letter and checks each against the CV — flag anything unsupported. This is the same idea as RAG "faithfulness" scoring (fraction of output claims grounded in source). Ship it as a visible "Fabrication check: 0 unsupported claims" badge in the UI.
- Keep a human in the loop: the app drafts, *you* approve/edit before it's ever "sent." Never auto-apply.

### A5. Models & cost (2026, current)

Prices are per **million tokens (MTok)**, from Anthropic's official pricing page. [14][15]

| Model | Input | Output | Use it for |
|---|---|---|---|
| **Claude Haiku 4.5** | $1 | $5 | The match-scoring judge (high volume, many jobs). Batch API halves it to $0.50/$2.50. [15] |
| **Claude Sonnet 4.6** | $3 | $15 | Cover-letter drafting + the fabrication-check pass (quality matters, low volume). |
| **Claude Opus 4.8** | $5 | $25 | Only if you want top-tier drafting; batch → $2.50/$12.50. Probably overkill here. [14] |

**Embeddings:** start with OpenAI `text-embedding-3-small` — 1536-dim, ~$0.02/MTok, MTEB ~62.3, explicitly the recommended prototype/MVP choice. [16] (Anthropic doesn't ship a first-party embedding model, so this is the pragmatic pick; you can note that reasoning in the README.) Store vectors in **pgvector** (Postgres extension) so you don't add a separate vector DB — one datastore, less ops.

**Rough cost per application processed:** matching one job with Haiku on a CV (~2k in / ~500 out tokens) is a fraction of a cent; a Sonnet cover letter (~3k in / ~800 out) is roughly one to two cents. Dogfooding your whole search will cost **single-digit dollars total.** Put that number in the README — cost-awareness is an AI-engineering signal.

### A6. Evaluating the AI (the rarest, highest-signal piece)

Almost no portfolio job-tracker has evals. Adding them is the clearest "I'm an AI engineer, not a prompt-caller" move. What to build:

- **A golden set.** Hand-label 20-40 (CV, job) pairs with a "true" match verdict (strong / medium / weak). Your own real applications are perfect labels once you dogfood. Measure whether your scorer's ranking correlates with your judgement (rank correlation, or simple "does it put the jobs I actually applied to near the top").
- **LLM-as-judge for eval (not just for scoring).** Use a separate judge model with a rubric to grade your matcher's *explanations* for quality/consistency. Known best practices: use a chain-of-thought rubric (G-Eval style), watch for judge biases (position, verbosity, self-preference), and calibrate the judge against your human labels before trusting it. [17]
- **Faithfulness / hallucination metric for cover letters.** Track "% of letters with 0 unsupported claims" over time (RAGAS-style faithfulness = fraction of output claims grounded in the CV).
- **Regression tests.** Snapshot scores on the golden set; fail CI if a prompt change moves them beyond a threshold. This is the single most impressive thing in the repo for a hiring manager.

### A7. One legal flag worth knowing (not a blocker)

Under the **EU AI Act**, tools that "shortlist CVs, rank candidates, or score interviews" are **high-risk** AI systems with strict obligations. [18] Your app scores *jobs for yourself*, not *candidates for an employer*, so you're the data subject and it's personal use — you're outside the high-risk scope. But **mentioning in the README that you know this distinction** ("this tool scores opportunities for the job-seeker, not candidates for employers, so it falls outside EU AI Act high-risk hiring provisions") is a standout signal for EU employers. It shows you think about AI governance, which is a hot 2026 hiring theme.

### A8. What makes this project credible vs generic (positioning)

From the portfolio-hiring research: [19]
- **Ship a live, deployable demo, not just a repo.** Runnable/hosted projects get far more hiring-manager attention than static code. Deploy the frontend + a hosted API.
- **Lead with problems solved and impact, not clever code.** Hiring managers care about value delivered. So the README opens with the dogfood story and real numbers (jobs ingested, applications sent, interviews landed), not architecture diagrams.
- **Production signals beat model cleverness:** tests, CI, evals, error handling, deploy, observability, a real README. A "Jupyter notebook with `model.predict()`" reads as a toy; this should read as a small product.
- **The dogfood narrative is your moat.** "I built this and ran my own EU remote search through it" is a story generic clones can't copy.

---

## Sources

- [1] Arbeitnow Job Board API — https://www.arbeitnow.com/blog/job-board-api
- [2] Remotive API (rate limits) — https://github.com/remotive-com/remote-jobs-api
- [3] Himalayas API (attribution terms) — https://himalayas.app/api
- [4] Adzuna Developer (limits + permitted use) — https://developer.adzuna.com/overview
- [5] ATS public endpoints (Greenhouse/Lever/Ashby/…) — https://fantastic.jobs/article/ats-with-api
- [6] Playwright bot detection state 2026 — https://alterlab.io/blog/playwright-bot-detection-what-actually-works-in-2026
- [7][8] CNIL — legitimate interest & web scraping (GDPR) — https://www.cnil.fr/en/legal-basis-legitimate-interest-focus-sheet-measures-implement-case-data-collection-web-scraping
- [9][11] ConFit v3 (retrieve-then-rerank, nDCG gains) — https://arxiv.org/html/2605.09760
- [10] Synapse (two-phase retrieval + RAG explanation) — https://arxiv.org/pdf/2604.02539
- [12] JobMatchAI (KG + semantic + explainable) — https://arxiv.org/pdf/2603.14558
- [13] Zero-shot resume↔job matching (CoT + embeddings) — https://www.mdpi.com/2079-9292/14/24/4960
- [14][15] Claude pricing (official) — https://platform.claude.com/docs/en/about-claude/pricing
- [16] Embedding models compared — https://pecollective.com/tools/text-embedding-models-compared/
- [17] LLM-as-judge best practices — https://deepeval.com/guides/guides-llm-as-a-judge
- [18] EU AI Act & hiring (high-risk) — https://www.hiretruffle.com/blog/eu-ai-act-hiring
- [19] AI portfolio positioning — https://zenvanriel.com/ai-engineer-blog/100k-ai-engineering-portfolio-projects/ ; https://dev.to/klement_gunndu/5-ai-portfolio-projects-that-actually-get-you-hired-in-2026-5bpl

---

## Part B — Build Plan

### B0. Architecture at a glance

```
                    ┌─────────────────────────────────────────┐
                    │            React frontend (thin)          │
                    │  pipeline board · job detail · letter UI  │
                    └────────────────────┬──────────────────────┘
                                         │ REST (JSON)
                    ┌────────────────────┴──────────────────────┐
                    │              FastAPI (Python)              │
                    │  /jobs  /match  /letters  /applications    │
                    └───┬───────────┬──────────────┬─────────────┘
                        │           │              │
             ┌──────────┘   ┌───────┘        ┌─────┘
             ▼              ▼                ▼
    ┌────────────────┐ ┌──────────────┐ ┌──────────────────┐
    │ Ingest layer   │ │ AI core      │ │ Postgres+pgvector│
    │ source adapters│ │ retrieve →   │ │ jobs, cvs,       │
    │ + normalizer   │ │ judge → draft│ │ matches, apps,   │
    │ + polite scraper│ │ + eval harness│ │ embeddings      │
    └────────────────┘ └──────────────┘ └──────────────────┘
```

Single Postgres (with pgvector) as the only datastore. Background jobs (ingest, embed, match) via a simple scheduler (APScheduler or a cron-triggered endpoint) — no Celery/Redis unless you later need it.

### B1. Data model (core tables)

- `cv` — your CV, parsed into structured sections (skills, experience[], education) + raw text + embedding.
- `job` — canonical normalized job (source, source_id, title, company, location, is_remote, description, url, posted_at, ingested_at) + embedding. Unique on `(source, source_id)`; dedup key on `(company_norm, title_norm, location_norm)`.
- `match` — (cv_id, job_id, overall_score, dimension_scores JSON, matched_requirements JSON, gaps JSON, verdict, model, created_at).
- `cover_letter` — (job_id, draft_text, fabrication_check JSON, status draft/approved/sent, versions).
- `application` — (job_id, status enum: saved→applied→interview→offer→rejected, notes, timestamps) — the tracker/pipeline.

### B2. Phased delivery

Each phase ends with something that works and is committed. Don't build the whole thing then wire it up.

**Phase 0 — Skeleton & rails (do this first, it pays back all project long)**
- Repo, `README` stub, FastAPI app, Postgres+pgvector via Docker Compose, one health endpoint, pytest running in CI (GitHub Actions), `.env`/secrets handling, `ruff` + `black`.
- Deliverable: `docker compose up` gives a running API + DB; CI is green.

**Phase 1 — Ingest & normalize (the unglamorous backbone)**
- `Job` schema + a `Source` adapter interface. Implement adapters for **Arbeitnow** (EU backbone) + **Remotive** (respect the ~4×/day limit; cache) + **one ATS** (Greenhouse) for a target company.
- Normalizer + dedup. Scheduler pulls periodically into Postgres.
- Deliverable: DB fills with deduped EU/remote jobs from 3 sources; a `/jobs` endpoint lists them.

**Phase 2 — CV ingestion & the retrieve stage**
- Upload/parse your CV (PDF → structured + raw text). Embed CV and all jobs (`text-embedding-3-small`), store vectors in pgvector.
- `/match/shortlist` — cosine-rank jobs against the CV, return top N.
- Deliverable: given your CV, the app ranks the whole feed by semantic relevance.

**Phase 3 — The LLM judge (the AI centerpiece)**
- Structured-output match scorer (Claude Haiku 4.5) over the shortlist: overall + dimension scores + matched requirements *with CV evidence* + gaps + verdict. Enforce JSON schema.
- Store in `match`. `/match/{job_id}` returns the explainable verdict.
- Deliverable: every shortlisted job gets an explainable 0-100 with receipts.

**Phase 4 — Cover-letter drafter + fabrication guard**
- Drafter (Claude Sonnet 4.6) grounded strictly in the CV, using match gaps to address them honestly, `[NEEDS INPUT]` placeholders instead of invention.
- Fabrication-check pass: extract claims about you, verify each against CV, flag unsupported. Surface a "0 unsupported claims" result.
- Deliverable: per-job draft letter + visible fabrication check; you approve/edit before use.

**Phase 5 — Tracker UI (your MERN comfort zone)**
- React: pipeline board (saved→applied→interview→offer→rejected), job detail with the match breakdown, letter editor with the fabrication badge, filters (remote, country, score).
- Deliverable: you can actually run your search from the UI.

**Phase 6 — Evals & rigor (the standout)**
- Golden set (label 20-40 real pairs from your own search). Ranking-correlation eval for the scorer. LLM-as-judge (G-Eval rubric) for explanation quality. Faithfulness metric for letters. Regression test in CI that fails on score drift.
- Deliverable: `make eval` prints a scorecard; CI guards it.

**Phase 7 — Polish, deploy, dogfood story**
- Deploy (frontend on Vercel/Netlify, API+DB on Railway/Fly/Render). Observability (structured logs, LLM call tracing, cost counter). Error handling on every source/LLM call. `SCRAPING_POLICY.md`, architecture doc, and a README that opens with the **dogfood metrics** (jobs ingested, applications sent, interviews) and the EU AI Act note.
- Deliverable: live demo link + a README that tells the story.

### B3. Scope discipline (what to say no to)
- No LinkedIn/Indeed scraping. State why in the README (turns a limitation into a judgement signal).
- No auto-apply. Human-in-the-loop is a feature, not a gap.
- No knowledge graph, no fine-tuning, no multi-tenant auth. Single user (you) is fine and honest.
- One datastore (Postgres+pgvector). No Celery/Redis until proven necessary.

### B4. The "spotless" checklist (what a EU hiring manager will look for)
- [ ] Live demo link that works.
- [ ] README leads with impact + dogfood numbers, not architecture.
- [ ] Evals with a golden set + regression test in CI.
- [ ] Structured outputs + a real anti-hallucination guard (not just "trust the model").
- [ ] Cost awareness stated (per-application cost, model choice rationale).
- [ ] `SCRAPING_POLICY.md` + robots.txt/GDPR reasoning.
- [ ] EU AI Act positioning note.
- [ ] Tests + CI green, typed Python, clean commits.
- [ ] Clear "why hybrid retrieve-then-rerank" writeup — shows you understand the tradeoff, not just the tutorial.
