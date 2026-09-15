# Domain Pack: Health Optimization

A worked example of adapting the LLM Wiki to a high-stakes personal domain. Copy this
when a user wants a wiki for training, nutrition, compounds, biomarkers, mental health,
or longevity.

Health is the domain where the skill's generic defaults are **most dangerous to leave
unmodified**. Three changes are not optional: evidence grading, mandatory safety blocks,
and units on every number. Everything else is tuning.

## Why health needs its own schema

The generic wiki treats all claims as roughly equal and lets prose carry the nuance.
In health, that flattens a well-powered RCT and a supplement vendor's blog post into
the same confident sentence. A wiki that does that is worse than no wiki, because it
launders weak claims into authoritative-looking ones.

The fix is structural, not stylistic: make evidence quality a field, not a vibe.

## Directory layout

```bash
WIKI=~/wikis/health
mkdir -p "$WIKI"/{entities,compounds,protocols,training,nutrition,biomarkers,conditions,concepts,comparisons,timelines,queries}
mkdir -p "$WIKI"/raw/{articles,papers,transcripts,assets}
```

Keep it a **sibling** of any other wiki, never a section inside one. Health pages have
different page thresholds, a different taxonomy, and a different safety posture than
(nominally) every other domain.

## Page types

```markdown
## Page Types

- `entities/` → `entity` — clinicians, researchers, labs, clinics, vendors, authors
- `compounds/` → `compound` — supplements, peptides, prescriptions, psychedelics, hormones
- `protocols/` → `protocol` — dosing regimens, cycles, stacks, tapering
- `training/` → `training` — programs, splits, progression schemes, movements, recovery
- `nutrition/` → `nutrition` — dietary patterns, macros, foods, fasting, hydration
- `biomarkers/` → `biomarker` — blood-work analytes, reference ranges, interpretation
- `conditions/` → `condition` — health states, goals, symptoms, risk factors
- `concepts/` → `concept` — mechanisms (mTOR, half-life, tolerance, insulin sensitivity)
- `comparisons/` → `comparison` — side-by-side analyses
- `timelines/` → `timeline` — protocol history, lab trends over time
- `queries/` → `query` — filed query results worth keeping
```

`training/` and `nutrition/` are split deliberately. Lumping them into a generic
`protocols/` recreates the "too coarse" problem: training programming and dietary
patterns each accumulate enough pages to need their own index section and taxonomy.

## The three non-optional additions

### 1. Evidence grading

Add to frontmatter, **required** on `compound`, `protocol`, `training`, and `nutrition`
pages:

```yaml
evidence: rct | observational | mechanistic | anecdote | mixed
```

`evidence` records the best supporting tier; `confidence` records how well it transfers
to the claim being made. They are independent axes — a solid RCT in an unlike
population is `evidence: rct` with `confidence: medium`. Cell and animal work is
`mechanistic` and must never carry `confidence: high` for a human outcome.

Vendor, supplement-seller, and forum sources cap at `confidence: low` unless an
independent human trial corroborates them.

### 2. The compound safety block

Every `compound` page and every `protocol` page carries these four headings, always:

```markdown
## Dosing
## Interactions
## Contraindications & Cautions
## High-Risk Signals
```

When something is genuinely low-risk, write one honest line under each heading rather
than deleting it. **The empty section is what makes a wiki page dangerous later** — a
future reader cannot distinguish "no interactions" from "nobody checked."

`High-Risk Signals` should state plainly when the answer is stop and seek care.

### 3. Units everywhere

Every number in this domain carries units and a denominator: `5 g/day`, `2 mg`,
`150 mg/dL`, `3×/week`, `0.3 mg before sleep`. A bare number is a **defect** — dosing
figures are precisely what gets copied out of a wiki and acted on.

## Tag taxonomy

```markdown
## Tag Taxonomy

**Substances**
- `supplement` — vitamins, minerals, botanicals, amino acids, OTC
- `peptide` — BPC-157, TB-500, semaglutide-class, GH secretagogues
- `prescription` — Rx pharmaceuticals
- `psychedelic` — psilocybin, LSD, MDMA, ketamine, DMT
- `hormone` — testosterone, thyroid, estrogen, cortisol, hGH
- `nootropic` — cognition-targeted compounds
- `performance-enhancing` — ergogenics and PEDs, including legality-sensitive

**Training**
- `strength` — maximal force, low-rep work
- `hypertrophy` — muscle growth
- `endurance` — aerobic and VO2max
- `mobility` — range of motion, joint health
- `recovery` — sleep, deload, tissue repair
- `injury` — pathology, rehab, prevention

**Nutrition**
- `diet-pattern` — keto, Mediterranean, carnivore, plant-based
- `macronutrient` — protein, fat, carbohydrate targets
- `fasting` — intermittent, extended, time-restricted
- `food` — specific foods and food groups
- `hydration` — fluid and electrolytes
- `alcohol` — ethanol and its health effects

**Measurement**
- `bloodwork` — serum/plasma analytes
- `reference-range` — normal vs optimal, assay variation
- `wearable` — HRV, sleep staging, CGM, training load
- `imaging` — DEXA, MRI, calcium scoring

**Health state**
- `metabolic` — insulin sensitivity, lipids, body composition
- `cardiovascular` — BP, apoB, LDL, risk
- `mental-health` — mood, anxiety, depression, ADHD
- `sleep` — architecture, latency, apnea
- `cognition` — memory, focus, executive function
- `hormonal` — endocrine axes and their disruption
- `gut-health` — microbiome, digestion, permeability
- `sexual-health` — libido, function, fertility
- `longevity` — healthspan, all-cause risk, aging biology
- `inflammation` — acute and chronic
- `pain` — acute and chronic pain states

**Evidence / Meta**
- `safety` — adverse effects, risk
- `interaction` — compound-compound and compound-drug
- `dosing` — dose-response, timing, route
- `contraindication` — explicit exclusions
- `regulatory` — legality, scheduling, sport bans
- `comparison` — side-by-side analyses
- `timeline` — chronological tracking
- `controversy` — disputed or contested claims
- `prediction` — forward-looking claims, dated so they can be scored later
```

## Page thresholds, tightened

Generic thresholds are too permissive here. Use:

- A **compound** gets a page when it appears in 2+ independent sources **and** has at
  least one human study or a well-documented safety profile. A supplement existing only
  in vendor marketing does not get a page — it gets a line on the relevant `conditions`
  page, flagged `evidence: anecdote`.
- A **biomarker** gets a page when it has established clinical interpretation, not merely
  a wellness-blog interpretation.
- **n=1 self-experiments** live on a `timeline` page, always `evidence: anecdote`, and
  never migrate into a compound page as though they were evidence.

## Update policy

Priority order for conflicts:

1. **A human outcome trial outranks a mechanism.** When a plausible mechanism says X and
   an RCT says not-X, the page records not-X with the mechanism noted as unresolved.
   Mechanism-first reasoning is the dominant failure mode in this domain.
2. **A vendor source never supersedes an independent one**, regardless of recency.
3. **Regulatory and safety status** is worth updating even when the underlying evidence
   hasn't moved — note the change with a date.
4. **Never delete a safety concern on one contrary source.** Downgrade its prominence,
   keep it recorded, note why.

## Standing framing

The wiki is a **knowledge base, not a treatment plan**. Pages summarize what the
evidence says; they do not prescribe for the reader. Say this once in the schema's
Domain section so every future session inherits it, and keep acute medical care and
individual diagnosis explicitly out of scope.

Nothing in the wiki substitutes for a clinician who knows the actual patient — and for
anything carrying real risk (psychedelics, hormones, prescription interactions), that
sentence should be on the page itself, not only in the schema.
