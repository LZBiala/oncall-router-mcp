# oncall-router-mcp

![ci](https://github.com/LZBiala/oncall-router-mcp/actions/workflows/ci.yml/badge.svg)

An MCP server that answers the three questions that eat the first ten minutes of an
incident: **who owns this**, **who do I wake and by when**, and **what does the runbook
say to try first**. Plus a fourth that most tools get wrong, which is **where should we be
on the clock right now**, measured from when impact started rather than from when somebody
opened a ticket.

## What this is

A small program that reads one text file about your services and answers five questions for an AI assistant: who owns this, who to wake and by when (escalation: the next person to call when the first does not answer), what to try first, which escalation step should be active by now, and, the day after, which phase of the incident ate the minutes. It never pages anyone or changes anything; it only answers. In jargon, an MCP server. MCP is the Model Context Protocol, a published standard for how an assistant plugs into outside tools, the way a wall socket is a standard for plugging in appliances. This one speaks the protocol by hand, three message types and no library, and its own source says a production deployment would use the official one.

## Why it matters

At 2am the first minutes of an incident go to finding who to call and what to try, not to fixing anything, because that knowledge sits in three places: a wiki nobody updated, a rotation tool that knows only this shift, and whoever has been there longest. This puts it in one file your assistant can read, and it would rather say "I do not know" than guess: a confident wrong page costs more than an honest refusal.

## Try it

Clone the repo (download a copy) and, inside it, run these three lines. Run on 2026-09-01 with Python 3.12.10 on Windows 11: the tests took 2.32 seconds; the clone and the install depend on your network and were not timed.

```
python -m pip install "pytest>=7,<10"
python -m pytest tests/ -q
PYTHONPATH=src python -m oncall_router.server --catalog catalog.toml
```

Line 1 installs pytest, the test runner and the only package the repo asks you to install. Line 2 runs the tests (count and caveat below). Line 3 starts the server, which waits silently for questions: correct, not a hang. On PowerShell that line is `$env:PYTHONPATH="src"; python -m oncall_router.server --catalog catalog.toml`. Asking who_owns with {"service": "cart"} answered checkout and its on-call handle, the name you would page (invented sample data). Wiring it into an assistant such as Claude Desktop or Claude Code is described below; no test in the repo exercises that wiring.

## How it works, intuitively

Picture the phone tree taped beside an office phone. This program is that sheet with one extra column: deadlines counted from when customers began hurting, not from when the ticket was opened. The sheet does not dial; neither does this.

It loads the catalog once at start-up. The catalog is one plain-text file in TOML format, chosen because Python reads TOML with nothing extra installed. Per question it maps nicknames like "cart" to "checkout", walks the call order adding up minutes against the elapsed time you supplied (it never reads the wall clock; a search of the source finds no call to the system time), and writes one line back. An unknown name gets found false plus near-misses, never a guess.

## What the numbers mean (and what they do not)

Each number carries its measurement and its limit in the same sentence. Checkable means you can rerun it from a clone; asserted means you are taking my word for it. The three below are checkable; the date and machine they were run on are asserted.

- 82 tests passed in one run of pytest on 2026-09-01. The repo's own setup instructions print no count on purpose, because it rises with every test added, so 82 holds for that date only. All 82 were written on the author's side, so they check what the author thought to check: green is a ceiling on what the suite can promise, not a proof the code is right.
- 5 tools, confirmed by a live tools/list call (the protocol's "what can you do" question) and by a test that pins the exact set. The rubric, the pass-or-fail list frozen before the code, scoped four; mttx_review was added 2026-08-24 under a separate frozen extension, and the rubric file says so.
- 0 runtime dependencies (nothing to install beyond Python 3.11 or newer) and no network calls in the source. Both are enforced by tests that read the text of the src/ folder: one rejects any import outside a short list of Python's own modules, the other fails if the source names any of five networking names. A text scan proves those words are absent; it is not a run watched with the network cable pulled.

## Where it loses

The repo names its edges: "No live integrations." "No write actions." "The shipped catalog is fictional." "The timing model is a convention, not a standard." Two claims it cannot prove: that every test was seen failing before its code existed (CI, the robot that reruns the tests on every push, cannot enforce history, and a log of 6 commits, the saved snapshots of the code, cannot show a per-test fail-then-pass sequence), and the headless assistant run described below, a run with no human at the keyboard, which nothing in the repo tests. One edge found by running it: pipe questions in by hand from a PowerShell set to UTF-8 output and the first line arrives with an invisible marker some Windows tools prepend to text, so the server skips that line without a word; the same lines from a plain file were all answered, and assistant clients do not send the marker.

## Try your own case

For your own file, copy catalog.toml, edit its services, teams and call orders, and run `PYTHONPATH=src python -m oncall_router.server --catalog your.toml`. To add a test, copy one row of the table of cases in tests/test_server.py (lines 48-67), change its inputs and expected output, and rerun pytest. The hygiene tests, the ones that police the text rather than the behaviour, scan every text file in the repo except the scanner itself: hyphens only, no key-shaped strings, none of nine marketing phrases.

---

## For engineers

Everything below is the original technical README: the design, the measurements, and how to reproduce them.

No runtime dependencies, no API key, no network calls, no telemetry. It reads one local
file. pytest is needed only to run the gates.

## Explained simply

Picture the wall next to an old fire-station telephone. Taped to it is a laminated card:
which crew covers which district, who to call when the first call goes unanswered, and
what to do first for each kind of fire - with the minutes printed beside each name, so
you know when an unanswered call becomes the next call. Every firehouse has one, because
at 2am nobody should be *remembering* - they should be *reading*.

This server is that laminated card for your software, written so an AI assistant can read
it for you while your hands are busy. That is all MCP (Model Context Protocol) is: a
standard socket that lets an assistant plug into outside tools. This repo is one small
plug. It puts your team's on-call knowledge - owners, escalation chains, runbook first
moves, expected timings - where the assistant you already use can reach it.

The knowledge itself usually lives in three places: a wiki nobody updated, a rotation tool
that only knows the current shift, and the head of whoever has been there longest. At 2am
the expensive minutes go to working out who to call, not to fixing anything. This moves
those minutes back where they belong.

## What this looks like during a real incident

It is 2:47am. Your monitor fires: **checkout error rate 40% for six minutes**. You open
your assistant, paste the alert, and ask for a first-ten-minutes brief. With this server
connected, the assistant can answer from your catalog instead of from its imagination:

1. **"Who owns this?"** - `who_owns("cart")` resolves the alias (nobody types
   `checkout-service-v2` at 2am) and returns the Storefront team with the primary on-call
   handle and their coverage hours.
2. **"Who do I wake, and by when?"** - `escalation_path("checkout", "sev1")` returns the
   full chain in order - primary at minute 5, secondary at minute 15, engineering manager
   at minute 30, then up into Platform Incident Command - because a sev1 climbs all the
   way and a sev3 deliberately does not.
3. **"What do I try first?"** - `playbook("checkout", "declines")` returns the two moves
   written for that exact symptom, starting with splitting declines by payment method,
   because one failing method hides inside an overall rate.
4. **"Where should we be on the clock?"** - `impact_clock` takes when impact started and
   what time it is now, and answers which escalation hop should already be active and
   what is overdue - measured from impact start, not from when the ticket was opened.

Every answer above is what the shipped sample catalog actually returns, word for word in
structure. The full JSON for every
tool, including the failure paths, is in [docs/TRANSCRIPT.md](docs/TRANSCRIPT.md) - and CI
regenerates that file on every push and fails the build if it drifts from what the code
actually produces. The docs cannot lie about the code.

## Wire it into your production alert flow

Three patterns, from zero setup to fully automated. In all three the server only ever
*answers questions* - it never pages anyone and never changes state, so the human stays in
command.

**1. Paste the alert (zero setup beyond the config below).** Alert lands in your phone,
you paste it into Claude Desktop or Claude Code with this server connected, together with
this prompt:

```text
A production alert just fired. Alert text: <paste the alert here>.
Using only the oncall-router tools, give me a first-ten-minutes brief:
1. Which service is this and who owns it (who_owns - try the name the alert uses).
2. Who do I wake and by when (escalation_path - I will give you the severity).
3. The first three moves (playbook - match the symptom; say if you fell back to general).
4. Where we are on the clock (impact_clock - impact started at <time>, it is now <time>).
Report exactly what the tools return. If a tool says found=false, say so - do not guess.
```

**2. Trigger it from the alert itself (headless).** Any alerting webhook can hand the
payload to a headless assistant run, and the brief is drafted before you have found your
glasses. Save the JSON config from the setup section below as `oncall.mcp.json` - same
shape, same paths:

```bash
claude -p "PRODUCTION ALERT: 'checkout error rate 40% for six minutes'. Impact start
02:41Z, now 02:47Z, severity sev1. Use the oncall-router tools to write a
first-ten-minutes brief: owner, escalation order with due minutes, first three runbook
moves, current hop on the clock. Only report what the tools return." \
  --mcp-config oncall.mcp.json \
  --allowedTools "mcp__oncall-router__who_owns,mcp__oncall-router__escalation_path,mcp__oncall-router__playbook,mcp__oncall-router__impact_clock"
```

The `--allowedTools` grant is not optional: a headless run has nobody to answer a
permission prompt, so without it the assistant can see the tools and use none of them.
The names follow `mcp__<server>__<tool>`, where `<server>` is the key you chose in the
JSON config (`oncall-router` above).

`claude -p` writes the brief to stdout; piping that into your chat tool's incoming
webhook is the one line left to you, on purpose. Two honest notes: the server stays
keyless, but the assistant running it authenticates as itself; and the same pattern works
with the Claude Agent SDK or any MCP-speaking agent runner. The assistant drafts the
brief; a human decides what to do with it. That division of labor is deliberate and this
server enforces its half of it.

**3. The day after (see "After the incident" below).** Feed `mttx_review` the timestamps
you actually have and learn which phase ate the incident - so next month's 2:47am is
shorter than this one's.

## The five tools

| tool | answers | when it cannot |
|---|---|---|
| `who_owns` | which team owns a service, and how to reach them now | says so, and offers near matches as candidates rather than as an answer |
| `escalation_path` | who to wake, in order, with the minute each hop is due | refuses an unknown severity rather than defaulting to the quietest one |
| `playbook` | what the runbook says to check first | falls back to the service's general steps and sets `fell_back` so the caller can tell |
| `impact_clock` | which hop should be active now, and what is overdue | requires an explicit `now`, and refuses a start time in the future |
| `mttx_review` | where the minutes went - Detect, React, Mitigate - and which tool shrinks the worst phase | measures only phases whose endpoints were supplied; refuses out-of-order timestamps by name |

Every tool fails closed. A near miss never silently resolves, because a confident wrong
escalation at 2am costs more than an honest "I do not know".

## Run it in sixty seconds

```bash
git clone <this repo> && cd oncall-router-mcp   # Python 3.11+ (tomllib is stdlib from 3.11)
python -m pip install "pytest>=7"          # the only dependency, and only to run the tests
python -m pytest tests/ -q                 # run the gates; the count is whatever pytest reports, never a number this file maintains
PYTHONPATH=src python -m oncall_router.server --catalog catalog.toml
```

On PowerShell, the last line is: `$env:PYTHONPATH="src"; python -m oncall_router.server --catalog catalog.toml`

To wire it into Claude Desktop or Claude Code, add this to your MCP client config,
using absolute paths:

```json
{
  "mcpServers": {
    "oncall-router": {
      "command": "python",
      "args": ["-m", "oncall_router.server", "--catalog", "/abs/path/to/catalog.toml"],
      "env": { "PYTHONPATH": "/abs/path/to/oncall-router-mcp/src" }
    }
  }
}
```

`"command"` must resolve to a Python 3.11 or newer. Desktop clients do not inherit your
shell's PATH, so on macOS especially, replace `"python"` with the absolute path from
`which python3` - and note that `/usr/bin/python3` is Apple's 3.9 stub, which is too old.
On Windows, use the full path to your `python.exe`.

To use your own data, copy `catalog.toml`, edit it, and pass `--catalog yours.toml`. No
code changes: the catalog is data, and a test proves it by running the same tool against
two different catalogs. Editing one readable file is the entire onboarding cost for a new
team.

## The catalog

One TOML file holding services, the team that owns each, escalation chains with timings,
and runbook steps by symptom. TOML rather than YAML because `tomllib` ships in the Python
standard library, so the catalog costs this project zero dependencies.

Aliases matter more than they look. During an incident people type the name they remember,
not the name in the repo: `cart`, `buy button` and `the checkout` all resolve to
`checkout`, the same way `gateway` and `apigw` resolve to `api-gateway`. Nobody types
`checkout-service-v2` at 2am, and a router that only answers to the formal name has
already cost you a minute.

## After the incident: where did the minutes go

The four tools above serve the first ten minutes. The fifth, `mttx_review`, serves the
day after. Give it the timestamps you actually have - when impact started, when anyone
first knew (**Detect**), when a responder engaged (**React**), when customers stopped
feeling it (**Mitigate**) - and it measures each phase, names the one that ate the
incident, and points at the tool or practice that shrinks it next time. React dominant?
The minutes went to finding the right person, which is what `escalation_path` exists to
fix. Mitigate dominant? The first three moves belong in the runbook, which is what
`playbook` serves. Detect dominant? The tool says honestly that detection lives in your
alerting, not in this server.

Three design choices worth naming. A phase is measured only when both of its endpoints
were supplied - a missing milestone is reported as `unmeasured`, never interpolated. A
still-open incident requires an explicit `now` and gets told which phase is bleeding
right now. And there is no grade, deliberately: thresholds for a "good" MTTx vary by an
order of magnitude across teams and tiers, so the shares and the dominant phase are
reported as facts and the judgment stays with the team that owns the service.

## Why it is built this way

The design opinion in the code is that **escalation timing runs from impact start**. A
ticket opened twenty minutes late does not buy the responder twenty extra minutes, and a
tool that measures from ticket creation will quietly tell you that it does.

The second opinion is that **at 2am, "I do not know" beats a plausible guess**, every
time. That is why unknown services return candidates instead of a best match, why an
unknown severity is refused instead of defaulted, and why a missing timestamp becomes
`unmeasured` instead of an interpolation. An assistant wired to this server inherits that
honesty: it cannot confidently misroute you, because the tool underneath refuses to.

## What this deliberately does not do

- **No live integrations.** It does not read your incident tool, your rotation tool, or
  your monitoring. Those are per-customer decisions and they belong behind a boundary.
- **No write actions.** It never pages anyone, opens anything, or changes state. It
  answers questions and a human decides.
- **The shipped catalog is fictional.** Every service, team, and handle in `catalog.toml`
  is invented. A test fails the build if anything employer-identifying appears in the repo.
- **The timing model is a convention, not a standard.** Cumulative minutes from impact
  start, carried forward when the chain climbs to another team. Reasonable, and not the
  only reasonable choice.
- **No cost or latency figures**, because there are no model calls. The server is
  deterministic and local.

## Gates

Built against a rubric frozen before the first line of code - published in full, with
its publication edits disclosed, as [docs/RUBRIC.md](docs/RUBRIC.md). The gates CI
enforces, worth knowing:

- Every tool answers through a real client speaking the wire protocol, not just as a
  function call in a test.
- Every tool has a failure-path test proving it declines rather than guesses.
- Swapping the catalog changes every answer with no code edit, proven by a test.
- The committed transcript regenerates, or the build fails.
- One malformed client message never ends the session, and errors never leak the
  deployment path.
- The whole suite runs in CI on Linux and Windows on every push.
- No credentials, no network calls in the source, no employer content, no third-party
  imports. This gate blocks.

One process claim sits outside that list on purpose: tests were written and observed
failing before each implementation existed. CI cannot enforce history, so that is an
assertion you audit rather than a gate a build proves - the commit trail is the closest
thing to evidence it has.

## Who built this

Built by an SRE lead who carries a real pager and wanted the first ten minutes back.
Part of a public, CI-verified portfolio where every published number regenerates or the
build fails: [lzbiala.github.io](https://lzbiala.github.io)

MIT licensed. Copy the catalog, keep the fail-closed defaults, make it yours.
