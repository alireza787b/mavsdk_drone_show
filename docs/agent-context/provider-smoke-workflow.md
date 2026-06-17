# Simurgh Provider Smoke Workflow

This workflow validates the optional advisory-only OpenAI adapter before a
maintainer enables it for a GCS service. It is a smoke check, not a feature
eval suite and not an operator command path.

Default rule:

- Run dry mode first. Dry mode patches the provider transport locally, validates
  the exact OpenAI Responses request invariants, and does not contact OpenAI.
- Run live mode only from a validation host or maintenance window after offline
  tests pass.
- Keep `MDS_AGENT_ACTION_CIRCUIT_BREAKER=true`,
  `MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION=true`, and `MDS_MCP_ENABLED=false`
  during provider smoke.
- Do not change deployment `MDS_MODE` for this workflow. A production GCS may
  remain `MDS_MODE=real`; the Simurgh assistant circuit breaker controls
  Simurgh non-read-only actions independently from human GCS operation.
- Keep deployed assistant endpoints on `MDS_AGENT_PROVIDER=mock` unless MDS auth
  is enabled and operators authenticate with an operator/admin session or a
  bearer token scoped for `agent`, `operator`, or `admin`. Drone-only bearer
  tokens cannot trigger external provider calls. Live smoke can validate
  provider connectivity from a trusted shell, but production HTTP assistant turns
  must not expose OpenAI as an unauthenticated or lower-privilege machine-token
  surface.
- Do not expose MCP tools, raw GCS commands, direct drone APIs, uploaded files,
  conversation state, streaming, background jobs, or provider-side storage.
- Do not paste raw field logs, screenshots, credentials, exact coordinates,
  private network details, or private repository paths into smoke prompts.

## Scenario Source

Smoke scenarios live in `config/agent_provider_smoke.yaml`. Add or edit
scenarios there, then update tests and this document in the same slice. The
suite is intentionally small; detailed behavior belongs in
`docs/agent-context/evals/simurgh-advisory-provider.yaml`.

Each scenario should specify:

- `id`: stable lowercase identifier
- `provider`: currently `openai`
- `actor`: non-sensitive actor label
- `prompt`: sanitized public-context prompt
- `context_resources`: public context ids from `context-index.yaml`
- `expected`: response length and required safety-note fragments

## Key Handling

Live smoke uses `MDS_AGENT_OPENAI_API_KEY_FILE` or `--api-key-file`. The key path
must be absolute, point to a regular non-empty file, and have no group or other
permissions. Use a root-owned file such as:

```bash
install -d -m 0700 /etc/mds/secrets
install -m 0600 /dev/null /etc/mds/secrets/openai_api_key
```

Paste the key into that file outside shell history. Do not store keys in
environment values, committed config, docs, tests, reports, Telegram messages,
or assistant prompts. Rotate any key that has been posted into chat or logs
before production use.

## Commands

Dry run:

```bash
python3 tools/run_simurgh_provider_smoke.py --expected-runtime-mode sitl
```

Live smoke:

```bash
python3 tools/run_simurgh_provider_smoke.py \
  --expected-runtime-mode real \
  --live \
  --api-key-file /etc/mds/secrets/openai_api_key
```

The printed report omits raw assistant content by default and includes only
safe metadata such as pass/fail state, content length, and a content hash. Use
`--show-content` only on a trusted validation host when the scenario prompt and
context are public. Set `--expected-runtime-mode` to the GCS mode you intend to
validate. The smoke does not change modes or alter its workflow based on that
value; it fails if the observed canonical `MDS_MODE` differs.

## Required Invariants

The smoke harness fails closed if the OpenAI request differs from the approved
advisory shape:

- `store=false`
- `tools=[]`
- `tool_choice="none"`
- `parallel_tool_calls=false`
- the canonical runtime mode matches `--expected-runtime-mode`
- the action circuit breaker is enabled
- always-confirm-before-action is enabled
- no `messages`, `conversation`, or `previous_response_id`
- no `stream`, `background`, uploaded-file, attachment, vector-store, or file-id
  fields
- metadata keeps `mds_execution=none`

The OpenAI base URL is pinned to `https://api.openai.com/v1` in this slice.
Custom OpenAI-compatible gateways are not accepted because the API key and
public context must not be sent to an unreviewed destination.

The adapter must parse text output without assuming a single fixed output array
shape, and it must reject non-text outputs.

## Reviewer Checklist

Before a slice can enable or deploy a provider configuration, reviewers should
confirm:

- dry smoke passes
- live smoke was run only with a restricted key file, when live smoke is needed
- advisory evals still pass offline
- no raw secret or field artifact appears in repo diffs, reports, shell output,
  runtime history, or dashboard API responses
- production service configuration keeps real drone operation mode separate from
  the Simurgh assistant circuit breaker
- docs, prompts, config, and tests agree on the current behavior
