# Concepts Primer — from zero

The build plan assumes you already know these. This file doesn't. Read it top to bottom once; each concept builds on the last. Every section has: **the idea in plain words**, **a tiny concrete example**, and **where it shows up in this project**.

You don't need to master these before starting — you'll learn them by building the phase that uses them. This is the map so nothing in the plan is a black box.

---

## 1. Embeddings & "vectorising"

**The idea.** A computer can't compare the *meaning* of two texts directly. An **embedding model** is a neural network that reads a chunk of text and outputs a long list of numbers (a **vector**, e.g. 1536 numbers) that represents its meaning. "Vectorising" (aka "embedding") just means running text through that model to get its vector. The key property: **texts with similar meaning get similar vectors**, even if they share no words.

**Tiny example.**
- "Senior Python backend engineer" → `[0.02, -0.11, 0.34, ... ]` (1536 numbers)
- "Experienced Django developer" → `[0.03, -0.09, 0.31, ... ]` (very close numbers, because similar meaning)
- "Chocolate cake recipe" → `[-0.4, 0.7, -0.2, ... ]` (very different numbers)

You never read these numbers yourself. You just compare them (next section).

**In this project.** You embed your CV once, and embed every job posting. Now "how relevant is this job to my CV?" becomes "how close are these two vectors?" — a fast math operation you can run over thousands of jobs cheaply.

**Model you'll use:** OpenAI `text-embedding-3-small`. You send it text over an API, it returns the vector.

---

## 2. Cosine similarity (comparing vectors)

**The idea.** Once two texts are vectors, you measure how "close" they point using **cosine similarity** — a single number from -1 to 1 (in practice ~0 to 1 for text). 1 = same direction (very similar meaning), 0 = unrelated. It's just geometry; the math is one line and the library does it for you.

**Tiny example.** cosine(CV_vector, job_vector) = 0.83 → strong semantic overlap. = 0.21 → probably irrelevant.

**In this project.** This is your **cheap first-pass ranking**. Score every job against your CV by cosine similarity, sort descending, take the top N. No LLM, no cost per job beyond the one-time embedding — that's why it scales.

---

## 3. Vector database & pgvector

**The idea.** If you have 5,000 job vectors and want "the 20 closest to my CV vector," you need somewhere to *store* vectors and *search* them by similarity quickly. That's a **vector database**. You could use a dedicated one (Pinecone, Weaviate, Qdrant), but the simplest option is **pgvector**: an extension for PostgreSQL (a normal SQL database) that adds a `vector` column type and similarity search. So your ordinary data (jobs, applications, notes) *and* your vectors live in **one database**.

**Tiny example.** In SQL with pgvector:
```sql
-- store
INSERT INTO job (title, embedding) VALUES ('Backend Engineer', '[0.02, -0.11, ...]');
-- search: 20 jobs most similar to my CV vector
SELECT title FROM job ORDER BY embedding <=> :cv_vector LIMIT 20;
```
That `<=>` operator is "distance between vectors." pgvector makes it fast even over thousands of rows.

**In this project.** One Postgres+pgvector database is your only datastore. Chosen deliberately: fewer moving parts than running a separate vector DB, and it's a very employable, "I made a sensible ops tradeoff" story.

---

## 4. LLM-as-judge

**The idea.** Instead of using an LLM to *write* something, you use it to *evaluate* something and return a structured verdict. You give it clear instructions + a rubric, and it outputs a score and reasons. It "acts as a judge."

**Tiny example.** Prompt: *"Here is a CV and a job. Score the match 0-100. Return which requirements are met (quote the CV line that proves it), which are gaps, and a one-line verdict. Respond as JSON."* → the model returns a structured judgement instead of prose.

**In this project.** After cosine similarity shortlists the top ~20 jobs, an LLM judge (Claude Haiku 4.5) scores *each one* with explainable reasons. This is the expensive-but-smart second pass — you only run it on the shortlist, not the whole feed.

**Two uses, don't confuse them:** here the LLM judges *job matches* (a product feature). Later, in evals (section 8), a *different* LLM judges *your system's output quality* (a testing tool). Same technique, different purpose.

---

## 5. Retrieve-then-rerank (the two-stage pattern)

**The idea.** Combine the two things above. **Retrieve** = cheap, high-recall first pass (embeddings/cosine) that narrows thousands → a shortlist. **Rerank** = expensive, high-precision second pass (LLM judge) that carefully orders/scores the shortlist. You get scale *and* quality: you never pay for the expensive model on obviously-irrelevant jobs.

**Analogy.** A recruiter first keyword-skims 500 CVs down to 20 (fast, rough), then actually reads those 20 carefully (slow, accurate). Retrieve = the skim; rerank = the careful read.

**In this project.** This is your core AI architecture and the thing to explain in your README. "Embeddings retrieve, an LLM reranks with explanations" is the sentence that signals you understand the tradeoff instead of just dumping everything into one model.

---

## 6. RAG (Retrieval-Augmented Generation)

**The idea.** LLMs make things up when they don't know an answer. **RAG** fixes this by *retrieving* relevant real information first and *feeding it into* the prompt, so the model generates an answer **grounded in facts you supplied** instead of its imagination. "Retrieval-augmented" = the generation is augmented with retrieved facts.

**Tiny example.** Naive: "Write my cover letter." → model invents experience. RAG: "Here are the exact skills and projects from my CV: [retrieved CV facts]. Write a cover letter using ONLY these." → model is anchored to truth.

**In this project.** Two places:
1. **Explainable match scores** — the judge grounds each score in retrieved CV evidence ("you match 'Python' because your CV line X says so"), not a vibe.
2. **Cover-letter drafting** — the letter is generated from retrieved CV facts, which is what lets you then *check* it for fabrication (section 7).

RAG is repeatedly cited as the single most in-demand AI-engineering skill in 2026, so understanding it here matters beyond this project.

---

## 7. Structured output & the fabrication guard

**Structured output.** Normally an LLM returns free-form text. You can instead force it to return **valid JSON matching a schema you define** (via "tool use" / "JSON mode"). This makes outputs parseable and reliable — no fragile text-parsing.

**Tiny example.** You define a schema `{ overall_score: int, gaps: string[], verdict: string }` and the model must fill exactly that. Your code gets `result.overall_score` safely.

**Fabrication guard.** A second, verification LLM pass: take the drafted cover letter, extract every factual claim about *you*, and check each against your CV. Anything not supported gets flagged. This is RAG "faithfulness" applied — measuring what fraction of the output is actually grounded in the source.

**In this project.** Match scores use structured output so they're always parseable. Cover letters get the fabrication guard so you never send a letter claiming experience you don't have. This guard is one of your standout portfolio pieces.

---

## 8. Evals (evaluating your AI)

**The idea.** "The demo looked good" is not evidence your AI works. **Evals** are systematic tests of AI output quality. Because AI output isn't a simple pass/fail like normal code, you need special techniques:
- **Golden set** — a hand-labelled set of examples with known-correct answers. You run your system on them and measure how close it gets.
- **Regression test** — re-run the golden set whenever you change a prompt; fail the build if quality dropped. Stops you from "fixing" one thing and silently breaking another.
- **LLM-as-judge for grading** — use an LLM with a rubric to score your system's outputs at scale (calibrated against your human labels first, because judges have biases).

**Tiny example.** You label 30 real (CV, job) pairs as strong/medium/weak match. Eval checks: does your scorer rank the "strong" ones above the "weak" ones? If a prompt tweak drops that from 90% to 70%, CI goes red.

**In this project.** This is the rarest, highest-signal piece — almost no portfolio job-tracker has evals. Your own real applications become the golden set once you dogfood. It's the clearest proof you're an AI *engineer*, not a prompt-caller.

---

## 9. How it all connects (one pass through the pipeline)

1. **Ingest**: pull jobs from APIs/ATS → normalize → store in Postgres.
2. **Vectorise**: embed your CV + each job (section 1) → store vectors in pgvector (section 3).
3. **Retrieve**: cosine-rank all jobs vs your CV (section 2), keep top ~20 (section 5, stage 1).
4. **Rerank/judge**: LLM scores each shortlisted job with grounded reasons (sections 4, 5-stage-2, 6).
5. **Draft**: RAG-generate a cover letter from CV facts (section 6), then fabrication-check it (section 7).
6. **Track**: you approve, apply, and move it through the pipeline board.
7. **Evaluate**: the golden set + regression tests keep the AI honest as you iterate (section 8).

---

## Suggested learning order (paired with build phases)

You learn each concept right before the phase that needs it — no upfront theory marathon:

| Before building… | Learn (this doc) | Also skim |
|---|---|---|
| Phase 2 (retrieve) | §1 embeddings, §2 cosine, §3 pgvector | OpenAI embeddings guide; pgvector README |
| Phase 3 (judge) | §4 LLM-as-judge, §5 rerank, §7 structured output | Anthropic tool-use / structured-output docs |
| Phase 4 (letters) | §6 RAG, §7 fabrication guard | Anthropic prompting guide |
| Phase 6 (evals) | §8 evals | DeepEval or RAGAS "getting started" |

Rule of thumb: read the section, build the phase, *then* the concept is actually yours. Reading all nine now just gives you the vocabulary so the plan stops looking like jargon.
