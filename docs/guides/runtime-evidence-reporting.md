# Runtime Evidence Reporting

MDS runtime reports should be generated from accepted telemetry/log artifacts, not from hand-written claims.
Use this workflow for public-safe validation packages and adapt it in private forks for customer-specific reports.

## What The Template Provides

- Markdown report with command results, timing, event timeline, tracking metrics, visuals, and evidence links.
- Optional HTML/PDF rendering when `pandoc` and `weasyprint` are installed.
- Visual asset copying from an analysis output directory.
- Evidence copying with a default large-file guard so raw ULogs or archives do not accidentally bloat git history.
- Customer-neutral wording suitable for official/public documentation.

## Standard Workflow

1. Run a validator or scenario-specific runtime script and keep the accepted summary JSON.
2. Generate metrics and plots from the accepted run.
3. Fetch raw logs or ULogs when available.
4. Package the evidence report.
5. Keep private customer names, contract details, site details, and mission-sensitive context in the private package only.

## Command

```bash
python3 tools/package_runtime_evidence_report.py \
  --summary-json /path/to/accepted-summary.json \
  --metrics-json /path/to/metrics.json \
  --visuals-dir /path/to/plots \
  --evidence-file /path/to/raw-log-or-input.csv \
  --output-dir /tmp/mds-runtime-evidence \
  --repo-root . \
  --title "MDS Runtime Evidence Report" \
  --subtitle "Accepted Runtime Scenario Evidence" \
  --scenario "smart-swarm-leader-follow"
```

The output package contains:

- `report/<scenario>-evidence-report.md`
- `report/<scenario>-evidence-report.html` if rendering dependencies exist
- `report/<scenario>-evidence-report.pdf` if rendering dependencies exist
- `visuals/`
- `evidence/`
- `README.md`

## PDF Rendering

Install both tools on the machine doing report generation:

```bash
sudo apt-get install pandoc
pip install weasyprint
```

If either tool is missing, the report still produces Markdown and records that PDF rendering was skipped.

## Large Evidence Policy

By default, files larger than 25 MB are not copied into the package. This avoids accidentally committing large ULogs, archives, or video outputs to git.

Use `--include-large-evidence` only when the output package is external/private and intentionally stores large artifacts.

## Private Customer Reports

For a customer fork, keep the public-safe generator in official and place customer-specific scenario text in the private repo/package. A private report can still use the same structure:

- neutral runtime summary from this tool,
- private executive/contract context added outside official,
- raw ULogs stored in external package storage or private release assets,
- GitHub Markdown with only the small visuals/evidence that are safe for that private repo.

## Review Checklist

- The run result is `PASS` or otherwise clearly marked.
- Command statuses match the intended scenario semantics.
- Continuous commands such as live follow modes are explained if they remain `executing` until superseded.
- Visuals are generated from the accepted run, not an earlier failed trial.
- Raw ULogs/log archives are checksummed if not committed.
- Official/public reports contain no customer name, contract detail, phone number, private IP, token, or site-specific mission data.
