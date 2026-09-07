# Hermes Agent - Development Guide

Hermes runs one agent core across the CLI, messaging gateways, TUI, and desktop.
Keep the core narrow; capability belongs in existing code, CLI commands, skills,
service-gated tools, and plugins before new core model tools.

## Before changing code

Trace the reported behavior and the original design intent before fixing it.
For bugs, identify the failing runtime path and cover sibling call paths. Preserve
prompt caching, profile isolation, and existing features when applying a fix.

Read the matching guides before implementing or reviewing changes in their area.
They contain the detailed rules and examples formerly held in this file. Read
all applicable guides; code paths inside them are relative to the repository root.

| Task | Required guidance |
| --- | --- |
| Feature scope, contribution review, dependencies, or adding capability | [Contribution policy](docs/agents/contributing.md) |
| Agent loop, caching, discovery, delegation, curator, cron, kanban, or background notifications | [Architecture](docs/agents/architecture.md) |
| CLI, slash commands, TUI, dashboard chat, desktop transport, TypeScript state, or skins | [Interfaces](docs/agents/interfaces.md) |
| Config, credentials, authorization, working directories, persistent state, or profiles | [Configuration and isolation](docs/agents/configuration.md) |
| Tools, toolsets, plugins, providers, or bundled/optional skills | [Extensions](docs/agents/extensions.md) |
| Tests, test execution, gateway streaming/guards, platform behavior, or merge preparation | [Testing and known pitfalls](docs/agents/testing.md) |
| Anything under `apps/desktop/` | [Desktop engineering](apps/desktop/AGENTS.md) and [design contract](apps/desktop/DESIGN.md) |

## Core invariants

- Keep the system prompt byte-stable for the life of a conversation. Preserve
  past context and toolsets; context compression is the exception. Commands that
  change prompt state defer invalidation to the next session unless the user
  explicitly opts into the existing `--now` path.
- Preserve message-role alternation and tool-result ordering. Never inject a
  synthetic user message mid-loop.
- Verify the premise against actual code and history (`git log -p -S`) before
  treating an intentional omission or isolation boundary as a bug.
- Extend existing infrastructure before adding a manager, hook, or abstraction.
  New extension points need concrete consumers. Every core tool adds schema cost
  on every API call; use the footprint ladder in the contribution guide.
- Plugins use generic interfaces and live in their own directories. New memory
  backends and third-party-product integrations ship in standalone plugin repos.
  Preserve contributor authorship when salvaging external work.
- Outbound telemetry and attribution require a user-facing opt-in gate.

## Surface capability is a property of the SESSION

Desktop panes, in-app browsing, reactions, and similar client capabilities resolve
from the session source, including remote and cloud clients. Put surface tools in
named toolsets selected by the gateway for that session. `check_fn` answers
reachability or opt-in; its process-wide cache cannot hold per-session decisions.
`HERMES_DESKTOP` identifies a backend spawned by Electron, not who is connected.
Cover GUI availability with the process environment flag absent.

## Configuration and isolation

- Behavioral settings belong in `config.yaml`; `.env` is for secrets. Integrate
  setup through the existing config/setup/tools UX. Add defaults to
  `DEFAULT_CONFIG`; bump the config version only for an actual migration.
- Use `get_hermes_home()` for profile-scoped state and `display_hermes_home()` for
  user-visible paths. Profile-management operations are intentionally HOME-anchored;
  consult the configuration guide before changing their path resolution.
- Multiplexed profile credentials and authorization must use the scoped secret
  accessors. A scoped miss fails closed; it must not borrow the default profile's
  process environment. Keep profiles independent.
- Check all relevant config loaders and real resolution paths; a CLI result alone
  does not prove the gateway receives a setting.

## UI boundaries

The dashboard embeds the real `hermes --tui` through a PTY. Extend Ink for its
transcript, composer, slash commands, and terminal experience. Supporting React
panels may complement the TUI while keeping independent state and failure handling.

Electron desktop is a separate React chat surface with a shared JSON-RPC transport
and a headless `hermes serve` backend. Read the desktop guide before editing it.
Shared TypeScript state belongs in small feature-owned stores; route roots compose
views, and narrow action modules own side effects.

## Verification

**ALWAYS use `scripts/run_tests.sh` for Python tests**, rather than direct `pytest`.
It isolates credentials, HOME, timezone, locale, and each test file's process.
Prefer the checkout's `.venv`, then `venv`; the runner handles its shared-venv fallback.

```bash
scripts/run_tests.sh tests/gateway/
scripts/run_tests.sh tests/agent/test_foo.py -k test_x
```

- Read the testing guide before writing or running tests. Tests must not write to
  the real `~/.hermes/`. Use a temporary `HERMES_HOME`; profile tests also isolate
  `Path.home()` for HOME-anchored operations.
- Assert behavior and relationships, not changing catalog values, version literals,
  counts, or source-text patterns. Execute the implementation under test.
- Resolution chains, config propagation, security boundaries, remote backends, and
  file/network I/O require real imports and an end-to-end path using temporary state.
- Test OS-specific behavior on the actual OS with the project's `linux_only`,
  `macos_only`, or `windows_only` markers, rather than pretending to change hosts.
- Put JS-side tests in the relevant JS suite so CI selects them for JS changes.
  Use each package's existing build, typecheck, lint, and test scripts.
- Treat pass-on-retry reports as flaky bugs to fix. Fix failures caused by the
  current work, and state any checks that could not run and why.

## Maintaining these instructions

Keep this entrypoint concise so it and scoped `AGENTS.md` files fit within Codex's
32 KiB project-instruction budget. Keep detailed examples in the linked guides;
update the relevant guide when its contract changes. Verify instruction discovery
from both the root and affected subdirectories after reorganizing these files.
