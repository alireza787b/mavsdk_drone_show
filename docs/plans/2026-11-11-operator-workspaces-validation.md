# Operator workspace refinement checkpoint

## Scope

This source/UI checkpoint refreshes Custom Show and Mission Config and makes
Overview inspection quieter. It does not change PX4 parameters, flight gains,
fleet formation, admission limits or aircraft-side mission execution.

- Overview shows Configured IP and stable link state. Exact ages remain in hints
  and inspector Diagnostics; missing information remains unknown.
- Custom Show has Operate and Design / Setup. Flight controls come first;
  scheduling, exact aircraft selection, native review and uncertain-receipt
  lookup are retained. Managed Return reuses the shared sequential queue.
- Preview import/regeneration creates matching light/dark PNGs, without color
  inversion. Explicit regeneration leaves CSV bytes and modification time alone.
  GET remains read-only. The maintenance POST is typed and excluded from the
  callable Simurgh registry.
- Mission Config prioritizes assignments and launch layout. Advanced tools and
  enrollment remain accessible in disclosures. Save review uses the shared
  focus-trapped dialog and clears acknowledgment when the reviewed report changes.
- Launch geometry uses concise measured summaries and a collapsed plot key.
  Unavailable summaries do not become zero; zero latitude/longitude is accepted
  as a valid origin. Review colors are display evidence, not flight admission.
- Retired Custom Show page and obsolete page/plot/save-dialog styles are removed;
  existing URLs and native API/command contracts remain supported.

## Validation evidence

All builds, tests and browser checks run on the designated remote validation
host, in an isolated worktree. Browser aircraft are synthetic and requests are
intercepted; no aircraft command or real configuration save is issued.

- Full dashboard baseline: **164 suites / 1,236 tests passed**.
- Final UI delta: **7 suites / 34 tests passed**, including the new launch
  geometry cases and disabled capture semantics.
- Preview/API/theme checks: **26 passed**.
- API and documentation/tool-index contracts: **112 passed**.
- Final generated-contract and preview recheck: **17 passed**.
- Optimized source build and dark/light responsive browser matrix cover
  desktop 1440 px, tablet 900 px and phone 390 px, including Setup, Operate,
  launch review, Mission Config, save review and IP inspection.

[Browser result matrix](../assets/operator-workspaces/evidence/browser-results.json)
and [illustrated workflow](../assets/operator-workspaces/operator-workspace-guide.png)
are retained with the source documentation. All screenshot aircraft are fixtures.

The repository guides and generated API/documentation indexes are refreshed in
the same phase. Preview regeneration adds no automatically callable agent tool.

## Boundaries

This is not a new pinned SITL image or flight qualification. The previously
deferred clean image rebuild/distribution remains separate. No real-aircraft
takeoff, return or motion is part of these UI checks. Independent physical
inspection, identity confirmation and qualified flight acceptance remain
required after an aircraft incident. Browser responsive emulation is not a
substitute for physical touch-device/Safari acceptance.
