# sra-run-watch — Design

**Date:** 2026-05-20
**Status:** Approved design, pre-implementation

## Purpose

A standalone daily tool that produces a list of **newly registered INSDC sequencing runs**
(SRR / ERR / DRR) with their registration date, sequenced bases, and sequencing file
sizes (`.sra`, `.fastq.gz`). Intended to be run once per day from cron, accumulating a
complete history in a local database and emitting a dated file of the runs first seen
that day.

This is an independent repository, not part of `insdc-rdf`. It is implemented in
**Python 3, standard library only** (no `pip install`, no build step) so it runs anywhere
Python 3 exists with minimal installation burden.

## Why these data sources

The workload is network-bound and tiny on the CPU side, so language choice is about
maintenance/installation, not speed — hence Python stdlib.

Two feeds are combined ("hybrid") because neither alone is both fresh and complete:

| Feed | Freshness | Provides | Gaps |
|------|-----------|----------|------|
| **NCBI Mirroring delta** (FTP) | ~1 day | run accession, publish date, `.sra` file size | **no bases**; SRR-centric |
| **ENA Portal API** | ~10–14 day lag | run accession, `first_public`, **base_count**, `fastq_bytes`, `sra_bytes`, `fastq_ftp` | lag means "yesterday" really means ~2 weeks ago |

### Verified facts (checked 2026-05-19/20 against live data)

- NCBI publishes a small **daily delta** at
  `https://ftp.ncbi.nlm.nih.gov/sra/reports/Mirroring/NCBI_SRA_Mirroring_YYYYMMDD/`
  (published ~17:00 UTC). Relevant files:
  - `fileinfo_runs.csv.gz` — header `Accession,FileSize,FileMd5,FileDate`. Only runs whose
    `.sra` file changed that day (hundreds of rows). `FileSize` is the `.sra` byte size.
  - `livelist.csv.gz` — header
    `Accession,Type,Status,Received,Published,LastUpdate,LastMetaUpdate,ReplacedBy,BioSample,BioProject,Insdc`.
    All accession types; filter `Type==RUN`. Contains SRR/ERR/DRR. ~16k RUN rows/day.
- **Bases are NOT in any NCBI daily delta.** The run-XML delta
  (`meta_run_set.xml.gz`) carries **zero** `total_bases` attributes (checked 16,682 runs).
  Fresh bases would require the 3.7 GB `SRA_Run_Members.tab` snapshot or ~15k/day per-run
  API calls — both rejected as too heavy. Bases come from the ENA sweep.
- **`livelist.Published` is the original publish date, not a freshness signal.** Today's
  delta contains RUN rows with Published dates in 2016–2017 (metadata re-touched) and even
  *future* dates (2027–2028 = embargo/hold-until dates). So "Published == today" does NOT
  mean "new run."
- **ENA Portal API covers all INSDC** (SRR + ERR + DRR resolvable), but the mirror lags
  NCBI by ~10–14 days, and very recent dates return empty `base_count`/byte fields until
  ENA finishes processing.
- ENA query gotcha: `first_public=YYYY-MM-DD` (equality) silently returns 0 rows. Must use
  a range: `first_public>=A AND first_public<=B`. `offset` is unsupported; paginate by
  splitting the date window. Use POST for queries with operators.

## Novelty model: "new to us"

Because publish-date semantics are unreliable (re-touches, embargo/future dates), novelty
is **not** derived from any date field. Instead:

- A cumulative **SQLite database** is the source of truth for every run accession ever seen.
- A run is "newly added" the **first time its accession enters the database**, regardless
  of which feed reported it or what its publish date is.
- The `date` column stores the run's reported registration date (ENA `first_public` when
  available, else NCBI `Published`) for information — it does not drive novelty.

This makes the tool idempotent and robust: re-running a day, or a feed reporting an old
accession, never produces a false "new" entry.

## Architecture

A single Python module/script, organized as small pure functions plus thin I/O wrappers,
so the parsing/merge logic is unit-testable without network.

```
sra-run-watch/
  sra_run_watch.py        # entry point + orchestration
  src/                    # (if split) parsers, db, feeds — pure logic
  tests/
    fixtures/             # captured small samples of each feed
  data/                   # runtime: runs.sqlite + daily files (gitignored)
  docs/
```

(Final module layout decided in the implementation plan; logic boundaries below are fixed.)

### Components (logical units)

1. **NCBI delta feed** — `fetch_ncbi_delta(date) -> rows`
   - Inputs: a UTC date. Builds the Mirroring URL, downloads `livelist.csv.gz` and
     `fileinfo_runs.csv.gz`, gunzips in memory.
   - Output: normalized run records `{run_accession, archive, date(Published), sra_bytes,
     sra_md5, insdc}` for `Type==RUN` rows, joined with fileinfo on accession (sra_bytes
     may be absent if no file entry that day).
   - Missing directory (not yet published) → returns empty + logs, does not error.

2. **ENA sweep feed** — `fetch_ena_sweep(start_date, end_date) -> rows`
   - POSTs `portal/api/search`, `result=read_run`, `query=first_public>=start AND
     first_public<=end`, `fields=run_accession,first_public,base_count,fastq_bytes,
     sra_bytes,fastq_ftp`, `format=tsv`, explicit large `limit`.
   - Splits the window day-by-day if a single response is too large (no offset support).
   - Output: normalized records `{run_accession, archive, date(first_public),
     sequenced_bases, sra_bytes, fastq_bytes, fastq_ftp}`. Multi-value `fastq_bytes`/
     `fastq_ftp` (`;`-separated for paired-end) are kept as-is (joined string).

3. **Parsers** (pure): `parse_livelist_csv`, `parse_fileinfo_csv`, `parse_ena_tsv`,
   `accession_to_archive` (prefix → DRR/ERR/SRR). No I/O; fully fixture-tested.

4. **Store** — SQLite wrapper.
   - Schema `runs`:
     `run_accession TEXT PRIMARY KEY, archive TEXT, date TEXT, sequenced_bases INTEGER,
      sra_bytes INTEGER, fastq_bytes TEXT, fastq_ftp TEXT, sra_md5 TEXT, sra_url TEXT,
      first_seen TEXT, last_updated TEXT, sources TEXT`.
   - `upsert(records, today)`: insert new accessions (set `first_seen=today`); for existing
     accessions, fill any NULL/empty fields from the new record and refresh `last_updated`
     (never overwrite a populated field with an empty one). Track which feeds touched the
     row in `sources`.
   - `select_new(today) -> rows`: rows where `first_seen == today`.

5. **Output writer** — writes `data/new_runs_YYYY-MM-DD.tsv` with header:
   `run_accession  date  sequenced_bases  sra_bytes  fastq_bytes  fastq_ftp  sra_url`
   - `sra_url`: constructed public ODP URL for the `.sra`
     (`https://sra-pub-run-odp.s3.amazonaws.com/sra/<acc>/<acc>`); `fastq_ftp` comes from ENA.

6. **Orchestrator** — `main()`:
   1. Ingest NCBI delta for the last `N` days (default 3) — covers the not-yet-published day
      plus overlap; upserts are idempotent.
   2. Ingest ENA sweep over the trailing `W` days (default 30) — backfills bases/fastq and
      discovers ERR/DRR missed by NCBI.
   3. `select_new(today)` and write the dated file.
   4. Log a summary (counts new, counts updated, feeds reached).

## Data flow

```
NCBI Mirroring/<date>/{livelist,fileinfo_runs}.csv.gz ─┐
                                                       ├─► normalize ─► upsert ─► runs.sqlite
ENA portal/api/search (first_public window) ───────────┘                          │
                                                                                   ▼
                                                          select first_seen==today ─► new_runs_YYYY-MM-DD.tsv
```

A typical SRR lifecycle across runs of the tool:
- **Day 0:** NCBI delta → row created with `date` + `sra_bytes`; `sequenced_bases`,
  `fastq_bytes`, `fastq_ftp` empty. Appears in that day's output file.
- **~2 weeks later:** ENA sweep → same row updated in place with `sequenced_bases`,
  `fastq_bytes`, `fastq_ftp`. Does **not** reappear in a daily file (not new).

The **daily file is a point-in-time snapshot**; the **database always holds the most
complete values**. Accepted tradeoff: bases/fastq are blank in the day-0 file for
NCBI-fresh runs. (Rejected alternative: ~15k/day per-run NCBI API calls for same-day bases.)

## Configuration

CLI flags / env with sensible defaults:
- `--data-dir` (default `./data`) — DB + output files.
- `--ncbi-lookback-days` (default 3).
- `--ena-window-days` (default 30).
- `--date` (default: today UTC) — for backfill/replay.

## Error handling

- **Network**: per-request timeout + retry with exponential backoff (e.g. 3 attempts).
  Transient failures of one feed do not abort the other; a feed that fails after retries is
  logged and skipped for the run (DB simply isn't updated from it).
- **Missing NCBI dir** (delta not yet published): treated as empty, logged, not fatal.
- **Empty ENA fields** for very recent dates: expected; rows get completed on later runs.
- **Malformed rows**: logged and skipped, processing continues.
- **Exit code**: non-zero only on unrecoverable errors (e.g. cannot open DB, both feeds
  fail) so cron mail alerts. Normal partial-data runs exit 0.
- **Idempotency**: all writes are upserts keyed by accession; re-running any day is safe.

## Testing

- **Unit tests** (no network) on pure functions using small captured fixtures in
  `tests/fixtures/`: `accession_to_archive`, `parse_livelist_csv`, `parse_fileinfo_csv`,
  `parse_ena_tsv`, the upsert/merge rule (esp. "never overwrite populated with empty"),
  and `select_new`.
- **Smoke test** (network, opt-in / skippable): run the orchestrator against a recent real
  date into a temp DB and assert rows land with expected columns.

## Out of scope

- Experiment/sample/study/bioproject relations (run IDs only, per requirement).
- RDF output (this is a separate concern from `insdc-rdf`).
- Downloading the actual sequence files.
- A daemon/server; this is a cron-invoked batch script.
