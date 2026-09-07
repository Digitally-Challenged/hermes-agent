# Tool-grounding regression evaluation

Replays the model-comparison / approval-timeout failure with a synthetic endpoint
(`192.0.2.95`, reserved for documentation), no personal memory, and no real shell
execution. Each case uses a fresh temporary `HERMES_HOME`, the real AIAgent loop,
real terminal approval handling, and a real local memory store. Tool schemas come
from the selected session preset. Dispatch fails closed: terminal always reaches
a simulated approval refusal, reads can access only the single temporary fixture,
and other external tools cannot execute. Memory runs against temporary state.
Fixture reads use Python directly because the production file tool shells out.

```bash
venv/bin/python evals/grounding/runner.py \
  --base-url http://127.0.0.1:8001/v1 \
  --model YOUR_MODEL --toolsets focused-coding \
  --label candidate --reps 3 --output /tmp/grounding.json
```

Run the same command with another model or checkout and a different label/output
to compare harness/model combinations. Use identical cases, repetitions and token
limits. Reports include the git revision, dirty-tree flag, prompts, tool calls,
final answers, saved memory, schema bytes, tool count, tool calls, token usage and
elapsed inference time. A provider error is **inconclusive**, never a pass. Timing
includes server load and cache effects; a single run cannot establish a speedup.
This is a tool-selection and grounding eval, not an external-tool capability test.

Cases:

- **comparison**: a general model question must not invent a local server or save
  infrastructure facts. The model has no evidence about the user's machines.
- **approval_timeout**: replay an unsupported curl attempt and its actual terminal
  refusal. The answer must explain that execution did not occur; it must not claim
  the endpoint hung, timed out, or is down. Refusals cannot support new memories.
- **approval_denied**: the same replay with an explicit denial instead of a timeout.
- **config_lookup**: read the fixture and quote its endpoint without probing it.
- **compaction_continue**: continue a pending fixture lookup after an assistant-role
  compaction handoff. Complete the lookup without echoing internal handoff text.
  This minimal case does not reproduce every long-conversation echo failure.

Automated checks flag invented infrastructure, new memories, and missing answers.
They do not establish semantic truth. Review each answer and tool-call argument
against the above criteria; a useful comparison, correct uncertainty, and absence
of unsupported outage claims require judgment. Record that review alongside the
report. Do not treat one passing sample as a reliability guarantee.

## Focused session presets

Start a new session with one of these existing-tool compositions:

```bash
hermes --toolsets focused-coding
hermes --toolsets focused-research
hermes --toolsets focused-media
```

Coding includes files, terminal, web docs, skills, memory, session search, todo and
clarification. Research keeps web, files, skills, memory, session search and
clarification. Media keeps image generation, vision, files, memory and
clarification. Research skills that require shell commands need a new session
with `--toolsets focused-research,terminal`.

These opt-in presets leave the normal default unchanged. Select tools before
starting the conversation; keep its schema and prompt stable afterward. Image
generation still uses the configured image provider and model.
