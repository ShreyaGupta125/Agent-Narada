# 3. The language model

[← System architecture](02-architecture.md) · [Contents](README.md) · [Next: Document ingestion and retrieval →](04-ingestion-and-retrieval.md)

## 3.1 What the model does, and what it does not

A **large language model (LLM)** is a program trained on a great deal of
text. Given some text, it predicts the next word piece ("token"), again and
again, and so writes sentences.

In Agent Narada the model has **one narrow job**: read up to four short
passages chosen by Django, and write a short answer to the question from
them, in a fixed JSON shape. It also helps in two small cases: rewriting a
follow-up ("and for how many days?") into a full question, and deciding
"university" or "other" for an unclear question.

The model does **not**:

- store or learn the documents (no training, no fine-tuning);
- decide who may read what;
- choose the sources;
- have the last word: Django checks every answer (chapter 5).

Because the documents are given to the model fresh with every question, a
new or changed document is used **immediately** after upload and approval.
Nothing has to be retrained.

## 3.2 The model: Qwen2.5-1.5B-Instruct

| Property | Value |
|----------|-------|
| Name | Qwen2.5-1.5B-Instruct |
| Made by | The Qwen team at Alibaba Cloud (released September 2024) |
| Downloaded from | Hugging Face (official Qwen GGUF release) |
| Size | about 1.5 billion parameters |
| "Instruct" | Tuned to follow instructions and hold a conversation (not just continue text) |
| Licence | Apache 2.0 (free to use, including in this project) |
| Context it can read | up to 32,768 tokens (Agent Narada uses 4,096, enough for the rules, 4 passages and a question) |
| File used | `models/qwen2.5-1.5b-instruct-q4_k_m.gguf` |
| File size | 1.12 GB (1,117,320,736 bytes) |

### Why this model

The model had to satisfy the project's requirements: **local**, **open**,
**from Hugging Face**, **small enough for a student laptop**, and good at
**following strict instructions**. These were the options considered (only
the chosen model was built into the system and measured; the others were
judged from their size, licence and the project's needs):

| Model (4-bit file size, approx.) | Considered | Decision |
|----------------------------------|------------|----------|
| Qwen2.5-0.5B-Instruct (~0.4 GB) | Fastest, smallest | Rejected: at this size instruction following and careful reading of tables become unreliable, and Agent Narada needs both |
| **Qwen2.5-1.5B-Instruct (~1.1 GB)** | Good balance | **Chosen** |
| Qwen2.5-3B-Instruct (~2 GB) | Better language, but twice the size, so slower and heavier; released under the more restrictive Qwen Research License instead of Apache 2.0 | Rejected: "optimised power, not over-power" — the extra quality is not needed because Django checks the answers anyway |
| 7B / 8B models (~4.5–5 GB) | Stronger still | Rejected: barely fits a 6 GB laptop GPU together with its working memory; much slower |
| Cloud AI (ChatGPT, Gemini …) | Strongest | Rejected: sends university documents and students' questions to an outside company; needs internet and payment; not a local model |

The reasons for **Qwen2.5-1.5B-Instruct** in particular:

1. **It fits the job.** The model never has to *know* anything about UPES;
   it only has to read four short passages and copy or rephrase the right
   sentence. A 1.5B model does this well. Knowledge-heavy tasks need large
   models; reading-and-copying tasks do not.
2. **Good instruction following and JSON output for its size.** The Qwen2.5
   family was trained specifically to follow system instructions and to
   produce structured output such as JSON, which Agent Narada relies on
   (section 3.5).
3. **Fast on ordinary hardware.** About 2 seconds per answer on the
   development laptop's RTX 4050 (section 3.7). It would also run, slower,
   on a computer without a graphics card.
4. **Small memory footprint.** The 4-bit file is 1.1 GB, leaving most of
   the 6 GB GPU and 16 GB RAM free.
5. **Open licence (Apache 2.0)** and an official release on Hugging Face in
   the GGUF format that llama.cpp reads directly.
6. **Mistakes are caught.** A small model makes more mistakes than a large
   one. Agent Narada was designed for that: Django checks every number,
   date, name and word of the answer against the passages, and replaces a
   doubtful answer by the "couldn't find" reply (chapter 5). The tests show
   0 wrong answers in the reviewed question sets (chapter 9).

## 3.3 Quantisation: why a 4-bit file (Q4_K_M)

A model is a very large list of numbers ("weights"). Stored at full
precision (16 bits each), Qwen2.5-1.5B takes about 3.1 GB. **Quantisation**
stores each weight with fewer bits:

| Format | Bits per weight | Approx. file size | Quality |
|--------|-----------------|-------------------|---------|
| F16 (original) | 16 | ~3.1 GB | reference |
| Q8_0 | 8 | ~1.6–1.9 GB | almost identical |
| **Q4_K_M** (used) | 4 for most weights, more for the most sensitive ones (5.8 on average in this file) | **1.1 GB** (measured) | very close to the original; the usual recommended balance |
| Q2_K | ~2–3 | ~0.7 GB | noticeably worse |

**Q4_K_M** ("4-bit, k-quant, medium") keeps the most important parts of the
model at higher precision and the rest at 4 bits. It is the standard
recommendation for the best quality per gigabyte, and it makes the model
about 3× smaller and faster to load and run.

**GGUF** is the file format of llama.cpp: one file holding the weights, the
tokenizer (how text is cut into tokens) and the chat template (how a
conversation is laid out for this model).

## 3.4 Why llama.cpp and llama-server

`llama-server.exe` is part of **llama.cpp**, an open-source (MIT licence)
program written in C/C++ that runs GGUF models. Agent Narada uses build
11588, compiled for NVIDIA CUDA 12.4.

| Need | How llama-server meets it |
|------|---------------------------|
| No heavy Python AI libraries | A single program; Django talks to it over HTTP with Python's own `urllib`. (The alternative, PyTorch + Transformers, is several GB of packages.) |
| Use the GPU | `-ngl 99` puts every layer of the model on the graphics card |
| A standard interface | `/v1/chat/completions`, the same request format as many online AI services, so the code is simple and the model could be swapped |
| Forced JSON replies | `response_format` with a JSON Schema: llama-server only lets the model write tokens that keep the reply valid JSON of that shape ("constrained decoding") |
| Security | `--host 127.0.0.1` (this computer only) and `--api-key` (requests without the key are refused) |
| No extra service | Ollama, an alternative, is a background service that downloads and manages models itself; llama-server runs only while Agent Narada runs and uses the file we chose |

## 3.5 How Django calls the model

`chat/llm.py` sends a request like this (shortened):

```json
POST http://127.0.0.1:8080/v1/chat/completions
Authorization: Bearer <secret key of this run>

{
  "messages": [
    {"role": "system", "content": "You are Agent Narada ... (the rules)"},
    {"role": "user",   "content": "Passages:\n\n[1] Attendance Notice\n...\n\nQuestion: ..."}
  ],
  "temperature": 0.0,
  "max_tokens": 600,
  "cache_prompt": false,
  "response_format": {"type": "json_schema", "json_schema": {"name": "reply", "schema": { ... }}}
}
```

| Setting | Value | Why |
|---------|-------|-----|
| `temperature` | 0.0 | The model always picks its most likely next token: **the same question gets the same answer** (requirement N4), and no "creative" wording |
| `max_tokens` | 600 | An upper limit on the reply's length; answers are short |
| `cache_prompt` | false | llama-server can reuse work from the previous request. That changes the arithmetic slightly, so answers could depend on what was asked before. Switched off: answers stay repeatable, at the cost of a fraction of a second |
| `response_format` | a JSON Schema | The reply is **always** valid JSON with the fields `answer`, `evidence`, `status`, `missing` (chapter 5.4) |
| context (`-c 4096`) | 4,096 tokens | Rules (222 words, about 300 tokens) + 4 passages of ~120 words + question + reply fit easily |
| timeout | 60 seconds | If the model does not answer, the user gets "Agent Narada's language model is not running right now. Please try again in a moment." (HTTP 503), and the technical reason is printed in the server's window |

The JSON shape forced for an answer:

```json
{
  "answer":   "Every student must attend at least 75% of the classes in each course ...",
  "evidence": [{"passage": 1, "quote": "Every student must attend at least 75% of the classes ..."}],
  "status":   "answered",
  "missing":  ""
}
```

## 3.6 Keeping the model private

- `main.py` creates a **new random key** (`secrets.token_urlsafe(32)`) every
  time it starts, gives it to llama-server (`--api-key`) and to Django
  (environment variable `NARADA_LLM_API_KEY`). The key is never written to
  disk. Another program or a web page on the same computer cannot use the
  model without it.
- Both listen on `127.0.0.1` only. No question, document or answer leaves
  the computer.
- Django ignores any proxy setting for this connection (`ProxyHandler({})`),
  so a proxy configured for the internet can never receive the requests.
- The model's prompt says that passages and questions are *information,
  not instructions* (protection against "prompt injection", chapter 6.6).

## 3.7 Measured speed

Measured on the development laptop (Intel Core i7-13700HX, 16 GB RAM,
NVIDIA GeForce RTX 4050 Laptop GPU with 6 GB), from llama-server's own log:

| Measure | Value |
|---------|-------|
| Loading the model at start-up | about 1 second |
| Reading the prompt (rules + passages + question; ~530 tokens in the logged example) | about 0.4 seconds (~1,300 tokens per second) |
| Writing the reply (~100 tokens) | about 1.6 seconds (~60 tokens per second) |
| **Total per answer** | **about 2 seconds** |
| Small talk, off-topic refusal, "couldn't find" when no passage matches | instant (the model is not asked) |

## 3.8 Limits of a small model, and how they are handled

| Limit | Seen in tests | How Agent Narada handles it |
|-------|---------------|-----------------------------|
| Reads the neighbouring row of a table | "Business Law exam" answered with the next row's date | Row check: each fact must be in a sentence about the question's own words (chapter 5.5) |
| Mixes up two directory entries | "Who teaches DBMS?" answered with the person above | Name check: a name must be in the paragraph about the question's subject |
| Says "Yes"/"No" wrongly | "Yes, students with low attendance cannot take the exam" | Leading yes/no is removed; the rule itself is shown |
| Answers from its own general knowledge | possible for any model | Facts and 75% of the words must be in the passages |
| Leaves the quote empty or names the wrong passage | frequent | Quotes are not required; Django finds the supporting passages itself |
| Fails to rewrite a follow-up well | "and Discrete Mathematics?" | The result is searched and checked like any question; the reply is then a safe "couldn't find" |

The principle: **a wrong answer is worse than no answer.** When in doubt,
Agent Narada says it could not find sufficient information.
