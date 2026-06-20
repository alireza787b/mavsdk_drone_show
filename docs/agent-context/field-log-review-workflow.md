# Simurgh Field Log Review Workflow

Field logs are useful for improving Simurgh guidance, but raw flight artifacts
can contain sensitive operational data. Official MDS docs, evals, prompts, and
tests must store sanitized patterns only.

Default rule:

- Do not commit raw ULog files, QGC logs, companion logs, screenshots, chat
  exports, customer archives, or private network details to the official repo.
- Keep original artifacts in the approved private evidence location for that
  customer or test campaign.
- Record a hash, artifact type, collection date, and reviewer name in the
  private evidence trail. Use the hash to relate a sanitized finding back to
  the private source without copying the source into public context.
- Convert lessons into minimal, reproducible, non-identifying scenarios before
  adding them to docs, prompts, or eval suites.
- Keep sensitive evidence detection configurable in `config/agent_assistant.yaml`
  through `sensitive_input_terms` and `sensitive_input_patterns`; update those
  guardrails when new field artifact names or identifier formats appear.
- Safe inventory/status questions are different from raw artifact review. For
  example, Simurgh may answer whether approved GCS endpoints show per-drone log
  sessions or ULog file metadata, and may correlate that with command-tracker
  summaries. It must still block pasted/downloaded/attached ULog, QGC, MAVLink,
  screenshot, archive, or customer field evidence before provider calls or
  public repo updates.

## Intake

Before reviewing field artifacts, classify the source:

- customer, partner, internal lab, public demo, or synthetic
- live-operation, maintenance-window, SITL, or bench-test context
- contains flight telemetry, exact coordinates, times, vehicle identifiers,
  network topology, logs, screenshots, credentials, or operator communications
- authorized for private evidence review by the project owner

If authorization or storage location is unclear, stop and ask the project owner.
Do not paste raw artifacts into assistant prompts, GitHub issues, public docs,
Telegram summaries, or eval fixtures.

## Redaction

Remove or generalize these items before anything enters the official repo:

- customer, operator, site, vessel, organization, and phone details
- private repo names, private URLs, ticket IDs, device serials, and NetBird peer
  identifiers
- public or private IP addresses when they reveal deployment topology
- API keys, tokens, cookies, passwords, SSH material, and OAuth details
- exact latitude, longitude, altitude profile, timestamps, and mission names
  unless they are explicitly approved public demo data
- raw MAVLink, ULog, QGC, companion, dashboard, systemd, or network logs
- screenshots that show names, map tiles, coordinates, peer IDs, keys, tokens,
  shells, chat history, or private repository paths

Use neutral placeholders such as `affected_vehicle`, `known_good_vehicle`,
`private_overlay_network`, `gcs_host`, `field_operator`, and
`redacted_coordinate` when a scenario needs structure.

## Evidence Checklist

A sanitized finding is ready for an official Simurgh update only when all items
below are true:

- The raw artifact remains outside the official repo.
- A private evidence record exists with source hash and reviewer.
- The finding is described as behavior, not as a copied log excerpt.
- Sensitive identifiers are removed or generalized.
- The diagnostic path is observation-first and does not claim assistant action.
- The GCS-only boundary is preserved; no direct drone-local API is exposed.
- The update includes matching docs, prompt/config context, eval scenarios, and
  focused tests when behavior changes.
- Offline evals pass before any live-provider or deployment discussion.
- Production services are not updated while field teams are flying or testing.

## Eval Conversion

When a real field issue teaches a reusable lesson:

1. Write a one-paragraph sanitized incident pattern.
2. Name the observable signals and what was ruled out.
3. State the safe diagnostic order.
4. Add the expected assistant response to
   `docs/agent-context/evals/simurgh-advisory-provider.yaml`.
5. Add or update tests that prove the scenario stays text-only/no-action.
6. Update this context or the operator guidance if the workflow changed.
7. Run the advisory eval suite and focused backend tests on the validation host.
8. Request independent reviewer approval before moving to the next slice.

Example sanitized pattern:

> An affected vehicle appeared online in the private overlay network, but QGC
> did not receive MAVLink from it. A known-good vehicle worked on the same
> cellular link. The safe guidance is to compare the two vehicles, verify GCS
> routing, and check whether the expected MAVLink stream configuration is
> enabled, without changing parameters from the assistant.

This pattern can become an eval. The raw log archive, chat transcript, exact
vehicle labels, site name, phone numbers, overlay peer IDs, and timestamps do
not belong in the eval.
