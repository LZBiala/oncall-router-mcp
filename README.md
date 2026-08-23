# oncall-router-mcp

An MCP server that answers the three questions that eat the first ten minutes of an
incident: **who owns this**, **who do I wake and by when**, and **what does the runbook
say to try first**. Plus a fourth that most tools get wrong, which is **where should we be
on the clock right now**, measured from when impact started rather than from when somebody
opened a ticket.

Zero dependencies. No API key, no network calls, no telemetry. It reads one local file.

## Why this exists

Escalation knowledge lives in three places: a wiki nobody updated, a rotation tool that
only knows the current shift, and the head of whoever has been there longest. At 2am the
expensive minutes go to working out who to call, not to fixing anything.

This puts that knowledge somewhere an assistant can reach it, and makes the timing
explicit. The design opinion in the code is that escalation timing runs from impact start.
A ticket opened twenty minutes late does not buy the responder twenty extra minutes, and a
tool that measures from ticket creation will quietly tell you that it does.

## The four tools

| tool | answers | when it cannot |
|---|---|---|
| `who_owns` | which team owns a service, and how to reach them now | says so, and offers near matches as candidates rather than as an answer |
| `escalation_path` | who to wake, in order, with the minute each hop is due | refuses an unknown severity rather than defaulting to the quietest one |
| `playbook` | what the runbook says to check first | falls back to the service's general steps and sets `fell_back` so the caller can tell |
| `impact_clock` | which hop should be active now, and what is overdue | requires an explicit `now`, and refuses a start time in the future |

Every tool fails closed. A near miss never silently resolves, because a confident wrong
escalation costs more than an honest "I do not know".

See [docs/TRANSCRIPT.md](docs/TRANSCRIPT.md) for real output from every tool, including
the failure paths. CI regenerates that file and fails the build if it drifts from what the
code actually produces.

## Run it

```bash
git clone <this repo> && cd oncall-router-mcp
python -m pytest tests/ -q                 # 26 tests, no install needed
PYTHONPATH=src python -m oncall_router.server --catalog catalog.toml
```

Point an MCP client at that command. To use your own data, copy `catalog.toml`, edit it,
and pass `--catalog yours.toml`. No code changes: the catalog is data, and a test proves
it by running the same tool against two different catalogs.

## The catalog

One TOML file holding services, the team that owns each, escalation chains with timings,
and runbook steps by symptom. TOML rather than YAML because `tomllib` ships in the Python
standard library, so the catalog costs this project zero dependencies.

Aliases matter more than they look. During an incident people type the name they remember,
so `gateway`, `apigw`, `edge` and `the gateway` all resolve to `api-gateway`.

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
