# sra-run-watch

Daily watcher for newly registered **INSDC sequencing runs** (SRR / ERR / DRR). Once a day
it pulls the freshest available metadata from **NCBI** and **ENA**, accumulates a complete
history in a local SQLite database, and writes a dated list of the runs first seen that day
with their registration date, sequenced bases, and sequencing file sizes.

- **Pure Python 3, standard library only** — no `pip install`, no build step.
- Designed to run from `cron`; idempotent and safe to re-run.

> Status: design approved, implementation in progress. See
> [`docs/superpowers/specs/2026-05-20-sra-run-watch-design.md`](docs/superpowers/specs/2026-05-20-sra-run-watch-design.md).

## What it produces

A daily TSV, `data/new_runs_YYYY-MM-DD.tsv`, of runs first seen that day:

| Column | Source | Notes |
|--------|--------|-------|
| `run_accession` | both | SRR / ERR / DRR |
| `date` | ENA `first_public`, else NCBI `Published` | registration date |
| `sequenced_bases` | ENA `base_count` | may be blank until ENA catches up (see below) |
| `sra_bytes` | NCBI `fileinfo_runs` / ENA | `.sra` file size in bytes |
| `fastq_bytes` | ENA `fastq_bytes` | `;`-separated for paired-end |
| `fastq_ftp` | ENA `fastq_ftp` | `;`-separated download URLs |
| `sra_url` | constructed | public ODP S3 URL for the `.sra` |

A cumulative **`data/runs.sqlite`** is the source of truth and always holds the most
complete values for every run ever seen.

## How it works

Two feeds are combined because neither alone is both fresh and complete:

- **NCBI Mirroring delta** (`ftp.ncbi.nlm.nih.gov/sra/reports/Mirroring/`) — ~1 day fresh.
  Gives new run accessions, publish date, and `.sra` file sizes. **Does not** carry
  sequenced bases.
- **ENA Portal API** (`ebi.ac.uk/ena/portal/api`) — covers all INSDC, but lags NCBI by
  ~10–14 days. Provides sequenced bases, fastq sizes, and download URLs.

A run is considered **"newly added" the first time its accession enters the database** —
not based on any date field, because NCBI's publish dates include re-touches and future
embargo dates. As a result, an NCBI-fresh run may appear in its day-0 file with `sra_bytes`
but blank `sequenced_bases`/`fastq_*`; those fields fill in (in the database) when the ENA
sweep catches up ~2 weeks later.

## Usage

```bash
# default: today (UTC), data in ./data
python3 sra_run_watch.py

# options
python3 sra_run_watch.py \
  --data-dir ./data \
  --ncbi-lookback-days 3 \
  --ena-window-days 30 \
  --date 2026-05-20
```

### Cron

```cron
# every day at 18:30 UTC (after NCBI publishes its ~17:00 UTC delta)
30 18 * * * cd /path/to/sra-run-watch && /usr/bin/python3 sra_run_watch.py >> data/cron.log 2>&1
```

## Requirements

- Python 3 (standard library only).

## License

[Apache License 2.0](LICENSE).
