---
title: "Llm Wiki — Karpathy's LLM Wiki: build/query interlinked markdown KB"
sidebar_label: "Llm Wiki"
description: "Karpathy's LLM Wiki: build/query interlinked markdown KB"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Llm Wiki

Karpathy's LLM Wiki: build/query interlinked markdown KB.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/research/llm-wiki` |
| Version | `3.1.0` |
| Author | Hermes Agent |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `wiki`, `knowledge-base`, `research`, `notes`, `markdown`, `rag-alternative` |
| Related skills | [`obsidian`](/docs/user-guide/skills/bundled/note-taking/note-taking-obsidian), [`arxiv`](/docs/user-guide/skills/bundled/research/research-arxiv), [`grounded-citations`](/docs/user-guide/skills/bundled/research/research-grounded-citations) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Karpathy's LLM Wiki

Build and maintain a persistent, compounding knowledge base as interlinked markdown files.
Based on [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

Unlike traditional RAG (which rediscovers knowledge from scratch per query), the wiki
compiles knowledge once and keeps it current. Cross-references are already there.
Contradictions have already been flagged. Synthesis reflects everything ingested.

**Division of labor:** The human curates sources and directs analysis. The agent
summarizes, cross-references, files, and maintains consistency.

## When This Skill Activates

Use this skill when the user:
- Asks to create, build, or start a wiki or knowledge base
- Asks to ingest, add, or process a source into their wiki
- Asks a question and an existing wiki is present at the configured path
- Asks to lint, audit, or health-check their wiki
- Asks to split, merge, export, or brief from the wiki
- References their wiki, knowledge base, or "notes" in a research context

## Wiki Location

**Location:** Set via `WIKI_PATH` environment variable (e.g. in `${HERMES_HOME:-~/.hermes}/.env`),
or the equivalent `skills.config.wiki.path` key in `config.yaml`.

If unset, defaults to `~/wiki`.

```bash
WIKI="${WIKI_PATH:-$HOME/wiki}"
```

The wiki is just a directory of markdown files — open it in Obsidian, VS Code, or
any editor. No database, no special tooling required.

**Why two knobs.** `WIKI_PATH` is the environment-variable interface and the one the
skill itself reads. `skills.config.wiki.path` is the config-file interface, and it is
what the WebUI's *LLM Wiki* observability widget reads to decide whether the wiki is
set up at all. Set both — they cost nothing and the widget silently reads `Unavailable`
if only the config key is absent (or vice versa). `hermes config set
skills.config.wiki.path '~/wiki'` writes the config side.

## Architecture: Three Layers

<!-- ascii-guard-ignore -->
```
wiki/
├── SCHEMA.md           # Conventions, structure rules, domain config
├── index.md            # Sectioned content catalog with one-line summaries
├── log.md              # Chronological action log (append-only, rotated yearly)
├── raw/                # Layer 1: Immutable source material
│   ├── articles/       # Web articles, clippings
│   ├── papers/         # PDFs, arxiv papers
│   ├── transcripts/    # Meeting notes, interviews
│   └── assets/         # Images, diagrams referenced by sources
├── entities/           # Layer 2: Entity pages (people, orgs, products, models)
├── concepts/           # Layer 2: Concept/topic pages
├── comparisons/        # Layer 2: Side-by-side analyses
└── queries/            # Layer 2: Filed query results worth keeping
```
<!-- ascii-guard-ignore-end -->

**Layer 1 — Raw Sources:** Immutable. The agent reads but never modifies these.
**Layer 2 — The Wiki:** Agent-owned markdown files. Created, updated, and
cross-referenced by the agent.
**Layer 3 — The Schema:** `SCHEMA.md` defines structure, conventions, and tag taxonomy.

The four Layer-2 directories above are the **canonical minimum**, not a fixed set.
A domain usually needs more — see the next section.

## Page Types: The Extensible Category Model

Four generic directories (`entities/`, `concepts/`, `comparisons/`, `queries/`) are
enough for a hobby wiki and too coarse for a real domain. Competitive intelligence,
for example, needs products and models tracked separately from the companies that
ship them, and regulations tracked separately from the doctrine they constrain.

**The page model is data, not code.** Each wiki declares its own page types in
`SCHEMA.md` under a `## Page Types` heading, in this exact shape:

```markdown
## Page Types

- `entities/` → `entity` — organizations and notable people
- `products/` → `product` — shipped commercial offerings
- `models/` → `model` — foundation models and architectures
- `concepts/` → `concept` — techniques and domain topics
- `regulations/` → `regulation` — rules, statutes, guidance
- `comparisons/` → `comparison` — side-by-side analyses
- `timelines/` → `timeline` — chronological tracking
- `queries/` → `query` — filed query results worth keeping
```

Rules that make this work:

- **One directory per page type.** A page lives in exactly one directory, and that
  directory fixes its `type:` frontmatter value.
- **The mapping is parsed, not guessed.** `scripts/wiki_lint.py` reads this table, so
  adding a row is genuinely all it takes to add a page type. Keep the
  ``- `dir/` → `type` `` shape (a `->` or `:` separator also parses).
- **Adding a page type is a three-step change:** add the row to `SCHEMA.md`, create the
  directory, add the section to `index.md`. Never create the directory first — a page
  directory the schema doesn't declare is invisible to lint and to every future session.
- **Removing a page type** means archiving its pages (see *Archiving*), deleting the
  row, and removing the index section. Do not leave an empty undeclared directory.

Lint enforces directory↔type agreement: a page in `products/` declaring `type: concept`
is flagged. That check is what keeps the model honest over hundreds of edits.

`summary` is a valid `type:` value with no dedicated directory — a summary page is a
short synthesis living in whichever directory its subject belongs to.

Choosing page types for a new wiki: start from what a *question* looks like in the
domain. "How does X compare to Y" needs `comparisons/`. "What changed when" needs
`timelines/`. "Are we allowed to do this" needs `regulations/`. Types should map to
question shapes, not to your org chart.

## Domain Packs

Some domains need more than a page-type table. They need different evidence standards,
different page thresholds, and different mandatory sections — because the cost of a
wrong page is different.

A **domain pack** is the reusable version of that: a reference file with the full
`SCHEMA.md` for a domain, plus the reasoning for its non-obvious choices.

- **`references/domain-pack-health.md`** — health optimization (training, nutrition,
  compounds, peptides, prescriptions, psychedelics, biomarkers, mental health,
  longevity). This is the most opinionated pack, because it is the one where the
  generic defaults are actively dangerous. It adds three non-optional mechanisms:
  **evidence grading** (`evidence: rct | observational | mechanistic | anecdote`),
  **mandatory compound safety blocks** (`Dosing` / `Interactions` /
  `Contraindications` / `High-Risk Signals` on every compound and protocol page), and
  **units on every number** (a bare dose figure is a defect, not a style nit).

Use a pack when the user's domain matches; copy its schema, then adjust. When a domain
has no pack, the generic template is the starting point — but ask what a *wrong* page
would cost, and if the answer is "someone could get hurt," tighten the schema before
the first ingest rather than after.

Write a pack when you have built a schema for a domain that is likely to recur, and
the reasoning behind its thresholds would otherwise be lost.

## Resuming an Existing Wiki (CRITICAL — do this every session)

When the user has an existing wiki, **always orient yourself before doing anything**:

① **Read `SCHEMA.md`** — understand the domain, conventions, page types, and tag taxonomy.
② **Read `index.md`** — learn what pages exist and their summaries.
③ **Scan recent `log.md`** — read the last 20-30 entries to understand recent activity.
④ **Run the stats pass** — one command gives you the shape of the whole wiki:

```bash
python scripts/wiki_lint.py "$WIKI" --summary-only
```

```bash
WIKI="${WIKI_PATH:-$HOME/wiki}"
# Orientation reads at session start
read_file "$WIKI/SCHEMA.md"
read_file "$WIKI/index.md"
read_file "$WIKI/log.md" offset=<last 30 lines>
```

Only after orientation should you ingest, query, or lint. This prevents:
- Creating duplicate pages for entities that already exist
- Missing cross-references to existing content
- Contradicting the schema's conventions
- Using a page type the schema doesn't declare
- Repeating work already logged

For large wikis (100+ pages), also run a quick `search_files` for the topic
at hand before creating anything new.

**Orientation is not skippable when the context is thin.** If the session is a cron
run, a subagent, or a resumed conversation with no wiki context loaded, orientation is
the only thing standing between you and a duplicate pile. Read before you write.

## Initializing a New Wiki

When the user asks to create or start a wiki:

1. Determine the wiki path (`$WIKI_PATH` / `skills.config.wiki.path`, or ask; default `~/wiki`)
2. **Ask what domain the wiki covers — be specific.** The domain drives the page types,
   the tag taxonomy, and the out-of-scope line. A vague answer ("tech stuff") produces a
   wiki that can't apply its own page thresholds.
3. Choose page types that match the domain's question shapes (see *Page Types* above)
   and create those directories plus `raw/`
4. Write `SCHEMA.md` customized to the domain (template below)
5. Write initial `index.md` with one section per declared page type
6. Write initial `log.md` with a creation entry
7. Confirm the wiki is ready, report the derived stats, and suggest first sources to ingest

### SCHEMA.md Template

Adapt to the user's domain. The schema constrains agent behavior and ensures consistency:

```markdown
# Wiki Schema

## Domain
[What this wiki covers — e.g., "AI/ML research", "personal health", "startup intelligence"]
[Add an explicit OUT OF SCOPE line. Wikis die of scope creep more often than of staleness.]

## Conventions
- File names: lowercase, hyphens, no spaces (e.g., `transformer-architecture.md`)
- Every wiki page starts with YAML frontmatter (see below)
- Use `[[wikilinks]]` to link between pages (minimum 2 outbound links per page)
- When updating a page, always bump the `updated` date
- Every new page must be added to `index.md` under the correct section
- Every action must be appended to `log.md`
- **Provenance markers:** On pages that synthesize 3+ sources, append `^[raw/articles/source-file.md]`
  at the end of paragraphs whose claims come from a specific source. This lets a reader trace each
  claim back without re-reading the whole raw file. Optional on single-source pages where the
  `sources:` frontmatter is enough.

## Page Types
- `entities/` → `entity` — organizations and notable people
- `concepts/` → `concept` — techniques, doctrine, domain topics
- `comparisons/` → `comparison` — side-by-side analyses
- `queries/` → `query` — filed query results worth keeping
[Add rows for the page types this domain needs. See the skill's Page Types section.]

## Frontmatter
  ```yaml
  ---
  title: Page Title
  created: YYYY-MM-DD
  updated: YYYY-MM-DD
  type: entity | concept | comparison | query | summary
  tags: [from taxonomy below]
  sources: [raw/articles/source-name.md]
  # Optional quality signals:
  confidence: high | medium | low        # how well-supported the claims are
  contested: true                        # set when the page has unresolved contradictions
  contradictions: [other-page-slug]      # pages this one conflicts with
  ---
  ```

`confidence` and `contested` are optional but recommended for opinion-heavy or fast-moving
topics. Lint surfaces `contested: true` and `confidence: low` pages for review so weak claims
don't silently harden into accepted wiki fact.

### raw/ Frontmatter

Raw sources ALSO get a small frontmatter block so re-ingests can detect drift:

```yaml
---
source_url: https://example.com/article   # original URL, if applicable
ingested: YYYY-MM-DD
sha256: &lt;hex digest of the raw content below the frontmatter>
---
```

The `sha256:` lets a future re-ingest of the same URL skip processing when content is unchanged,
and flag drift when it has changed. Compute over the body only (everything after the closing
`---`), not the frontmatter itself.

## Tag Taxonomy
[Define 10-20 top-level tags for the domain. Add new tags here BEFORE using them.]

Example for AI/ML:
- Models: model, architecture, benchmark, training
- People/Orgs: person, company, lab, open-source
- Techniques: optimization, fine-tuning, inference, alignment, data
- Meta: comparison, timeline, controversy, prediction

Rule: every tag on a page must appear in this taxonomy. If a new tag is needed,
add it here first, then use it. This prevents tag sprawl.

## Page Thresholds
- **Create a page** when an entity/concept appears in 2+ sources OR is central to one source
- **Add to existing page** when a source mentions something already covered
- **DON'T create a page** for passing mentions, minor details, or things outside the domain
- **Split a page** when it exceeds ~200 lines — break into sub-topics with cross-links
- **Archive a page** when its content is fully superseded — move to `_archive/`, remove from index

## Update Policy
When new information conflicts with existing content:
1. Check the dates — newer sources generally supersede older ones
2. If genuinely contradictory, note both positions with dates and sources
3. Mark the contradiction in frontmatter: `contradictions: [page-name]`
4. Flag for user review in the lint report
```

### index.md Template

The index is sectioned by page type. Each entry is one line: wikilink + summary.

```markdown
# Wiki Index

> Content catalog. Every wiki page listed under its type with a one-line summary.
> Read this first to find relevant pages for any query.
> Last updated: YYYY-MM-DD | Total pages: N

## Entities
<!-- Alphabetical within section -->

## Concepts

## Comparisons

## Queries
```

**One section per declared page type.** If `SCHEMA.md` declares `products/`, the index
has a `## Products` section. Lint check ③ compares the filesystem against index entries,
so a missing section is a systematic miss, not a one-off.

**Scaling rule:** When any section exceeds 50 entries, split it into sub-sections
by first letter or sub-domain. When the index exceeds 200 entries total, create
a `_meta/topic-map.md` that groups pages by theme for faster navigation.

### log.md Template

```markdown
# Wiki Log

> Chronological record of all wiki actions. Append-only.
> Format: `## [YYYY-MM-DD] action | subject`
> Actions: ingest, update, query, lint, create, archive, delete, split, merge, export
> When this file exceeds 500 entries, rotate: rename to log-YYYY.md, start fresh.

## [YYYY-MM-DD] create | Wiki initialized
- Domain: [domain]
- Structure created with SCHEMA.md, index.md, log.md
```

## Core Operations

### 1. Ingest

When the user provides a source (URL, file, paste), integrate it into the wiki:

① **Capture the raw source:**
   - URL → use `web_extract` to get markdown, save to `raw/articles/`
   - PDF → use `web_extract` (handles PDFs), save to `raw/papers/`
   - Pasted text → save to appropriate `raw/` subdirectory
   - Name the file descriptively: `raw/articles/karpathy-llm-wiki-2026.md`
   - **Add raw frontmatter** (`source_url`, `ingested`, `sha256` of the body).
     On re-ingest of the same URL: recompute the sha256, compare to the stored value —
     skip if identical, flag drift and update if different. This is cheap enough to
     do on every re-ingest and catches silent source changes.

② **Discuss takeaways** with the user — what's interesting, what matters for
   the domain. (Skip this in automated/cron contexts — proceed directly.)

③ **Check what already exists** — search index.md and use `search_files` to find
   existing pages for mentioned entities/concepts. This is the difference between
   a growing wiki and a pile of duplicates.

④ **Write or update wiki pages:**
   - **New entities/concepts:** Create pages only if they meet the Page Thresholds
     in SCHEMA.md (2+ source mentions, or central to one source)
   - **Existing pages:** Add new information, update facts, bump `updated` date.
     When new info contradicts existing content, follow the Update Policy.
   - **Pick the right directory:** the page type is determined by which directory it
     goes in, so decide the type *before* writing. A fact that fits nowhere may be
     evidence you need a new declared page type — propose it rather than dumping it
     into `concepts/`.
   - **Cross-reference:** Every new or updated page must link to at least 2 other
     pages via `[[wikilinks]]`. Check that existing pages link back.
   - **Tags:** Only use tags from the taxonomy in SCHEMA.md
   - **Provenance:** On pages synthesizing 3+ sources, append `^[raw/articles/source.md]`
     markers to paragraphs whose claims trace to a specific source.
   - **Confidence:** For opinion-heavy, fast-moving, or single-source claims, set
     `confidence: medium` or `low` in frontmatter. Don't mark `high` unless the
     claim is well-supported across multiple sources.

⑤ **Update navigation:**
   - Add new pages to `index.md` under the correct section, alphabetically
   - Update the "Total pages" count and "Last updated" date in index header
   - Append to `log.md`: `## [YYYY-MM-DD] ingest | Source Title`
   - List every file created or updated in the log entry
   - If a new page type directory was involved, confirm its index section exists

⑥ **Report what changed** — list every file created or updated to the user.

A single source can trigger updates across 5-15 wiki pages. This is normal
and desired — it's the compounding effect.

### 2. Query

When the user asks a question about the wiki's domain:

① **Read `index.md`** to identify relevant pages.
② **For wikis with 100+ pages**, also `search_files` across all `.md` files
   for key terms — the index alone may miss relevant content.
③ **Read the relevant pages** using `read_file`.
④ **Synthesize an answer** from the compiled knowledge. Cite the wiki pages
   you drew from: "Based on [[page-a]] and [[page-b]]..."
⑤ **File valuable answers back** — if the answer is a substantial comparison,
   deep dive, or novel synthesis, create a page in the matching directory
   (`comparisons/`, `queries/`, or a `timelines/` entry).
   Don't file trivial lookups — only answers that would be painful to re-derive.
⑥ **Update log.md** with the query and whether it was filed.

### 3. Lint

Run the bundled script — it implements every check below, in one pass:

```bash
python scripts/wiki_lint.py "$WIKI"              # full report, grouped by severity
python scripts/wiki_lint.py "$WIKI" --summary-only   # stats only
python scripts/wiki_lint.py "$WIKI" --json        # machine-readable
```

Exit code is `0` when no critical issues exist, `1` when they do — usable directly as
a CI or cron gate. Stdlib-only, no dependencies.

What it checks, and how to act on each:

| # | Check | Severity | Action |
|---|---|---|---|
| ① | **Orphan pages** — no inbound `[[wikilinks]]` | INFO | Add inbound links from related pages; a true orphan is invisible |
| ② | **Broken wikilinks** — `[[link]]` to a non-existent page | CRITICAL | Fix the target or create the page |
| ③ | **Index completeness** — page absent from `index.md` | WARNING | Add it under its type section |
| ④ | **Frontmatter validation** — required fields, tags in taxonomy | CRITICAL | Fill the field; add new tags to SCHEMA.md first |
| ⑤ | **Stale content** — `updated` > 90 days old | INFO | Re-verify against the newest source, or accept and move on |
| ⑥ | **Contradictions** — `contested: true` / `contradictions:` | WARNING | Surface both positions to the user with dates |
| ⑦ | **Quality signals** — `confidence: low`, single-source unrated | INFO | Corroborate or demote |
| ⑧ | **Source drift** — `raw/` sha256 mismatch | CRITICAL | The source changed under you; re-ingest or restore |
| ⑨ | **Page size** — over 200 lines | INFO | Split (see *Splitting a Page*) |
| ⑩ | **Tag audit** — tags not in the taxonomy | WARNING | Add to taxonomy or correct the page |
| ⑪ | **Log rotation** — > 500 entries | INFO | Rotate to `log-YYYY.md` |
| ⑫ | **Page types** — `type:` disagrees with its directory | WARNING | Move the page or fix the frontmatter |

Two behaviours worth knowing, because both are deliberate:

- **An empty taxonomy disables the tag checks, it does not fail them.** If `SCHEMA.md`
  declares no tags, the script cannot know what "wrong" means and stays quiet rather
  than flagging every tag on every page. If you expected tag warnings and got none,
  the taxonomy probably failed to parse — check that the tags are under a
  `## Tag Taxonomy` heading.
- **Declared page types come from SCHEMA.md.** A page directory the schema doesn't
  declare is not linted as a wiki page at all. Missing pages in the stats output is
  the usual symptom.

After a lint pass:
- **Report findings** with specific file paths and suggested actions, grouped by
  severity (broken links > source drift > orphans > contested pages > stale content > style)
- **Append to log.md:** `## [YYYY-MM-DD] lint | N issues found`, naming the top fixes

For the reasoning behind the checks — why orphan detection matters more than it looks,
why source drift is a correctness bug and not a hygiene nit — see
`references/lint-rationale.md`.

### 4. Splitting a Page

Lint flags pages over ~200 lines. Splitting preserves the compounding property — a
3,000-line page is a wiki the wiki can't link into.

1. **Identify the seams.** Usually one of: distinct sub-topics, distinct time periods,
   or distinct entities that were merged by accident.
2. **Create the child pages** in the appropriate directories, each with full frontmatter
   and at least 2 outbound `[[wikilinks]]`.
3. **Leave the parent as a hub.** Keep the overview, the definition, and a short
   annotated link list to the children. Do not empty it — the parent's inbound links
   must keep resolving.
4. **Move the detail**, don't copy it. Duplicated prose diverges and then contradicts.
5. **Update `index.md`** — add every child, keep the parent entry.
6. **Log it:** `## [YYYY-MM-DD] split | Parent Page → 3 children`

### 5. Merging Pages

The inverse, and the more common cleanup: two thin pages covering the same ground.

1. **Confirm the overlap** by reading both — the same *subject*, not merely adjacent topics.
2. **Pick the surviving slug.** Prefer the one with more inbound `[[wikilinks]]`; the
   other becomes a redirect stub or is archived.
3. **Merge content**, reconciling any contradictions explicitly (they are usually the
   signal that one page was simply older).
4. **Repoint every inbound link** — `search_files "\[\[old-page\]\]"` finds them all.
   A merge that leaves broken inbound links is worse than the duplication was.
5. **Update `index.md`**, remove the dead entry.
6. **Log it:** `## [YYYY-MM-DD] merge | A + B → C`

### 6. Briefing and Export

The wiki is a source. Common downstream shapes:

- **Briefing doc** — synthesize a dated markdown brief from N wiki pages on a theme.
  Write it to `queries/` with `type: query` so it compounds, or out to a file if the
  user wants it as a deliverable. Cite pages inline as `[[wikilink]]`.
- **Static site** — the directories render in MkDocs or Docusaurus as-is; `[[wikilinks]]`
  need rewriting to relative paths, and `raw/` should be excluded from the nav.
- **Handoff bundle** — a subset of pages plus their `sources:` raw files, for someone
  outside the wiki. Copy raw files alongside so provenance survives the trip.

When the export quotes outside facts, use the `grounded-citations` skill for the
citation ledger — the wiki's `sources:` frontmatter is the input, not the output format.

## Automation: Scheduled Maintenance

A wiki that isn't maintained decays quietly. Two cron shapes are worth setting:

**Nightly re-ingest + drift scan.** Re-fetch every `raw/` file with a `source_url`,
recompute sha256, and surface only what changed:

```bash
python scripts/wiki_lint.py "$WIKI" --json | python3 -c "
import json,sys
d=json.load(sys.stdin)
for i in d['issues']:
    if i['check'] in ('source-drift','broken-wikilinks'):
        print(i['severity'], i['path'], i['message'])
"
```

**Weekly lint digest.** `--summary-only` plus the issue counts, delivered to a chat
surface. Route it so the output is a *diff against last week*, not a full re-report —
use the cron `continuity` flag so the job sees its own previous output and can report
only changes.

Guidance that keeps automated runs from making things worse:
- **Never let a scheduled run create entity pages from scratch.** Heuristic page
  creation is how a wiki fills with stubs. Scheduled runs should update existing pages
  and *report* candidates for new pages.
- **Skip the takeaway discussion step** (Ingest ②) in unattended contexts.
- **Cap the blast radius.** If a run would touch more than ~10 pages, have it report and
  stop rather than mass-update. See the *Ask before mass-updating* pitfall.
- **Log every automated run** so the human can audit what changed while they slept.

## Multiple Wikis

One wiki per domain. When the user wants a second, don't nest — sibling directories,
each with its own `SCHEMA.md`, `index.md`, and `log.md`:

```bash
export WIKI_PATH=~/wiki            # default wiki
export WIKI_LEGAL=~/wikis/legal    # domain-specific wikis
export WIKI_HEALTH=~/wikis/health
```

`WIKI_PATH` addresses the default; other wikis are addressed by explicit path. The
WebUI widget observes the configured wiki only, so make the configured one the wiki
the user actually works in most.

**Cross-wiki linking is a trap.** `[[wikilinks]]` resolve within one vault; a link
across wikis silently breaks in Obsidian. If two domains genuinely cross-reference
heavily, that is evidence they are one wiki with two tag families.

## Large Wikis: Context Discipline

Past a few hundred pages, the failure mode stops being "missing knowledge" and becomes
"agent reads 40 files and answers worse." Rules:

- **Index first, always.** `index.md` is the retrieval layer. Read it before reading pages.
- **Trust the summaries.** The one-line index entry is usually enough to decide relevance.
  Read a page only when its summary says you must.
- **Budget your reads.** For a broad query, cap at ~10 page reads; if you need more, the
  index summaries are too thin — improve them instead.
- **Prefer `search_files` over reading directories.** `search_files "term" path="$WIKI"
  file_glob="*.md"` beats opening files one by one.
- **Subagents for wide synthesis.** Delegate "read these 30 pages and synthesize" to a
  subagent, which absorbs the context cost and returns only the synthesis.

## Working with the Wiki

### Searching

```bash
# Find pages by content
search_files "transformer" path="$WIKI" file_glob="*.md"

# Find pages by filename
search_files "*.md" target="files" path="$WIKI"

# Find pages by tag
search_files "tags:.*alignment" path="$WIKI" file_glob="*.md"

# Find every inbound link to a page (before a merge or archive)
search_files "\[\[old-page\]\]" path="$WIKI" file_glob="*.md"

# Recent activity
read_file "$WIKI/log.md" offset=<last 20 lines>
```

### Bulk Ingest

When ingesting multiple sources at once, batch the updates:
1. Read all sources first
2. Identify all entities and concepts across all sources
3. Check existing pages for all of them (one search pass, not N)
4. Create/update pages in one pass (avoids redundant updates)
5. Update index.md once at the end
6. Write a single log entry covering the batch

### Archiving

When content is fully superseded or the domain scope changes:
1. Create `_archive/` directory if it doesn't exist
2. Move the page to `_archive/` with its original path (e.g., `_archive/entities/old-page.md`)
3. Remove from `index.md`
4. Update any pages that linked to it — replace wikilink with plain text + "(archived)"
5. Log the archive action

`_archive/` is excluded from lint, so archived pages don't generate orphan and
broken-link noise. That also means nothing will remind you they exist — the log is the
only index of what was archived.

### Obsidian Integration

The wiki directory works as an Obsidian vault out of the box:
- `[[wikilinks]]` render as clickable links
- Graph View visualizes the knowledge network
- YAML frontmatter powers Dataview queries
- The `raw/assets/` folder holds images referenced via `![[image.png]]`

For best results:
- Set Obsidian's attachment folder to `raw/assets/`
- Enable "Wikilinks" in Obsidian settings (usually on by default)
- Install Dataview plugin for queries like `TABLE tags FROM "entities" WHERE contains(tags, "company")`

If using the Obsidian skill alongside this one, set `OBSIDIAN_VAULT_PATH` to the
same directory as the wiki path.

Graph View is the fastest way to see a lint problem before lint finds it: orphans and
clusters show up as disconnected islands.

### Obsidian Headless (servers and headless machines)

On machines without a display, use `obsidian-headless` instead of the desktop app.
It syncs vaults via Obsidian Sync without a GUI — perfect for agents running on
servers that write to the wiki while Obsidian desktop reads it on another device.

**Setup:**
```bash
# Requires Node.js 22+
npm install -g obsidian-headless

# Login (requires Obsidian account with Sync subscription)
ob login --email <email> --password '<password>'

# Create a remote vault for the wiki
ob sync-create-remote --name "LLM Wiki"

# Connect the wiki directory to the vault
cd ~/wiki
ob sync-setup --vault "<vault-id>"

# Initial sync
ob sync

# Continuous sync (foreground — use systemd for background)
ob sync --continuous
```

**Continuous background sync via systemd:**
```ini
# ~/.config/systemd/user/obsidian-wiki-sync.service
[Unit]
Description=Obsidian LLM Wiki Sync
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/path/to/ob sync --continuous
WorkingDirectory=%h/wiki
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now obsidian-wiki-sync
# Enable linger so sync survives logout:
sudo loginctl enable-linger $USER
```

This lets the agent write to `~/wiki` on a server while you browse the same
vault in Obsidian on your laptop/phone — changes appear within seconds.

## Pitfalls

- **Never modify files in `raw/`** — sources are immutable. Corrections go in wiki pages.
- **Always orient first** — read SCHEMA + index + recent log before any operation in a new session.
  Skipping this causes duplicates and missed cross-references.
- **Always update index.md and log.md** — skipping this makes the wiki degrade. These are the
  navigational backbone.
- **Don't create a directory the schema doesn't declare** — undeclared page directories are
  invisible to lint and to every future session. Add the `## Page Types` row first.
- **Don't create pages for passing mentions** — follow the Page Thresholds in SCHEMA.md. A name
  appearing once in a footnote doesn't warrant an entity page.
- **Don't create pages without cross-references** — isolated pages are invisible. Every page must
  link to at least 2 other pages.
- **Frontmatter is required** — it enables search, filtering, and staleness detection.
- **Tags must come from the taxonomy** — freeform tags decay into noise. Add new tags to SCHEMA.md
  first, then use them.
- **Keep pages scannable** — a wiki page should be readable in 30 seconds. Split pages over
  200 lines. Move detailed analysis to dedicated deep-dive pages.
- **Ask before mass-updating** — if an ingest would touch 10+ existing pages, confirm
  the scope with the user first.
- **Rotate the log** — when log.md exceeds 500 entries, rename it `log-YYYY.md` and start fresh.
  The agent should check log size during lint.
- **Handle contradictions explicitly** — don't silently overwrite. Note both claims with dates,
  mark in frontmatter, flag for user review.
- **An empty taxonomy check is silent, not green** — if tag warnings vanish, suspect the
  taxonomy stopped parsing rather than that the tags got clean.

## Related Tools

[llm-wiki-compiler](https://github.com/atomicmemory/llm-wiki-compiler) is a Node.js CLI that
compiles sources into a concept wiki with the same Karpathy inspiration. It's Obsidian-compatible,
so users who want a scheduled/CLI-driven compile pipeline can point it at the same vault this
skill maintains. Trade-offs: it owns page generation (replaces the agent's judgment on page
creation) and is tuned for small corpora. Use this skill when you want agent-in-the-loop curation;
use llmwiki when you want batch compile of a source directory.

Pair with:
- **`obsidian`** — filesystem-first vault operations against the same directory.
- **`grounded-citations`** — when wiki content flows into a cited deliverable.
- **`arxiv`** — a natural `raw/papers/` source for research wikis.
