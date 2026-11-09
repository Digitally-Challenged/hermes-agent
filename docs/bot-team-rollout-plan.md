# Hermes bot team rollout plan

Date: 2026-11-08. Status: proposed; implementation has not started.

Build a small, measurable specialist workflow before introducing external memory,
automatic model routing, or autonomous maintenance. Start with an orchestrator,
coder, and critic. Expand only when representative tasks demonstrate a benefit.
The target is reliable accepted work at a lower total cost, with explicit evidence
for isolation, completion, and recovery.

This plan authorizes no installation, live configuration change, provider upload,
paid experiment, service restart, deployment, or scheduled job. Those belong to a
subsequent implementation effort. Keep credentials, actual configuration exports,
user memories, and client documents outside this repository.

## Architecture and implementation boundaries

- Use persistent Hermes profiles for roles that need their own settings, skills,
  credentials, and long-term state. Use temporary delegated children for bounded
  tasks. A fresh conversation alone does not create a private persistent profile.
- Prefer existing delegation-provider and Kanban review mechanisms. Use a
  standalone plugin for a concrete missing capability; change core only after a
  reproduction proves the generic extension surface is insufficient.
- Keep the installed runtime on a supported stable release. Develop and test in
  a separate task worktree; do not patch the live runtime checkout.
- Resolve profiles and secrets through Hermes's supported scope mechanisms. Test
  real imports and discovery with two temporary homes in A → B → A order.
- Pin third-party plugin and skill revisions. Let Hermes PM own changes to Hermes
  environments; manage a separate OpenViking server environment independently.
- Keep system prompts and tool schemas stable throughout a conversation. Apply
  saved skills, role, memory-provider, and delegation-schema changes in new sessions.
  Do not rewrite earlier messages to accommodate routing or review.

## Sequence and promotion gates

Each phase produces evidence and a rollback path. A failed gate leaves the
previous working phase in place. Planning numbers below are proposed acceptance
thresholds, not claims of measured performance or spending authorization.

| Phase | Deliverable | Gate before proceeding |
| --- | --- | --- |
| 0 | Baseline tasks, fixed rubric, budgets, recovery inventory | Repeatable measurements and recorded operating limits |
| 1 | Orchestrator, coder, critic pilot | Exact-artifact review, bounded execution, successful recovery |
| 2 | Isolated OpenViking memory pilot | Access separation, correct retrieval, correction, restore |
| 3 | Voyage and document-ingestion comparison | Grounded extraction and measured retrieval improvement |
| 4 | Model and effort routing experiment | Provider compatibility and lower total cost without quality loss |
| 5 | Additional specialists | Demonstrated benefit for each added role |
| 6 | Nightly candidate improvement | Independent evaluation and review before promotion |

### Phase 0 Establish the baseline

1. Revalidate the actual installed version, active surfaces, provider routes,
   delegation backend, toolsets, existing profiles, and concurrent work. The
   development checkout and live runtime may have different capabilities.
2. Keep a private recovery inventory of configuration, plugin pins, and service
   bindings. Verify the existing backup mechanism without copying credentials into
   task logs or Git. Record how to restore the previous profile selection.
3. Prepare 24 synthetic or public development tasks: six coding changes, four bug
   fixes, four research/source-selection tasks, four UI tasks, and six document or
   retrieval tasks. Reserve eight additional balanced cases as a held-out set.
   Include ambiguous requests and tasks requiring an honest abstention.
4. Freeze a rubric before trials: functional correctness, source grounding,
   completeness, material defects, and unnecessary actions. Use deterministic
   checks where possible; human review settles disputed subjective results.
5. Measure the existing workflow: accepted-task rate, material defects, total
   provider spend, cached/uncached tokens, reasoning and output usage where
   reported, latency, retries, and human correction time. Count every specialist,
   critic, extraction, embedding, and routing call in the candidate's cost.
6. Set a total pilot spend ceiling, per-task ceiling, wall-time ceiling, and a
   maximum of two critic-driven rework cycles before any paid trial. Keep child
   concurrency at three initially and enforce a shared budget across descendants;
   a per-parent setting alone is not a global concurrency or spending limit.

Exit: the baseline can be reproduced, budgets are recorded, and the trial data is
approved for the selected providers. Preserve the eight held-out cases from tuning.

### Phase 1 Prove the three-role review workflow

Create fresh pilot profiles rather than cloning the full default identity and
credentials. Configure only the capabilities each role needs.

| Role | Responsibility | Initial authority |
| --- | --- | --- |
| Orchestrator | Define acceptance criteria, dispatch work, track unresolved findings | Route tasks and read evidence; no deployment or credential administration |
| Coder | Implement in an isolated worktree and run relevant native checks | Edit the assigned checkout; no production credentials |
| Critic | Independently inspect requirements, exact changes, and test evidence | Read artifacts; execute checks only in an isolated writable scratch environment |

Keep the baseline model route fixed so this phase measures orchestration rather
than simultaneous changes to memory and model choice. Use Kanban's durable review
and change-request transitions for work that needs a review lifecycle; do not rely
on a bot-message acknowledgement or completion notification as acceptance.

The completion contract must associate the task, implementation run, commit SHA or
artifact hash, test evidence, and critic verdict. Any artifact modification makes
the prior verdict stale. Missing, timed-out, malformed, or stale reviews leave work
unaccepted. Distinguish implementation complete, review accepted, and deployed.
Prove that implementers cannot mark a review-required task accepted through another
supported completion surface. Existing review transitions are a starting point,
not proof that mandatory review is enforced on every completion path.

Begin with flat delegation. Trial `max_spawn_depth: 2` only when the critic has a
specific need to delegate a check. Keep `orchestrator_enabled: true`, restrict the
critic's permitted targets, and retain the shared budgets. In the inspected runtime,
delegation capability is derived from remaining depth and the enable switch; a
role name in SOUL.md is not the enforcement mechanism. Do not disable bot loop
guards to implement task orchestration.

Prove these behaviors using real profile routing and temporary homes:

- Each role gets its assigned tools and scoped credentials; profile B never uses
  profile A's credentials after an A → B → A switch.
- A critic rejects a planted functional defect despite the coder's claim of success.
- A stale verdict cannot accept a changed artifact; a missing verdict cannot accept
  a task; passing evidence applies to the exact reviewed version.
- Depth, concurrency, time, cost, and rework bounds hold; cancellation stops owned
  children and leaves an inspectable incomplete result.
- Restart during review preserves task identity and evidence without repeating an
  external write. UI acknowledgements distinguish queued work from settled results.

Exit: zero acceptance-bypass failures in the challenge cases, no critical defects
in accepted pilot outputs, and no net reduction in accepted-task count versus the
baseline. Evaluate both cost and human correction effort; do not expand a workflow
whose extra review cost produces no measurable benefit.

Rollback: stop new pilot dispatch, drain or cancel owned pilot work deliberately,
and resume the baseline route. Preserve artifacts and unresolved reviews. Do not
stop unrelated profiles or replace existing sessions.

### Phase 2 Pilot OpenViking with isolated identities

Install the reviewed catalog plugin only in pilot profiles. Use a separately managed,
version-pinned local OpenViking server for the custom embedding/VLM configuration.
Bind it to loopback initially and use authenticated, separately scoped users and
keys for private role memory. Do not give bots the server's administrative key.
Define shared project knowledge as an explicit additional access policy; verify
the server can enforce it before enabling sharing.

Treat recalled memories as source-linked data, not instructions that grant tool or
credential authority. Preserve provenance, source timestamp, owner, and correction
history for retained facts. Keep authoritative documents and backups independently
of extracted memories. An extraction submission is not proof of durable retrieval.

Use 20 synthetic facts, five conflicting updates, and five irrelevant distractors:

- Retrieve at least 18 of the 20 answerable facts after process/server restart.
- Return the current fact for all five corrections, with source attribution; retain
  enough history to explain supersession without treating old facts as current.
- Deny all cross-user direct reads, search, browse, and writes in the access matrix.
  Test explicit tools as well as automatic recall: peer recall filters are not ACLs.
- Demonstrate deletion behavior for stored facts and derived indexes, document
  retention in backups, and prevent deleted source material from being re-ingested.
- Exercise server outage, delayed extraction, retry/recovery, and an actual backup
  restore. Report uncaptured turns or pending work accurately.
- Seed an instruction-like memory and prove it cannot authorize an otherwise
  forbidden operation or access another role's data.

Exit: retrieval target met and zero access-boundary failures. Record restore time,
known capture gaps, retention policy, and the approved provider data flows.

Rollback: disable the pilot memory provider for new sessions and return to baseline
memory. Stop the pilot server separately after its writers drain; plugin removal
alone does not stop it. Preserve its data until retention decisions are made.

### Phase 3 Compare Voyage and prove document ingestion

Configure OpenViking's server-side embedding and VLM settings explicitly; Hermes's
auxiliary vision selection is a separate configuration. Verify the selected VLM
actually accepts images through the intended provider API. Start with an already
available vision-capable model before adding another provider.

Compare `voyage-4-large` with the Phase 2 embedding baseline on the same retrieval
questions, corpus, chunking, and dimensions appropriate to each model. Use separate
indexes when vector spaces differ. Confirm account access and current pricing;
do not assume unused free tokens or a particular lifetime for the allowance.

Create 12 known-answer fixtures: three photos, three scanned PDFs, two text PDFs,
two Word documents, and two spreadsheets. Cover small text, tables, numbers,
multi-page references, ambiguous imagery, and an unanswerable detail. Prefer native
parsing for machine-readable text, formulas, and workbook structure; use vision
where it adds information.

Retain originals and source hashes. Store extracted text separately from generated
descriptions, with page/sheet/location references and the extraction model/version.
Flag uncertainty rather than inventing content. A Markdown description is a
derived artifact, not the authoritative document.

Exit: all predeclared critical strings, numbers, and formulas are preserved; every
answer has a valid source location; no unsupported critical fact is accepted.
Compare retrieval scores, ingestion/query latency, and total costs. Adopt Voyage
only if the measured result justifies it. Do not migrate existing memory indexes
until reindexing and rollback have been exercised.

Rollback: retain the previous index and model configuration. Switch new sessions
back without overwriting originals; identify and invalidate incorrect derivatives.

### Phase 4 Evaluate routing before it controls requests

Separate three decisions: which specialist owns a task, which provider/model serves
it, and which supported reasoning effort applies. Use Hermes's delegation-provider
interface first. The linked JEV effort router is Ollama-Cloud-specific; its current
provider allowlist does not implement routing for an OpenRouter or Bedrock setup.

If JEV remains useful, implement or select a standalone adapter against the existing
plugin surface. Validate model identifiers, API modes, provider-specific effort
values, scoped secrets, timeouts, fallback behavior, and model capability needs.
Send only the approved task summary to the decision service. Log decision category,
route, effort, cost, and fallback reason without raw private conversation content.

Run in shadow mode first: record proposed routes while the baseline serves tasks.
Evaluate the frozen development set, then the held-out set without retuning on it.
Trial task/session model affinity before per-turn model switching; measure cache
effects. Keep each tool loop on one validated route. Routing failures retain the
known working route and never bypass required review or tool restrictions.

Exit: all provider/API/effort compatibility cases pass; no critical defect or
reduction in accepted-task count on either set; at least 15% lower total cost per
accepted task; p95 latency no more than 20% worse than the fixed-route candidate.
These small sets support a pilot decision, not a broad quality guarantee. If the
gate fails, retain fixed routing and revise or stop the experiment.

Rollback: disable request rewriting and return to the fixed profile route. Keep
the routing evidence for comparison; do not rewrite historical conversations.

### Phase 5 Add specialists only for demonstrated demand

Add one role at a time and compare the tasks that role is intended to improve.
Keep simple tasks on the direct path; there is no mandatory nine-role waterfall.

- Researcher: add when library/provider selection needs repeated source-backed
  comparisons. Package health is an input alongside suitability and maintenance.
- Designer: add for substantive UI work. Pin Hallmark if selected; verify actual
  rendered behavior at 320, 375, 768, and 1440 pixels and test relevant interactions,
  accessibility, and real content. A gate count is not a usability result.
- Security: add with a defined threat model and reproducible boundary tests.
  Semgrep/gitleaks results and a prompt-based review do not establish containment.
- Scraper: evaluate Scrapling on authorized extraction targets. Use isolated browser
  sessions and explicit login/credential policy; keep user browser sessions separate.
- Docsmith: validate outputs in native readers or renderers. Recalculate workbook
  formulas, check charts and layout, and distinguish editable source from exports.
- Bugbounty: create only for a concrete authorized scope, with dedicated sandbox,
  target allowlist, credentials, rate limits, and evidence retention. Keep it outside
  ordinary automatic routing and without production authority.

Review every external skill's source, revision, license, dependency and executable
behavior. Similar names in a proposal are not an installation specification.
Profiles and tool allowlists are not OS containment against a role with unrestricted
terminal access; test the chosen filesystem/network isolation independently.

Exit per role: measurable improvement on its task subset, verified permissions,
bounded costs, and no regression on the held-out cases it can affect. Retire an
ineffective role from routing without deleting its evidence or user-owned data.

### Phase 6 Run nightly candidate improvement

Borrow autoresearch's bounded experiment-and-measure pattern, not its training
program as a drop-in Hermes updater. Begin with manually invoked experiments;
schedule only after their operating limits and delivery destination are approved.

Each run proposes one focused skill, instruction, or memory-maintenance change in
an isolated candidate area. Keep the evaluator, held-out cases, acceptance policy,
credentials, active instructions, and live memory outside its write authority.
Memory proposals retain sources and correction semantics; they never silently
rewrite facts or erase source records.

Evaluate candidates against deterministic checks and the fixed rubric. A Jev or
other model judge is advisory on subjective criteria. Record the candidate diff,
baseline comparison, cost, failures, and rollback instructions. No automatic merge,
deployment, live memory mutation, credential change, or instruction replacement.

Exit: a scheduled run can stop at budget, recover after interruption, and produce
a reviewable proposal without changing active behavior. Promotion remains an
explicit reviewed step. If automatic promotion is later requested, design its
authority and acceptance mechanism as a separate change.

## Evidence and rollout completion

Keep trial evidence private by default: task and run IDs, exact artifact hashes,
review verdicts, command results, provider usage, latency, and remaining gaps.
Retain only redacted synthetic summaries in a public repository.

For implementation changes, run the checkout's native checks and use
`scripts/run_tests.sh` for Python tests. Cover real resolution/discovery and file
I/O against temporary homes, including A → B → A profile changes. For visible
features, observe the actual client surface; green unit tests do not establish
desktop, gateway, WebUI, or mobile behavior. Revalidate after stable-version updates.

Completion means the promoted configuration, pinned components, measured results,
backup/restore procedure, and rollback action are recorded; required user-facing
surfaces work; and no required verification gate is merely assumed. Wider rollout
follows a successful isolated pilot. It is not implied by completion of this plan.

## Source references

Capability review used the installed Hermes v0.23.0 source. Revalidate these
contracts against the implementation version before executing the plan.

- [Hermes profile semantics](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/website/docs/user-guide/profiles.md)
- [Delegation providers and cache-aware configuration](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/website/docs/developer-guide/delegation-provider-plugin.md)
- [Depth-derived child role implementation](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/tools/delegate_tool.py)
- [Kanban review and completion contracts](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/website/docs/user-guide/features/kanban.md)
- [OpenViking reviewed plugin configuration and access scope](https://github.com/volcengine/OpenViking/blob/e855796c83f9eb575d9b0f3082926660730f6a63/examples/hermes-plugin/CONFIGURATION.md)
- [JEV effort-router provider gate at the inspected catalog pin](https://github.com/AlphaPerseii3000/jev-effort-router/blob/562dc2a27aa22977e0795809a17fbbbb1819f0ab/router.py#L111)
- [Voyage model descriptions](https://docs.voyageai.com/docs/embeddings) and [current pricing](https://docs.voyageai.com/docs/pricing)
- [Autoresearch experiment scope](https://github.com/karpathy/autoresearch#how-it-works)
