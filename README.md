# oncall-router-mcp

An MCP server that answers the three questions that eat the first ten minutes of an
incident: **who owns this**, **who do I wake and by when**, and **what does the runbook
say to try first**. Plus a fourth that most tools get wrong, which is **where should we be
on the clock right now**, measured from when impact started rather than from when somebody
opened a ticket.

No runtime dependencies, no API key, no network calls, no telemetry. It reads one local file. pytest is needed only to run the gates.

## Why this exists

Escalation knowledge lives in three places: a wiki nobody updated, a rotation tool that
only knows the current shift, and the head of whoever has been there longest. At 2am the
expensive minutes go to working out who to call, not to fixing anything.

This puts that knowledge somewhere an assistant can reach it, and makes the timing
explicit. The design opinion in the code is that escalation timing runs from impact start.
A ticket opened twenty minutes late does not buy the responder twenty extra minutes, and a
tool that measures from ticket creation will quietly tell you that it does.

## The five tools

| tool | answers | when it cannot |
|---|---|---|
| `who_owns` | which team owns a service, and how to reach them now | says so, and offers near matches as candidates rather than as an answer |
| `escalation_path` | who to wake, in order, with the minute each hop is due | refuses an unknown severity rather than defaulting to the quietest one |
| `playbook` | what the runbook says to check first | falls back to the service's general steps and sets `fell_back` so the caller can tell |
| `impact_clock` | which hop should be active now, and what is overdue | requires an explicit `now`, and refuses a start time in the future |
| `mttx_review` | where the minutes went - Detect, React, Mitigate - and which tool shrinks the worst phase | measures only phases whose endpoints were supplied; refuses out-of-order timestamps by name |

Every tool fails closed. A near miss never silently resolves, because a confident wrong
escalation costs more than an honest "I do not know".

See [docs/TRANSCRIPT.md](docs/TRANSCRIPT.md) for real output from every tool, including
the failure paths. CI regenerates that file and fails the build if it drifts from what the
code actually produces.

## Run it

```bash
git clone <this repo> && cd oncall-router-mcp
python -m pip install "pytest>=7"          # the only dependency, and only to run the tests
python -m pytest tests/ -q                 # run the gates; the count is whatever pytest reports, never a number this file maintains
PYTHONPATH=src python -m oncall_router.server --catalog catalog.toml
```

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

Point an MCP client at that command. To use your own data, copy `catalog.toml`, edit it,
and pass `--catalog yours.toml`. No code changes: the catalog is data, and a test proves
it by running the same tool against two different catalogs.

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

Built against a rubric frozen before the first line of code. The ones worth knowing:

- Every tool answers through a real client speaking the wire protocol, not just as a
  function call in a test.
- Every tool has a failure-path test proving it declines rather than guesses.
- Tests were observed failing before each implementation existed.
- Swapping the catalog changes every answer with no code edit, proven by a test.
- The committed transcript regenerates, or the build fails.
- No credentials, no network calls in the source, no employer content, no third-party
  imports. This gate blocks.


