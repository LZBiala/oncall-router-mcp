# The rubric

The README says this project was "built against a rubric frozen before the first line of
code." A claim you cannot check is just a story, so here is the rubric. Two documents: the
original, frozen 2026-08-23 before any code existed, and the extension for the fifth tool,
frozen 2026-08-24 before its build began.

## Publication notes (every edit, disclosed)

This is the working document from the project's planning notes. Publishing it took some
edits, and silently editing a frozen document would defeat the point of publishing it,
so here is all of them - a fresh-context reviewer diffed this file against the originals
and this list is what survived that check:

1. **One redaction in G6.** The original named a specific employer whose data must never
   appear in this repo, so it reads "[employer]" below. The gate that enforces this
   compares SHA-256 hashes of the banned terms, so the scan covers every file in the repo
   including the gate's own source, and the name appears nowhere in the working tree - a
   first version kept the terms in plain text inside the gate and exempted that one file
   from its own scan, which made this note false one file away from where it was made.
   That version existed in early history; the hash form is what ships.
2. **G4's filename was generalized.** The original said `catalog.yaml`; between freezing
   and the first commit the file became `catalog.toml`, when `tomllib` being in the
   Python standard library made TOML the zero-dependency choice. Rather than publish a
   filename that never shipped, the gate below says "the catalog". The gate's substance -
   the catalog is data, never code - is unchanged and tested.
3. **Three clauses referencing private planning tools were removed as redactions**: a
   personal testing doctrine cited in G3, a comparison to sibling projects in G5, and a
   private checker's name in G8. Each was context, not requirement; nothing the gates
   govern changed.
4. **"the four tools" was the original scope.** The fifth tool, `mttx_review`, was added
   2026-08-24 under its own frozen extension, included in full below. Its R9 pins "41
   prior tests" - true on its freeze date, and left as written because editing a frozen
   number is exactly what this repo exists to not do.

## Original rubric - oncall-router-mcp (frozen 2026-08-23)

Frozen before a line of code. A gate that fails sends the design back; it does not get
relaxed to let the build through. Any gate changed after a run is disclosed in the commit
that changes it, with the reason.

### Correctness gates

**G1 - every tool answers through a real MCP client.**
Not "the function returns a dict". A client connects over stdio, lists the tools, calls
each one, and gets a well-formed response. Verified in CI, not by hand.

**G2 - every tool fails closed, and a test proves it.**
For each of the four tools there is a test that feeds it something it cannot answer and
asserts it declines rather than guesses. An unknown service must not resolve to the
nearest owner. An unknown severity must not fall back to the lowest one.

**G3 - RED observed before GREEN, every tool.**
The test exists and fails for the stated reason before the implementation is written. If
a test passes the moment it is added, it is not testing what its name claims and gets
rewritten. A suite that cannot fail is decoration.

**G4 - the catalog is data, never code.**
Swapping the catalog changes every answer with no code edit. Proven by a test that runs
the same tool against two different catalogs and asserts different results.

### Honesty gates

**G5 - the README's example transcript regenerates.**
CI reruns the documented examples and fails if the committed output differs. The
committed artifact IS the claim.

**G6 - no key, no network, no employer data.**
CI asserts there is no outbound network call in the test run, no credential-shaped string
in the repo, and no [employer] service, team, or person name anywhere in the catalog or
docs.

**G7 - it says what it cannot do.**
The README carries an explicit limits section: no live integration, no write actions,
sample catalog is fictional, timing model is a convention rather than an industry
standard. A reader should finish the README knowing where the edges are.

### Craft gates

**G8 - hyphens only, no slop.**
No em or en dashes, none of the slop vocabulary already forbidden elsewhere in the
portfolio. Checked in CI so it cannot drift.

**G9 - a non-engineer can follow the walkthrough.**
Someone who does not write Python can read the walkthrough and understand what the server
does and why the impact clock matters. Tested by reading it aloud and hearing where it
stalls.

**G10 - installable in under five minutes from a cold clone.**
Clone, install, point a client at it, get an answer. If the README needs a
troubleshooting section to achieve this, the setup is wrong and gets fixed rather than
documented.

### Remedy ladder, pre-registered

- **G1 or G2 fails:** the tool is broken. Fix the tool, never the assertion.
- **G3 fails** (a test passed on arrival): rewrite the test to assert the behaviour its
  name promises, then re-observe RED.
- **G4 fails:** the catalog has leaked into the code. Extract it, do not special-case it.
- **G5 fails:** the docs drifted from the code. Regenerate the docs; never hand-edit the
  transcript to match.
- **G6 fails:** stop and remove, before any commit. This gate blocks.
- **G10 fails:** cut setup steps until it passes. Adding documentation is not a fix.

## Extension rubric - mttx_review (frozen 2026-08-24, before its build)

R1. **Closed incident measures true.** Known timestamps produce exact phase minutes,
    shares that sum to 100 (+-1 for rounding), the right dominant phase, and
    total_impact_minutes = mitigated - impact_start.
R2. **The loop closes.** React-dominant output carries a next_tool hint naming
    escalation_path; Mitigate-dominant names playbook; Detect-dominant honestly says
    detection lives outside this server.
R3. **Open incidents demand a clock.** No mitigated + no now = refusal; with now, the
    open phase is named with minutes_in_phase, and now earlier than a supplied milestone
    is refused.
R4. **Refusals name the defect.** Out-of-order pairs by name; mixed tz-awareness by
    field; unknown service with did_you_mean; impact_start alone with no now.
R5. **Partial data is partial, never guessed.** A missing middle milestone yields
    unmeasured phases listed by name, and dominance considers only measured phases.
R6. **No grade anywhere in the output.**
R7. **The boundary holds.** Dispatch routes mttx_review; non-string fields get the
    typecheck refusal; a bad call cannot end the session.
R8. **The teaching example lands.** checkout resolves from cart / buy button / the
    checkout; README's alias paragraph uses it; api-gateway remains in the catalog.
R9. **Every existing gate stays green**: 41 prior tests, no-deps, no-network, hygiene
    (hyphens, no employer names), transcript regenerates byte-identical in CI.
R10. **RED observed before GREEN** for every new test; QA workflow findings triaged and
    the real ones fixed before push.

## Checking it yourself

The gates that CI can enforce live in `tests/` - run `python -m pytest tests/ -q` and
read the test names against the gate numbers above. Four gates are human gates that no
build can prove, and saying so plainly beats implying otherwise: G3 and R10 (RED observed
before GREEN) are process history, auditable only through the commit trail; G7 is a
reading judgment; G9 and G10 (the walkthrough read-aloud and the five-minute cold clone)
are yours to try.
