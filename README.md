# Natural Language → Structured Action Agent

A small backend service that takes plain-English facility monitoring
instructions and turns them into validated, executable actions. Built
for the Gen AI Engineering take-home assignment.

The core idea: the LLM is only trusted to *understand language*. It is
never trusted to decide what's safe or valid — that responsibility
belongs entirely to this codebase (Pydantic schemas + a validator module
checked against a real device registry).

---

## Setup & Run

### 1. Clone and install

```bash
git clone <your-repo-url>
cd nl-action-agent
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

By default `MOCK_MODE=true`, so the app runs and is fully testable
without any API key.

To use a real Gemini call, edit `.env`:
GEMINI_API_KEY=your_real_key
MOCK_MODE=false
### 3. Run the server

```bash
uvicorn app.main:app --reload
```

Server runs at `http://localhost:8000`. Interactive API docs are at
`http://localhost:8000/docs`.

### 4. Try it

```bash
curl -X POST http://localhost:8000/command \
  -H "Content-Type: application/json" \
  -d '{"text": "Alert me if warehouse-3 temperature stays above 40°C for more than 10 minutes"}'

curl http://localhost:8000/rules
```

### 5. Run tests

```bash
pytest -v
```

All tests run against `MOCK_MODE`, so they're deterministic and don't
touch the network.

---

## LLM Provider

This project uses **Google's Gemini API** (`gemini-2.5-flash`) for the
natural-language parsing step.

Reasons for this choice:

- **Free tier available** — makes the assignment easy to run and test
  without paid credits.
- **Native JSON mode** — Gemini supports
  `response_mime_type: "application/json"` in its generation config,
  which constrains output at the API level instead of relying purely on
  prompt instructions like "output only JSON."
- **Fast/cheap model tier** — `gemini-2.5-flash` is more than capable
  for structured extraction; a larger model isn't needed here.

The LLM call is fully isolated in `app/llm_client.py`. Nothing in
`main.py`, `models.py`, or `validator.py` knows or cares which provider
sits behind `parse_command()`. Swapping providers means rewriting one
function (`_real_parse`) — the rest of the pipeline is provider-agnostic
by design.

### Mock mode

`MOCK_MODE=true` (the default) returns canned responses for the 5
required test phrases instead of calling the live API. This keeps the
app runnable and testable at zero cost, and keeps tests deterministic.
Set `MOCK_MODE=false` with a real `GEMINI_API_KEY` to exercise the
actual model.

---

## Architecture
text
│
▼
llm_client.parse_command() ── LLM guesses a structured action (raw dict)
│
▼
models.parse_action() ── Does the guess fit a known Action shape?
│ (Pydantic validation — catches malformed
│ types, missing fields, wrong enums)
▼
validator.validate_action() ── Does it make sense given reality?
│ (device exists? metric valid for that
│ device? duration positive? etc.)
▼
store.add_rule() / get_rules() ── Only runs if the above two passed
│
▼
JSON response ── { understood, status, reason, result }
Three deliberately separate layers:

1. **`llm_client.py`** — language understanding only. Produces a guess,
   never touches the registry, never decides validity.
2. **`models.py` + `validator.py`** — this codebase's actual authority.
   Pydantic enforces *shape*; `validator.py` enforces *business rules*
   (real devices, real metrics, sane values).
3. **`store.py`** — execution. Only reached after both validation steps
   pass.

Route handlers in `main.py` are intentionally thin — they just call
these modules in order and shape the response. No business logic lives
in the route itself.

### Response shape

Every call to `POST /command` returns:

```json
{
  "understood": { "...the parsed action, or null..." },
  "status": "EXECUTED | REJECTED | UNSUPPORTED",
  "reason": "human-readable explanation",
  "result": "whatever was created/queried, or null"
}
```

- `EXECUTED` — action was valid and something ran (rule created, status
  queried, rules listed).
- `REJECTED` — action was understood but failed validation (bad device,
  bad metric, bad values).
- `UNSUPPORTED` — the LLM itself couldn't map the instruction to a
  known action, or explicitly flagged it as out of scope.

---

## Design decision: the ambiguous case (#3)

**Input:** *"notify security if the front-gate camera goes offline"*

This doesn't map cleanly onto `CREATE_ALERT_RULE` as written — there's
no numeric threshold or obvious "stays above X for Y minutes" concept
for a camera going offline. Two reasonable options existed:

1. Reject it as `UNSUPPORTED` since it doesn't fit the numeric alert
   model.
2. Interpret it as a legitimate alert with a best-effort mapping.

**I chose option 2.** Reasoning:

- An operator saying "notify me if X goes offline" clearly *does* have
  actionable intent — it's a real, common monitoring request. Rejecting
  it outright would be technically safe but practically unhelpful; a
  real product would want to support this.
- "Goes offline" is naturally a **boolean/state** condition rather than
  a **numeric threshold** one. I mapped it onto the existing schema by
  treating connectivity as a metric with a binary value: `metric:
  "connectivity"`, `condition: "EQUALS"`, `threshold: 0`. This reuses
  the existing schema instead of inventing a new action type, keeping
  the system simpler.
- Since no duration was specified, I default `duration_minutes` to a
  conservative `1` rather than guessing something larger. This is
  documented in the prompt itself so the behavior is explicit and
  traceable, not a silent LLM guess.
- Critically, **this mapping still goes through the same validator as
  everything else.** If `front-gate-camera` didn't have a `connectivity`
  metric in the registry, this would be rejected just like any other
  invalid metric reference. The "creative interpretation" only happens
  in the LLM layer; the safety check is unaffected.

**Trade-off I'm accepting:** this means the LLM is making a modeling
decision (mapping "offline" → a specific metric/condition/threshold)
that the user didn't literally specify. A stricter design would refuse
to guess and return `UNSUPPORTED` instead, asking the user to be more
specific. I think producing a sensible default with clear documentation
is the better user experience for this kind of assistant, but it's a
defensible call either way — which is presumably why the assignment
calls this out as the interesting case.

---

## Known limitations

- **In-memory storage only.** Rules disappear on server restart. Fine
  per the assignment's scope, not fine for production.
- **No live telemetry.** `QUERY_STATUS` returns a stubbed value since
  there's no real sensor backend — out of scope per the assignment.
- **Small mock device registry.** Only 6 devices are defined. Real
  metric names in the wild would need a much larger, probably
  dynamically loaded registry.
- **No retry logic on LLM calls.** A transient API failure or timeout
  currently isn't retried — it would surface as an `UNSUPPORTED` result
  via the JSON-parse failure path, but a flaky network call isn't
  distinguished from a genuinely bad model response.
- **No conversation memory.** Each `/command` call is stateless; the
  system can't handle follow-ups like "actually make that 15 minutes."
- **No auth.** Anyone who can reach the service can create rules. Out
  of scope per the assignment, but would be a hard requirement for
  anything real.
- **Prompt-injection protection is basic.** See the bonus section below
  — it's a keyword/pattern guard, not a comprehensive defense.

---

## Bonus: Prompt-injection protection

`llm_client.py` includes a lightweight keyword/pattern guard that checks
incoming text for phrases commonly used to try to override system
behavior (e.g. "ignore previous instructions", "delete all rules")
before sending it to the LLM. Matches are rejected as `UNSUPPORTED`
without ever reaching the model.

This is a basic first line of defense, not a complete solution — a
sufficiently creative injection could still get past keyword matching.
The stronger guarantee in this system is architectural: even if an
injection did get an LLM to hallucinate a malicious-looking action, it
still has to pass `validator.py`'s checks against the real device
registry to do anything. The LLM's output is never trusted or executed
directly, regardless of what it was tricked into producing.

---

## What I'd do with more time

- Add a confidence score or ask-for-clarification flow instead of
  always guessing on ambiguous input (e.g. respond with "did you mean
  X or Y?" rather than committing to one interpretation).
- Persist rules to a real datastore (SQLite would be a reasonable first
  step) instead of in-memory.
- Add retry-with-backoff around the Gemini call, and separate "LLM
  infra failure" from "LLM gave nonsense" in the response so callers
  can distinguish a retryable error from a genuine rejection.
- Expand the device registry and pull it from a more realistic source
  (e.g. a devices API) rather than a static JSON file.
- Implement the bonus `/rules/:id` DELETE/UPDATE endpoint via the same
  NL interface.
- Add basic rate limiting / cost tracking around LLM calls (see note
  below).

---

## Note on LLM cost at scale

At scale, the main cost lever is call volume × tokens per call. A few
practical levers I'd reach for before anything fancy:

- **Cache identical/near-identical requests** — operations staff likely
  send similar phrasings repeatedly (e.g. the same alert rule template
  across many devices); a normalized-text cache would cut real API
  calls significantly.
- **Keep the system prompt lean and stable** — it's sent on every call;
  trimming it and keeping few-shot examples minimal directly reduces
  input tokens.
- **Use the cheapest model tier that meets accuracy needs** — this is
  exactly the kind of task where a small, fast model outperforms a
  large one on cost without meaningfully hurting quality.
- **Set a hard token/response cap** (`max_tokens` equivalent) so a
  malformed or runaway generation can't balloon cost on a single
  request.
- **Track cost per request type** so you can see which instruction
  patterns are expensive and worth hand-writing a rules-based fast path
  for instead of always hitting the LLM.

---

## Time spent

Roughly 5–6 hours across two sessions: schema + registry + validator
first, then the LLM integration and prompt iteration, then tests, then
this README.
