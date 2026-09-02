# A recorded headless run (2026-09-02)

One run of the README's own `claude -p` recipe, on a Windows laptop, against the shipped fictional catalog. This file is a receipt, not a test: nothing in CI reruns it, and a second run could phrase the brief differently. The stream was captured with `--output-format stream-json --verbose`; session ids and local paths are removed, nothing else is edited. The prompt gave clock times only; the assistant supplied a calendar date to call `impact_clock`, visible in its arguments below.

## The command

```bash
claude -p "PRODUCTION ALERT: 'checkout error rate 40% for six minutes'. Impact start
02:41Z, now 02:47Z, severity sev1. Use the oncall-router tools to write a
first-ten-minutes brief: owner, escalation order with due minutes, first three runbook
moves, current hop on the clock. Only report what the tools return." \
  --mcp-config oncall.mcp.json \
  --allowedTools "mcp__oncall-router__who_owns,mcp__oncall-router__escalation_path,mcp__oncall-router__playbook,mcp__oncall-router__impact_clock" \
  --output-format stream-json --verbose
```

`oncall.mcp.json` is the setup-section config with absolute paths filled in: the Python from a local virtual environment, `PYTHONPATH` pointing at `src`, `--catalog` at the shipped `catalog.toml`.

## What happened: 6 turns, 4 tool calls, model claude-fable-5, cost 1.10 USD, result `success`

### 1. `mcp__oncall-router__who_owns`

Arguments:

```json
{
  "service": "checkout"
}
```

Returned:

```text
{
  "found": true,
  "asked_for": "checkout",
  "service": "checkout",
  "description": "The page where customers pay. When this hurts, revenue hurts by the minute.",
  "tier": 1,
  "team": "Storefront",
  "hours": "24x7",
  "contact": "@storefront-oncall",
  "contact_role": "primary on-call"
}
```

### 2. `mcp__oncall-router__escalation_path`

Arguments:

```json
{
  "service": "checkout",
  "severity": "sev1"
}
```

Returned:

```text
{
  "found": true,
  "service": "checkout",
  "severity": "sev1",
  "severity_meaning": "Customer-facing outage or material financial impact.",
  "hops": [
    {
      "team": "Storefront",
      "role": "primary on-call",
      "handle": "@storefront-oncall",
      "at_minute": 5
    },
    {
      "team": "Storefront",
      "role": "secondary on-call",
      "handle": "@storefront-secondary",
      "at_minute": 15
    },
    {
      "team": "Storefront",
      "role": "engineering manager",
      "handle": "@storefront-em",
      "at_minute": 30
    },
    {
      "team": "Platform Incident Command",
      "role": "incident commander",
      "handle": "@incident-command",
      "at_minute": 35
    }
  ]
}
```

### 3. `mcp__oncall-router__playbook`

Arguments:

```json
{
  "service": "checkout",
  "symptom": "errors"
}
```

Returned:

```text
{
  "found": true,
  "service": "checkout",
  "matched": "general",
  "fell_back": true,
  "asked_for": "errors",
  "steps": [
    "Check the payment success rate against the seven-day baseline before anything else.",
    "Compare against the last deploy: most checkout pain follows a change somebody shipped.",
    "If one payment method is failing, disable that method before debugging it - customers can still pay another way while you look."
  ],
  "known_symptoms": [
    "declines",
    "slow pages"
  ]
}
```

### 4. `mcp__oncall-router__impact_clock`

Arguments:

```json
{
  "service": "checkout",
  "severity": "sev1",
  "impact_start": "2026-09-01T02:41:00Z",
  "now": "2026-09-01T02:47:00Z"
}
```

Returned:

```text
{
  "found": true,
  "service": "checkout",
  "severity": "sev1",
  "impact_start": "2026-09-01T02:41:00+00:00",
  "now": "2026-09-01T02:47:00+00:00",
  "elapsed_minutes": 6,
  "current_hop": {
    "team": "Storefront",
    "role": "primary on-call",
    "handle": "@storefront-oncall",
    "at_minute": 5
  },
  "overdue": [
    {
      "team": "Storefront",
      "role": "primary on-call",
      "handle": "@storefront-oncall",
      "at_minute": 5
    }
  ],
  "next_hop": {
    "team": "Storefront",
    "role": "secondary on-call",
    "handle": "@storefront-secondary",
    "at_minute": 15
  },
  "minutes_to_next": 9,
  "note": "Elapsed time is measured from impact start, not from ticket creation."
}
```

## The brief the assistant wrote

```text
**Sev1 checkout - first-ten-minutes brief** (impact start 02:41Z, now 02:47Z, 6 minutes elapsed)

**Owner:** Storefront team owns checkout (tier 1, 24x7 coverage - "when this hurts, revenue hurts by the minute"). Reach the primary on-call at **@storefront-oncall** now.

**Escalation order for sev1** ("customer-facing outage or material financial impact"), due minutes measured from impact start:
1. @storefront-oncall - Storefront primary on-call - due at minute 5
2. @storefront-secondary - Storefront secondary on-call - due at minute 15
3. @storefront-em - Storefront engineering manager - due at minute 30
4. @incident-command - Platform Incident Command incident commander - due at minute 35

**Clock status:** The active hop is the Storefront primary on-call, and it is already **overdue** - it was due at minute 5 and we're at minute 6. If the primary isn't engaged, page them immediately; the secondary comes due in 9 minutes (minute 15). The router notes elapsed time runs from impact start, not ticket creation.

**First three runbook moves** (the runbook has no entry for "errors" - its known symptoms are "declines" and "slow pages" - so these are checkout's general steps, per its fallback):
1. Check the payment success rate against the seven-day baseline before anything else.
2. Compare against the last deploy - most checkout pain follows a change somebody shipped.
3. If one payment method is failing, disable that method before debugging it; customers can still pay another way while you look.

If the 40% error rate turns out to be payment declines specifically, it's worth re-querying the playbook with the "declines" symptom for the targeted steps.
```

## What this run does and does not show

- It shows the four tools called with the arguments the README predicts, and a brief assembled from what they returned; the tool results above let a reader check that claim line by line.
- The turn before the first tool call was the assistant looking up the four tool schemas; that is client behavior, not something the server does.
- It does not show correctness on a real catalog: every owner, rota, and runbook here is fictional by design.
- It does not show repeatability: one run, one model, one date. The transcript CI does regenerate is `docs/TRANSCRIPT.md`, which drives the server directly and needs no assistant.
- The server stayed keyless; the assistant authenticated as itself, on the author's own subscription.
