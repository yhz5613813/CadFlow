# CadFlow Agent DSL

This directory is an isolated, optional wrapper for context-efficient CAD
agents. It borrows the useful part of SGLang's design--compact structured
commands over server-side state--without depending on the SGLang runtime. It
does not change CadFlow's existing public API or native kernel.

The line-oriented language compiles to the public replayable `make_*_r*`
operations. Durable history contains geometry, tags, result declarations, and
checkpoints; inspection, export, and preview requests are transient effects:

```text
box base 80 50 6 at 0 0 0
cylinder hole 3 8 at 10 10 -1
cut part base hole
tag part role.base
inspect part volume bbox topology limit=12
result part
```

The runtime returns bounded JSON such as `model`, `revision`, `result`, and
requested inspection facts. Complete model JSON remains available through
`AgentModel.model_json` for replay and interchange, but is never included in a
normal response. `checkpoint NAME` and a standalone `rollback NAME` provide
deterministic revision control by rebuilding the command history in a fresh
`GraphSession`.

Finishing operations accept either explicit topology indices or semantic tags:

```text
fillet rounded body 0.5 edges 0,1
shell hollow rounded 1.0 faces tag:face.top
mirror reflected hollow normal 1 0 0 origin 0 0 0
```

Tag selection is preferable when the public CadFlow operation supplies a
stable semantic tag. Indexed selections remain available for intentional
topology picks and are compiled to real edge/face objects so canonical replay
records geometry selectors.

The parser accepts no Python, imports, attribute access, expressions, or
arbitrary function names. STEP export is explicit:

```text
export part step outputs/part.step
```

A preview request selects a transient tessellation quality without entering
model history or incrementing the revision:

```text
preview part draft
preview part final
```

For a long-running or multi-process agent service, `ModelStore` persists the
control state and canonical model JSON with atomic replacement and file
locking. Mutations require an optimistic revision check:

```python
from agent_dsl import ModelStore

store = ModelStore("/data/yihongzhu/cadflow-agent-models")
store.open("bracket", create=True)
response = store.apply(
    "bracket",
    "box base 80 50 6\nresult base",
    expected_revision=0,
)
facts = store.inspect(
    "bracket",
    "base",
    fields=("volume", "bbox"),
    expected_revision=response.revision,
)
```

Normal responses intentionally omit full model JSON and meshes. Requested
face/edge inspection lists are capped at 64 items; callers should usually ask
for a much smaller limit. `AgentModel.model_json` is the explicit interchange
and replay boundary.

Use `from agent_dsl import AgentModel` from the repository root. The package is
intentionally not installed as part of CadFlow's core distribution.

## Real-time browser preview

The preview service treats a committed model revision as the rendering
boundary. `ModelStore.apply_with_model()` returns the same committed live
geometry used by the background Scene compiler, avoiding an extra history
replay. New submissions coalesce per model; a completed stale build is never
published over a newer revision. Scene assets are written atomically before a
`revision_ready` event makes their immutable URL visible.

Start the dependency-free HTTP/SSE server from the repository root:

```bash
PYTHONPATH=.:python \
  /data/yihongzhu/SimpleCADAPI-venv/bin/python \
  -m agent_dsl.realtime \
  --host 127.0.0.1 --port 8765 \
  --state-dir .cadflow-preview/models \
  --artifact-dir .cadflow-preview/artifacts
```

Open `http://127.0.0.1:8765`. The workbench submits incremental DSL revisions,
listens on `GET /events/{model}` with `EventSource`, and replaces the Three.js
model only after the matching Scene manifest and GLBs are ready. Camera state
is preserved between revisions, and the viewer rejects older revision/build
pairs.

The programmatic submission endpoint is:

```http
POST /models/bracket/apply
Content-Type: application/json

{"document":"box base 80 50 8\nresult base","expected_revision":0,"quality":"draft"}
```

Draft uses `0.35 mm / 0.22 rad` linear/angular tolerances. Final uses the Scene
compiler defaults, `0.1 mm / 0.08 rad`. A DSL `preview SHAPE QUALITY` effect
overrides the request quality and can rebuild the current revision without
changing it. `GET /models/{model}` returns the current revision and latest
ready artifact; geometry and edge GLBs are served below `/artifacts/`.

## Multi-agent proposals

`MultiAgentStore` keeps each agent's durable DSL contribution separate until
merge time. Proposal dependencies form a DAG; read/write sets are derived from
the parsed instructions. A merge with overlapping writes or an undeclared
read-after-write dependency is rejected without changing the model revision.
Accepted proposals are topologically ordered and submitted to `ModelStore` as
one atomic revision, so the existing replay and BREP validation path remains
the execution boundary:

```python
from agent_dsl import ModelStore, MultiAgentStore

models = ModelStore("/data/yihongzhu/cadflow-agent-models")
models.open("assembly", create=True)
agents = MultiAgentStore(models)

agents.submit_proposal(
    "assembly", "body_agent", "box body 20 10 4",
    base_revision=0, proposal_id="body",
)
agents.submit_proposal(
    "assembly", "hole_agent", "cylinder hole 2 6 at 0 0 -1",
    base_revision=0, proposal_id="hole",
)
agents.submit_proposal(
    "assembly", "boolean_agent", "cut final body hole\nresult final",
    base_revision=0, proposal_id="finish", depends_on=("body", "hole"),
)
response = agents.merge(
    "assembly", ("body", "hole", "finish"), expected_revision=0
)
```

Agents can exchange bounded JSON-compatible messages with `send_message()` and
query their mailbox with `messages()`. Messages never mutate model geometry.

## Text2CAD-Bench compatibility gate

The official 600-case Text2CAD-Bench dataset and evaluator are not publicly
available yet; the paper currently says that part of the benchmark and
evaluation code will be released after acceptance. The offline adapter in
`benchmarks/text2cad_published.py` therefore implements the L2 hemisphere with
cross-shaped groove case published in Appendix F. Seven agents author its
independent and dependent features, merge them as one revision, and compare
the result against a public-API reference with CadFlow's strict BREP gate. It
is intentionally reported as a published-case compatibility result, not an
official Text2CAD-Bench score:

```bash
python -m agent_dsl.benchmarks.text2cad_published \
  --output-dir /tmp/cadflow-text2cad-l2
```

The measured reference workflow in `tests/test_agent_dsl.py` compares the DSL
against an equivalent executable public-API Python program. It reduces the
dependency-free lexical token estimate from 119 to 44 tokens (63.03%) and the
UTF-8 payload from 483 to 195 bytes (59.63%). Both gates require at least 20%.
Tests also compare every supported geometry operation against direct public
API STEP output with CadFlow's strict BREP comparison and replay extended
operations through canonical model JSON.

### Real-LLM single-vs-multi-Agent measurement

One controlled run on 2026-08-15 used GPT-5.6 Sol at low reasoning effort
through isolated Codex CLI processes. The single-Agent baseline made one model
call for the complete DSL. The multi-Agent treatment made seven calls using a
dependency DAG with peak concurrency four. Shared and dependency document
forwarding were disabled, and both sides used the same exact-output constraint:

| Execution | Generation | End to end | Input / output / total tokens | Peak concurrency |
| --- | ---: | ---: | ---: | ---: |
| One Agent, one complete-model call | 16.385 s | 18.869 s | 16464 / 62 / 16526 | 1 |
| Seven Agents, parallel DAG | 200.155 s | 202.480 s | 116460 / 139 / 116599 | 4 |

For this case, multi-Agent generation had a 0.0819x speedup, meaning it was
12.216x slower. End to end it had a 0.0932x speedup, or was 10.731x slower,
and consumed 7.055x as many tokens. The slowest multi-Agent request took
140.222 seconds because of provider-side queueing, so latency should be
reported as a real Codex CLI harness observation rather than a stable model
constant. Both candidates passed the strict BREP hard gate with zero
bidirectional material-difference volume. The raw report is retained under
`benchmarks/results/text2cad_gpt56sol_single_vs_multi_20260815_r2/`.

Reproduce the single-vs-multi run from the repository root with:

```bash
PYTHONPATH=.:build/lib.linux-x86_64-cpython-310 \
  /data/yihongzhu/SimpleCADAPI-venv/bin/python \
  -m agent_dsl.benchmarks.text2cad_llm \
  --output-dir /tmp/text2cad-gpt56sol-single-vs-multi \
  --provider codex-cli --model gpt-5.6-sol \
  --mode single-multi --max-concurrency 4 \
  --reasoning-effort low --timeout 600 \
  --omit-shared-context --omit-dependency-context
```

The separate scheduler-only run, which holds the seven calls fixed and changes
only serial versus DAG scheduling, measured 2.004x generation speedup and
1.965x end-to-end speedup with effectively identical token use. Its raw report
is under `benchmarks/results/text2cad_gpt56sol_codex_20260815/`. That result
must not be presented as a single-Agent versus multi-Agent comparison.

For historical comparison, a warmed three-repeat measurement on the same date
used Qwen2.5 1.5B through four independent single-request Ollama endpoints on
RTX 4090 GPUs 4-7, with a 1024 token model context. Each run used the same
Appendix-F L2 geometry and the
complete STEP/BREP validation sequence. Shared and dependency document
forwarding were disabled so the measurement isolates scheduling and per-agent
prompt overhead:

| Execution | Generation, mean +/- std | End to end, mean +/- std | Input / output / total tokens | Peak concurrency |
| --- | ---: | ---: | ---: | ---: |
| Seven agents, serial scheduler | 1.536 +/- 0.090 s | 4.223 +/- 0.148 s | 417 / 74 / 491 | 1 |
| Seven agents, DAG scheduler | 0.612 +/- 0.013 s | 3.290 +/- 0.039 s | 417 / 74 / 491 | 4 |

Against the same seven calls executed serially, DAG scheduling is 2.509 +/-
0.188x faster for generation and 1.284 +/- 0.046x faster end to end, with an
identical token count. All six candidate models passed STEP header/reopen,
one-solid validity, global-summary, and strict BREP gates with zero
material-difference volume. The distinction remains important: parallel
scheduling accelerates decomposed work, while decomposition itself still has
fixed prompt and orchestration costs. A one-call monolithic Agent is a separate
baseline and should not be used to isolate scheduler speedup.

The three raw reports are retained under:

- `benchmarks/results/text2cad_qwen25_1p5b_gpu4-7_ctx1024_20260815/`
- `benchmarks/results/text2cad_qwen25_1p5b_gpu4-7_ctx1024_20260815_r2/`
- `benchmarks/results/text2cad_qwen25_1p5b_gpu4-7_ctx1024_20260815_r3/`

The historical local-provider command was:

```bash
python -m agent_dsl.benchmarks.text2cad_llm \
  --output-dir /tmp/cadflow-text2cad-llm \
  --provider openai --model qwen2.5:1.5b --wire-api chat \
  --base-url http://127.0.0.1:11434/v1 \
  --base-url http://127.0.0.1:11435/v1 \
  --base-url http://127.0.0.1:11436/v1 \
  --base-url http://127.0.0.1:11437/v1 \
  --mode comparison --max-concurrency 4 \
  --omit-shared-context --omit-dependency-context
```

The command writes the complete machine-readable result to
`<output-dir>/benchmark.json`. Each serial or parallel subdirectory also
contains `validation.json` with STEP hashes, file/header checks, global BREP
summaries, and the strict bidirectional comparison result. HTTP provider
replicas are leased exclusively, so one endpoint cannot receive two Agent
requests at the same time through the pool. The Codex provider instead starts
one isolated CLI process per request.

## Whole-conversation benchmark

The single-request numbers above are not the total context reduction. The
benchmark in `benchmarks/context_total.py` measures a six-turn modeling
session: create a base, cut a hole, translate it, tag it, inspect it, and
export it. Each stateless Python request rebuilds the current revision; the DSL
keeps that state server-side. Both sides use the same actual compact JSON
responses, so the comparison isolates the request representation while still
counting responses and all prior turns.

With `tiktoken`'s `o200k_base` encoding, the measured totals are:

| Scope | Public Python | DSL | Total saved | Reduction |
| --- | ---: | ---: | ---: | ---: |
| Requests only | 872 tokens | 134 tokens | 738 tokens | 84.63% |
| Final retained conversation | 1,382 tokens | 644 tokens | 738 tokens | 53.40% |
| Six calls, cumulative input plus output | 4,549 tokens | 2,393 tokens | 2,156 tokens | 47.40% |
| Final retained conversation | 4,502 bytes | 1,853 bytes | 2,649 bytes | 58.84% |
| Six calls, cumulative input plus output | 14,498 bytes | 6,639 bytes | 7,859 bytes | 54.21% |

The dependency-free lexical proxy reports the same conclusion: the final
conversation falls from 1,401 to 722 tokens, saving 679 (48.47%), and
cumulative processing falls from 4,605 to 2,639, saving 1,966 (42.69%). The
corresponding byte totals are 4,510 to 1,857 for the final conversation and
14,510 to 6,643 across all six calls.

These figures exclude the system prompt shared by both protocols. If that
prompt is `S` tokens, the `o200k_base` final-window reduction is
`738 / (1382 + S)`, and the six-call cumulative reduction is
`2156 / (4549 + 6S)`. They remain at least 20% while `S <= 2308` and
`S <= 1038`, respectively. This distinction matters: the measured reduction
is for dynamic CAD context, not an unknown fixed agent prompt.

The benchmark also exports both final models and applies CadFlow's strict BREP
gate. The gate passes, and both directional material-difference volumes are
zero. Run the dependency-free version with:

```bash
python -m agent_dsl.benchmarks.context_total --output-dir /data/yihongzhu/cadflow-context-benchmark-output/lexical
```

Pass `--tokenizer o200k_base` when `tiktoken` is available. Exact byte counts
include the export path embedded in the final request, so changing the output
directory can change them by a few bytes.
