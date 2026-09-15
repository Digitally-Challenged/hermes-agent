# Why the Lint Checks Exist

A lint report is easy to read as a to-do list and easy to dismiss as hygiene. These
checks encode specific failure modes that kill wikis. Knowing the failure mode is what
tells you which findings are urgent and which are cosmetic.

## Broken wikilinks — CRITICAL

`[[some-page]]` pointing at nothing is not a cosmetic typo. The wiki's entire claim to
value is that the links are already there, so a reader (human or agent) can follow the
chain without searching. A broken link is a chain someone will pull on and find nothing.

The second-order damage is worse: an agent that finds broken links learns the links are
unreliable and starts ignoring them, falling back to full-text search. At that point the
wiki is a slow, badly-structured RAG corpus and the compounding advantage is gone.

Treat broken links as build errors, not warnings.

## Source drift — CRITICAL

Every `raw/` file carries a `sha256` of its body. When the recomputed hash differs, one
of two things happened, and both matter:

1. **The raw file was edited.** It shouldn't have been — `raw/` is immutable by contract.
   An edit there means the wiki's pages now cite a source that no longer exists in the
   form they cited.
2. **The upstream URL changed.** You re-fetched a page and the page is different now.
   This is the more common case, and it is genuinely valuable: silently-changed source
   material is how a wiki ends up confidently asserting last quarter's truth.

Drift is a correctness signal because wiki pages are derived artifacts. When the source
moves, every claim traced to it is suspect until re-checked. This is why the check is
CRITICAL rather than informational.

## Orphans — INFO, but the leading indicator

An orphan has no inbound links. By itself that's survivable. The reason it's worth
watching is that orphans are the **early symptom of every other problem**:

- Duplicate pages are orphans that never got reconciled with their twin.
- Abandoned ingests are orphans — the page was written and never linked into the web.
- A page written with one outbound link instead of two is halfway to being an orphan.

Systematic orphaning means pages are being created without being integrated. The fix is
not "add links to the orphans," it's "find out why the ingest step skipped
cross-referencing." Watch the trend, not the count.

## Stale content — INFO, because `updated` is a promise

A page not touched in 90 days may be perfectly correct. The check is not asserting
wrongness; it's asserting that nobody has verified it lately.

The severity depends entirely on domain velocity. In fast-moving competitive
intelligence, a 90-day-old pricing page is very likely wrong. In a wiki of settled
historical or doctrinal facts, it's very likely fine. Calibrate by the domain's change
rate, and consider tightening the threshold for `pricing` and `funding` tagged pages
specifically — those decay fastest.

## Contradictions and `confidence` — WARNING, the hardest to automate

The wiki's core promise is that contradictions have already been flagged. Lint can only
find the ones you explicitly marked (`contested: true`, `contradictions:`), or infer
candidates from pages sharing tags that state conflicting facts.

This is the check that genuinely needs a human or a careful model pass. Its value is
not the count — it's that unmarked contradictions are the failure mode a wiki is *most*
likely to have and *least* likely to notice. A wiki that has never surfaced a single
contradiction is not a contradiction-free wiki; it's an unexamined one.

`confidence: low` markings are the same signal at the claim level: they exist so weak
claims don't silently harden into accepted wiki fact through repetition.

## Page size — INFO, with a hard ceiling

The 200-line threshold is about the 30-second readability promise. A page nobody reads
is a page nobody corrects — errors on a 2,000-line page survive indefinitely because
verifying them costs too much.

Splitting is almost always better than trimming, because the split adds structure
(children with their own links) while trimming removes information.

## Tag discipline — WARNING

Freeform tags decay into noise: `llm`, `LLMs`, `large-language-model`, `large language
model` become four tags for one concept, and tag-based retrieval stops working. The
taxonomy exists so that the tag namespace has an owner.

The rule is procedural, not aesthetic: add the tag to `SCHEMA.md` *first*, then use it.
That one step of friction is what keeps the taxonomy honest, and it costs nothing.

## Directory / type agreement — WARNING

`type:` and the page's directory encode the same fact twice. When they disagree, which
one is true? Nothing in the system can tell, so every downstream consumer — Dataview
queries in Obsidian, index sections, a future agent's search — picks one arbitrarily.

Two encodings of one fact is a bug even when they currently agree, because they will
eventually drift. Lint's job is to catch the drift the moment it appears rather than
after a hundred pages have inherited the wrong assumption.

## Log completeness — the audit trail

Not linted directly, but worth stating: `log.md` is how a human audits what the agent
did while they weren't watching. An unlogged change is indistinguishable from a change
that never happened. When an automated or cron run touches pages, logging it is the
difference between a maintainable wiki and one that mysteriously evolved.

## Reading a lint report

Severity is a triage order, not a quality score:

- **CRITICAL** — the wiki is currently wrong or broken. Fix before continuing.
- **WARNING** — the wiki is drifting toward being wrong. Fix soon, or accept knowingly.
- **INFO** — signals to watch in aggregate. A single one is noise; a rising trend is a
  process problem in how pages are being created.

A healthy wiki does not have zero findings. It has zero CRITICAL findings, a stable or
falling WARNING count, and INFO counts you have consciously decided to ignore.
