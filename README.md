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
python -m uvicorn app.main:app --reload
```

(Using `python -m uvicorn` rather than a bare `uvicorn` avoids picking
up a different Python install if one happens to be earlier on your
PATH — see "Known limitations" below.)

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

Tests **force** `MOCK_MODE=true` internally (see `tests/conftest.py`),
regardless of what your local `.env` is set to. This keeps the suite
deterministic and fast even if you've switched your own `.env` to live
mode for manual testing. See "A bug I found and fixed" below for why
this matters.

---

## LLM Provider

This project uses **Google's Gemini API** (`gemini-flash-latest`) for
the natural-language parsing step.

Reasons for this choice:

- **Free tier available** — makes the assignment easy to run and test
  without paid credits.
- **Native JSON mode** — Gemini supports
  `response_mime_type: "application/json"` in its generation config,
  which constrains output at the API level instead of relying purely on
  prompt instructions like "output only JSON."
- **Fast/cheap model tier, always current** — `gemini-flash-latest` is
  an alias that tracks Google's current recommended fast model, rather
  than a pinned version string that can be deprecated later (an earlier
  version of this project used `gemini-2.5-flash` directly, which
  stopped being available to new users mid-development — see below).

The LLM call is fully isolated in `app/llm_client.py`. Nothing in
`main.py`, `models.py`, or `validator.py` knows or cares which provider
sits behind `parse_command()`. Swapping providers means rewriting one
function (`_real_parse`) — the rest of the pipeline is provider-agnostic
by design.

### Mock mode

`MOCK_MODE=true` (the default) returns canned responses for the 5
required test phrases instead of calling the live API. This keeps the
app runnable and testable at zero cost, and keeps automated tests
deterministic. Set `MOCK_MODE=false` with a real `GEMINI_API_KEY` to
exercise the actual model.

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

## Live Gemini experiment (beyond the 5 required phrases)

To confirm the LLM integration isn't just working against the 5
hardcoded canned examples, I ran a few genuinely novel phrases against
the real Gemini API (`MOCK_MODE=false`), not seen anywhere in the
prompt's few-shot examples or the mock response set:

**Input:** *"let me know if the pump station pressure drops below 20"*

```json
{
  "understood": {
    "type": "CREATE_ALERT_RULE",
    "device_id": "pump station",
    "metric": "pressure",
    "condition": "BELOW",
    "threshold": 20,
    "duration_minutes": 1,
    "notify_via": ["EMAIL"]
  },
  "status": "REJECTED",
  "reason": "Device 'pump station' does not exist in the registry."
}
```

**Input:** *"let me know if the server room temperature goes above 30 for 5 minutes"*

```json
{
  "understood": {
    "type": "CREATE_ALERT_RULE",
    "device_id": "server room",
    "metric": "temperature",
    "condition": "ABOVE",
    "threshold": 30,
    "duration_minutes": 5,
    "notify_via": ["EMAIL"]
  },
  "status": "REJECTED",
  "reason": "Device 'server room' does not exist in the registry."
}
```

Both are a nice real-world illustration of the system's design intent:
Gemini correctly extracted metric, condition, threshold, and duration
purely from natural phrasing in both cases — genuine language
understanding, not pattern matching against my few-shot examples. But
in both cases it guessed a plausible-but-wrong device id (`"pump
station"` instead of the registry's `"pump-station-4"`, `"server room"`
instead of `"server-room-a"`) — a space instead of the registry's exact
hyphenated id.

This is exactly why the architecture never lets the LLM's output reach
`store.py` directly. `validator.py` caught both mismatches and rejected
them with a clear, specific reason rather than silently creating rules
for devices that don't actually exist under those ids. The LLM's
language understanding was good; its knowledge of my exact internal
naming scheme was, correctly, not trusted.

---

## A bug I found and fixed: tests were leaking my local `.env`

While testing the live Gemini integration, I temporarily set
`MOCK_MODE=false` in my `.env` to confirm real API calls worked. I then
re-ran `pytest` without changing anything back — and one test
(`test_ambiguous_camera_offline_is_handled_not_crashed`) failed. The
test suite had, without my intending it to, called the real Gemini API
during a `pytest` run and taken ~27 seconds to do so, and Gemini
returned a reasonable but slightly different interpretation than the
hardcoded value my test asserted against.

This happened because `llm_client.py` reads `MOCK_MODE` from the
environment once at import time, and my tests had no isolation from
whatever `.env` said. That's a real gap: automated tests should never
depend on a developer's local, mutable configuration, and definitely
shouldn't silently become live network calls.

**Fix:** `tests/conftest.py` now sets `os.environ["MOCK_MODE"] = "true"`
before the app is imported, forcing every test run into mock mode
regardless of local `.env` state. After the fix, the full suite runs in
0.02s instead of ~27s and is fully deterministic again. I'm noting this
here rather than quietly fixing it, since catching and correcting this
kind of test-isolation bug is arguably a more meaningful signal than
not having hit it in the first place.

---

## Known limitations

- **In-memory storage only.** Rules disappear on server restart. Fine
  per the assignment's scope, not fine for production.
- **No live telemetry.** `QUERY_STATUS` returns a stubbed value since
  there's no real sensor backend — out of scope per the assignment.
- **Small mock device registry.** Only 6 devices are defined, using
  strict hyphenated ids (e.g. `pump-station-4`). As shown in the live
  experiment above, natural phrasing doesn't always match these exactly
  — a production system would want fuzzy/alias matching on device ids
  rather than exact string equality.
- **`google-generativeai` is deprecated.** Google has end-of-lifed this
  SDK in favor of `google.genai`. The current implementation still
  works but should be migrated with more time.
- **Model name pinning risk.** An earlier version of this project used
  `gemini-2.5-flash` directly, which became unavailable to new API keys
  partway through development. Switched to the `gemini-flash-latest`
  alias to reduce (not eliminate) this risk going forward.
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
- Add fuzzy device-id matching (e.g. normalize spaces/hyphens, or a
  small similarity check) so near-miss ids like `"server room"` vs
  `"server-room-a"` could resolve automatically instead of always
  rejecting — while keeping the safety property that genuinely unknown
  devices still get rejected.
- Migrate off the deprecated `google-generativeai` SDK to `google.genai`.
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

Roughly 3-4 hours across a few sessions: schema + registry + validator
first, then the LLM integration and prompt iteration, then tests, then
debugging the model-deprecation and test-isolation issues that came up
while testing the live Gemini path, then this README.
EOF
