# sra-run-watch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Python 3 (stdlib-only) tool that runs daily, harvests newly registered INSDC sequencing runs from the NCBI Mirroring FTP delta and the ENA Portal API, accumulates them in a SQLite database, and writes a dated TSV of runs first seen that day.

**Architecture:** Pure parsing/merge logic in a small importable package `srw/`, with thin network wrappers kept separate so all logic is unit-testable without network access. A cumulative SQLite DB is the source of truth; novelty is "first time an accession enters the DB". An orchestrator wires feeds → upsert → daily-file output.

**Tech Stack:** Python 3 standard library only — `urllib`, `gzip`, `csv`, `sqlite3`, `argparse`, `datetime`, `unittest` (tests). No `pip install`, no build step.

**Spec:** `docs/superpowers/specs/2026-05-20-sra-run-watch-design.md`

---

## File Structure

```
sra-run-watch/
  sra_run_watch.py          # entry point: argparse + main() orchestration
  srw/
    __init__.py
    accession.py            # accession_to_archive (pure)
    parsers.py              # gunzip_text, parse_livelist_csv, parse_fileinfo_csv,
                            #   parse_ncbi_delta, parse_ena_tsv (pure)
    feeds.py                # ncbi_delta_url, ena_search_params, http_get, http_post,
                            #   fetch_ncbi_delta, fetch_ena_sweep
    store.py                # connect, upsert, select_new (SQLite)
    output.py               # compute_sra_url, write_daily_file
  tests/
    __init__.py
    test_accession.py
    test_parsers.py
    test_store.py
    test_output.py
    test_feeds.py
    test_main.py
    test_smoke.py           # network, skipped unless SRW_SMOKE=1
  data/                     # runtime only (gitignored): runs.sqlite + new_runs_*.tsv
```

### Canonical normalized record (used everywhere)

Parsers emit plain `dict`s with a subset of these keys. `run_accession` is always present; the rest are optional and default to `None`:

```
run_accession   str    e.g. "SRR38673021"
archive         str    "NCBI" | "ENA" | "DDBJ"  (derived from accession prefix)
reg_date        str    registration date "YYYY-MM-DD" (ENA first_public, else NCBI Published)
sequenced_bases int    ENA base_count
sra_bytes       int    .sra file size
sra_md5         str    .sra md5
fastq_bytes     str    ENA fastq_bytes (kept as-is; ";"-separated for paired-end)
fastq_ftp       str    ENA fastq_ftp  (kept as-is; ";"-separated)
source          str    which feed produced this record ("ncbi" | "ena")
```

### DB table `runs`

```
run_accession   TEXT PRIMARY KEY
archive         TEXT
reg_date        TEXT
sequenced_bases INTEGER
sra_bytes       INTEGER
sra_md5         TEXT
fastq_bytes     TEXT
fastq_ftp       TEXT
first_seen      TEXT     -- date (YYYY-MM-DD) the accession first entered the DB
last_updated    TEXT     -- date of the most recent run that touched the row
sources         TEXT     -- comma-joined set of feeds that have touched the row
```

> Note: the output column header is `date` (mapped from `reg_date`), and `sra_url` is **derived** at output time (not stored), to keep the schema minimal.

---

### Task 1: Package scaffolding

**Files:**
- Create: `srw/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `data/.gitkeep` (empty; dir is otherwise gitignored)

- [ ] **Step 1: Create the empty package/test markers**

Create `srw/__init__.py` with a single line:

```python
"""sra-run-watch: daily harvester of newly registered INSDC sequencing runs."""
```

Create `tests/__init__.py` empty (0 bytes).

Create `data/.gitkeep` empty (0 bytes).

- [ ] **Step 2: Verify the package imports**

Run: `python3 -c "import srw; print('ok')"`
Expected: prints `ok`

- [ ] **Step 3: Commit**

```bash
git add srw/__init__.py tests/__init__.py data/.gitkeep
git commit -m "chore: package scaffolding for srw"
```

---

### Task 2: `accession_to_archive`

**Files:**
- Create: `srw/accession.py`
- Test: `tests/test_accession.py`

- [ ] **Step 1: Write the failing test**

`tests/test_accession.py`:

```python
import unittest
from srw.accession import accession_to_archive


class TestAccessionToArchive(unittest.TestCase):
    def test_srr_is_ncbi(self):
        self.assertEqual(accession_to_archive("SRR38673021"), "NCBI")

    def test_err_is_ena(self):
        self.assertEqual(accession_to_archive("ERR1358750"), "ENA")

    def test_drr_is_ddbj(self):
        self.assertEqual(accession_to_archive("DRR196884"), "DDBJ")

    def test_lowercase_prefix(self):
        self.assertEqual(accession_to_archive("srr1"), "NCBI")

    def test_unknown_prefix_returns_none(self):
        self.assertIsNone(accession_to_archive("XYZ123"))

    def test_empty_returns_none(self):
        self.assertIsNone(accession_to_archive(""))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_accession -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'srw.accession'`

- [ ] **Step 3: Write minimal implementation**

`srw/accession.py`:

```python
"""Map an INSDC run accession to its source archive by prefix."""

_ARCHIVE_BY_PREFIX = {"SRR": "NCBI", "ERR": "ENA", "DRR": "DDBJ"}


def accession_to_archive(accession):
    """Return 'NCBI'/'ENA'/'DDBJ' for a run accession, or None if unknown."""
    if not accession:
        return None
    return _ARCHIVE_BY_PREFIX.get(accession[:3].upper())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_accession -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add srw/accession.py tests/test_accession.py
git commit -m "feat: accession_to_archive prefix mapping"
```

---

### Task 3: CSV parsers (`gunzip_text`, `parse_livelist_csv`, `parse_fileinfo_csv`)

**Files:**
- Create: `srw/parsers.py`
- Test: `tests/test_parsers.py`

- [ ] **Step 1: Write the failing test**

`tests/test_parsers.py`:

```python
import gzip
import unittest
from srw.parsers import gunzip_text, parse_livelist_csv, parse_fileinfo_csv


LIVELIST = (
    "Accession,Type,Status,Received,Published,LastUpdate,LastMetaUpdate,"
    "ReplacedBy,BioSample,BioProject,Insdc\n"
    "SRP348566,STUDY,live,2021-11-30 13:23:02,2026-05-18 14:17:08,"
    "2026-05-18 14:17:08,2021-11-30 13:23:02,None,None,PRJNA784537,True\n"
    "SRR38673021,RUN,live,2026-05-18 02:00:00,2026-05-18 02:17:20,"
    "2026-05-18 02:17:20,2026-05-18 02:00:00,None,SAMN1,PRJNA1,True\n"
    "ERR1358750,RUN,live,2016-04-15 18:26:05,2016-04-15 18:27:22,"
    "2026-05-19 01:31:37,2018-11-25 16:09:37,None,SAMEA3928353,PRJEB7624,False\n"
)

FILEINFO = (
    "Accession,FileSize,FileMd5,FileDate\n"
    "SRR38673021,20017812,fb97e1031f43107c97cf99100d75fd3b,2026-05-18 02:17:20\n"
    "SRR38673016,22105709,b581e816f348c70598c7b7e9d9ee01de,2026-05-18 02:17:22\n"
)


class TestGunzip(unittest.TestCase):
    def test_roundtrip(self):
        raw = gzip.compress(b"hello\nworld\n")
        self.assertEqual(gunzip_text(raw), "hello\nworld\n")


class TestParseLivelist(unittest.TestCase):
    def test_only_run_rows(self):
        recs = parse_livelist_csv(LIVELIST)
        self.assertEqual([r["run_accession"] for r in recs], ["SRR38673021", "ERR1358750"])

    def test_fields(self):
        recs = parse_livelist_csv(LIVELIST)
        srr = recs[0]
        self.assertEqual(srr["archive"], "NCBI")
        self.assertEqual(srr["reg_date"], "2026-05-18")
        self.assertEqual(srr["source"], "ncbi")
        err = recs[1]
        self.assertEqual(err["archive"], "ENA")
        self.assertEqual(err["reg_date"], "2016-04-15")


class TestParseFileinfo(unittest.TestCase):
    def test_fields(self):
        recs = parse_fileinfo_csv(FILEINFO)
        self.assertEqual(len(recs), 2)
        r = recs[0]
        self.assertEqual(r["run_accession"], "SRR38673021")
        self.assertEqual(r["sra_bytes"], 20017812)
        self.assertEqual(r["sra_md5"], "fb97e1031f43107c97cf99100d75fd3b")
        self.assertEqual(r["source"], "ncbi")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_parsers -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'srw.parsers'`

- [ ] **Step 3: Write minimal implementation**

`srw/parsers.py`:

```python
"""Pure parsing of NCBI delta CSVs and ENA TSV into normalized records."""

import csv
import gzip
import io

from srw.accession import accession_to_archive


def gunzip_text(raw):
    """Decompress gzip bytes to a UTF-8 string."""
    return gzip.decompress(raw).decode("utf-8")


def _date_only(value):
    """'2026-05-18 02:17:20' -> '2026-05-18'; '' / 'None' -> None."""
    if not value or value == "None":
        return None
    return value.split(" ", 1)[0]


def _int_or_none(value):
    if value is None:
        return None
    value = value.strip()
    if value == "" or value == "None":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_livelist_csv(text):
    """Parse livelist.csv text, returning normalized records for RUN rows only."""
    records = []
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("Type") != "RUN":
            continue
        acc = row["Accession"]
        records.append(
            {
                "run_accession": acc,
                "archive": accession_to_archive(acc),
                "reg_date": _date_only(row.get("Published")),
                "source": "ncbi",
            }
        )
    return records


def parse_fileinfo_csv(text):
    """Parse fileinfo_runs.csv text into normalized records (sra size + md5)."""
    records = []
    for row in csv.DictReader(io.StringIO(text)):
        acc = row["Accession"]
        records.append(
            {
                "run_accession": acc,
                "archive": accession_to_archive(acc),
                "sra_bytes": _int_or_none(row.get("FileSize")),
                "sra_md5": row.get("FileMd5") or None,
                "source": "ncbi",
            }
        )
    return records
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_parsers -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add srw/parsers.py tests/test_parsers.py
git commit -m "feat: gunzip_text and NCBI livelist/fileinfo CSV parsers"
```

---

### Task 4: Merge NCBI delta (`parse_ncbi_delta`) and parse ENA TSV (`parse_ena_tsv`)

**Files:**
- Modify: `srw/parsers.py`
- Test: `tests/test_parsers.py` (append cases)

- [ ] **Step 1: Write the failing tests (append to `tests/test_parsers.py`)**

Add these imports at the top (extend the existing import line):

```python
from srw.parsers import (
    gunzip_text,
    parse_livelist_csv,
    parse_fileinfo_csv,
    parse_ncbi_delta,
    parse_ena_tsv,
)
```

Append these test classes:

```python
ENA_TSV = (
    "run_accession\tfirst_public\tbase_count\tfastq_bytes\tsra_bytes\tfastq_ftp\n"
    "DRR196884\t2025-10-01\t30197652282\t13397979872\t\t"
    "ftp.sra.ebi.ac.uk/vol1/fastq/DRR196/DRR196884/DRR196884.fastq.gz\n"
    "SRR38673021\t2026-05-18\t\t\t\t\n"
)


class TestParseNcbiDelta(unittest.TestCase):
    def test_merges_fileinfo_into_livelist(self):
        recs = parse_ncbi_delta(LIVELIST, FILEINFO)
        by_acc = {r["run_accession"]: r for r in recs}
        # union of livelist RUN rows + fileinfo rows
        self.assertIn("SRR38673021", by_acc)
        self.assertIn("ERR1358750", by_acc)
        self.assertIn("SRR38673016", by_acc)  # fileinfo-only
        # SRR38673021 carries both date (livelist) and sra_bytes (fileinfo)
        srr = by_acc["SRR38673021"]
        self.assertEqual(srr["reg_date"], "2026-05-18")
        self.assertEqual(srr["sra_bytes"], 20017812)
        # fileinfo-only row still has archive derived, no date
        f_only = by_acc["SRR38673016"]
        self.assertEqual(f_only["archive"], "NCBI")
        self.assertIsNone(f_only.get("reg_date"))
        self.assertEqual(f_only["sra_bytes"], 22105709)


class TestParseEnaTsv(unittest.TestCase):
    def test_fields(self):
        recs = parse_ena_tsv(ENA_TSV)
        by_acc = {r["run_accession"]: r for r in recs}
        drr = by_acc["DRR196884"]
        self.assertEqual(drr["archive"], "DDBJ")
        self.assertEqual(drr["reg_date"], "2025-10-01")
        self.assertEqual(drr["sequenced_bases"], 30197652282)
        self.assertEqual(drr["fastq_bytes"], "13397979872")
        self.assertIsNone(drr["sra_bytes"])  # empty -> None
        self.assertTrue(drr["fastq_ftp"].endswith("DRR196884.fastq.gz"))
        self.assertEqual(drr["source"], "ena")

    def test_empty_numeric_fields_become_none(self):
        recs = parse_ena_tsv(ENA_TSV)
        srr = {r["run_accession"]: r for r in recs}["SRR38673021"]
        self.assertIsNone(srr["sequenced_bases"])
        self.assertIsNone(srr["fastq_bytes"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_parsers -v`
Expected: FAIL — `ImportError: cannot import name 'parse_ncbi_delta'`

- [ ] **Step 3: Add implementation to `srw/parsers.py`**

Append to `srw/parsers.py`:

```python
def parse_ncbi_delta(livelist_text, fileinfo_text):
    """Merge livelist RUN rows and fileinfo rows into one record per accession."""
    merged = {}
    for rec in parse_livelist_csv(livelist_text):
        merged[rec["run_accession"]] = dict(rec)
    for rec in parse_fileinfo_csv(fileinfo_text):
        acc = rec["run_accession"]
        if acc in merged:
            target = merged[acc]
            if rec.get("sra_bytes") is not None:
                target["sra_bytes"] = rec["sra_bytes"]
            if rec.get("sra_md5") is not None:
                target["sra_md5"] = rec["sra_md5"]
        else:
            merged[acc] = dict(rec)
    return list(merged.values())


def _str_or_none(value):
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_ena_tsv(text):
    """Parse ENA Portal API read_run TSV into normalized records."""
    records = []
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    for row in reader:
        acc = row["run_accession"]
        records.append(
            {
                "run_accession": acc,
                "archive": accession_to_archive(acc),
                "reg_date": _str_or_none(row.get("first_public")),
                "sequenced_bases": _int_or_none(row.get("base_count")),
                "sra_bytes": _int_or_none(row.get("sra_bytes")),
                "fastq_bytes": _str_or_none(row.get("fastq_bytes")),
                "fastq_ftp": _str_or_none(row.get("fastq_ftp")),
                "source": "ena",
            }
        )
    return records
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_parsers -v`
Expected: PASS (6 tests total)

- [ ] **Step 5: Commit**

```bash
git add srw/parsers.py tests/test_parsers.py
git commit -m "feat: parse_ncbi_delta merge and parse_ena_tsv"
```

---

### Task 5: SQLite store — `connect`, `upsert` (insert path), `select_new`

**Files:**
- Create: `srw/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

`tests/test_store.py`:

```python
import unittest
from srw.store import connect, upsert, select_new


class TestStoreInsert(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_insert_new_records(self):
        recs = [
            {"run_accession": "SRR1", "archive": "NCBI", "reg_date": "2026-05-18",
             "sra_bytes": 100, "source": "ncbi"},
            {"run_accession": "ERR2", "archive": "ENA", "reg_date": "2026-05-18",
             "sequenced_bases": 500, "source": "ena"},
        ]
        new, updated = upsert(self.conn, recs, "2026-05-20")
        self.assertEqual((new, updated), (2, 0))
        rows = select_new(self.conn, "2026-05-20")
        self.assertEqual([r["run_accession"] for r in rows], ["ERR2", "SRR1"])
        srr = {r["run_accession"]: r for r in rows}["SRR1"]
        self.assertEqual(srr["sra_bytes"], 100)
        self.assertEqual(srr["first_seen"], "2026-05-20")
        self.assertEqual(srr["sources"], "ncbi")

    def test_select_new_filters_by_first_seen(self):
        upsert(self.conn, [{"run_accession": "SRR1", "source": "ncbi"}], "2026-05-19")
        upsert(self.conn, [{"run_accession": "SRR2", "source": "ncbi"}], "2026-05-20")
        rows = select_new(self.conn, "2026-05-20")
        self.assertEqual([r["run_accession"] for r in rows], ["SRR2"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_store -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'srw.store'`

- [ ] **Step 3: Write minimal implementation**

`srw/store.py`:

```python
"""SQLite store: the cumulative source of truth for all runs ever seen."""

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_accession   TEXT PRIMARY KEY,
    archive         TEXT,
    reg_date        TEXT,
    sequenced_bases INTEGER,
    sra_bytes       INTEGER,
    sra_md5         TEXT,
    fastq_bytes     TEXT,
    fastq_ftp       TEXT,
    first_seen      TEXT,
    last_updated    TEXT,
    sources         TEXT
);
"""

# Fields that upsert may fill in on an existing row (never overwrite a populated value).
_FILLABLE = (
    "archive",
    "reg_date",
    "sequenced_bases",
    "sra_bytes",
    "sra_md5",
    "fastq_bytes",
    "fastq_ftp",
)


def connect(path):
    """Open (and initialize) the SQLite DB at path. Use ':memory:' for tests."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _is_empty(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def _merge_sources(existing, new_source):
    parts = [s for s in (existing or "").split(",") if s]
    if new_source and new_source not in parts:
        parts.append(new_source)
    return ",".join(parts)


def upsert(conn, records, today):
    """Insert new accessions; fill empty fields on existing ones. Returns (new, updated)."""
    new_count = 0
    updated_count = 0
    for rec in records:
        acc = rec["run_accession"]
        row = conn.execute(
            "SELECT * FROM runs WHERE run_accession = ?", (acc,)
        ).fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO runs (run_accession, archive, reg_date, sequenced_bases,
                       sra_bytes, sra_md5, fastq_bytes, fastq_ftp,
                       first_seen, last_updated, sources)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    acc,
                    rec.get("archive"),
                    rec.get("reg_date"),
                    rec.get("sequenced_bases"),
                    rec.get("sra_bytes"),
                    rec.get("sra_md5"),
                    rec.get("fastq_bytes"),
                    rec.get("fastq_ftp"),
                    today,
                    today,
                    _merge_sources("", rec.get("source")),
                ),
            )
            new_count += 1
        else:
            updates = {}
            for field in _FILLABLE:
                if _is_empty(row[field]) and not _is_empty(rec.get(field)):
                    updates[field] = rec[field]
            new_sources = _merge_sources(row["sources"], rec.get("source"))
            if updates or new_sources != row["sources"]:
                set_clause = ", ".join(f"{f} = ?" for f in updates)
                params = list(updates.values())
                if set_clause:
                    set_clause += ", "
                set_clause += "sources = ?, last_updated = ?"
                params += [new_sources, today, acc]
                conn.execute(
                    f"UPDATE runs SET {set_clause} WHERE run_accession = ?", params
                )
                updated_count += 1
    conn.commit()
    return new_count, updated_count


def select_new(conn, day):
    """Return rows (as sqlite3.Row) whose first_seen == day, ordered by accession."""
    return conn.execute(
        "SELECT * FROM runs WHERE first_seen = ? ORDER BY run_accession", (day,)
    ).fetchall()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_store -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add srw/store.py tests/test_store.py
git commit -m "feat: sqlite store with insert and select_new"
```

---

### Task 6: SQLite store — merge rule (fill empty, never overwrite populated)

**Files:**
- Modify: none (behavior already implemented in Task 5)
- Test: `tests/test_store.py` (append cases that lock the merge contract)

- [ ] **Step 1: Write the failing tests (append to `tests/test_store.py`)**

Append this class:

```python
class TestStoreMerge(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_fills_empty_fields_from_later_feed(self):
        # day 0: NCBI gives date + sra_bytes, no bases
        upsert(self.conn, [{"run_accession": "SRR1", "archive": "NCBI",
                            "reg_date": "2026-05-18", "sra_bytes": 100,
                            "source": "ncbi"}], "2026-05-20")
        # ~2 weeks later: ENA fills bases + fastq, keeps sra_bytes
        new, updated = upsert(self.conn, [{"run_accession": "SRR1",
                              "sequenced_bases": 999, "fastq_bytes": "55",
                              "fastq_ftp": "ftp.x/y.fastq.gz", "source": "ena"}],
                              "2026-06-01")
        self.assertEqual((new, updated), (0, 1))
        row = self.conn.execute("SELECT * FROM runs WHERE run_accession='SRR1'").fetchone()
        self.assertEqual(row["sequenced_bases"], 999)
        self.assertEqual(row["sra_bytes"], 100)          # unchanged
        self.assertEqual(row["first_seen"], "2026-05-20")  # novelty preserved
        self.assertEqual(row["last_updated"], "2026-06-01")
        self.assertEqual(row["sources"], "ncbi,ena")

    def test_does_not_overwrite_populated_with_empty(self):
        upsert(self.conn, [{"run_accession": "SRR1", "sra_bytes": 100,
                            "source": "ncbi"}], "2026-05-20")
        # a later feed with an empty sra_bytes must not clobber the 100
        new, updated = upsert(self.conn, [{"run_accession": "SRR1",
                              "sra_bytes": None, "source": "ena"}], "2026-06-01")
        row = self.conn.execute("SELECT * FROM runs WHERE run_accession='SRR1'").fetchone()
        self.assertEqual(row["sra_bytes"], 100)
        # still counts as updated because a new source touched it
        self.assertEqual((new, updated), (0, 1))

    def test_idempotent_rerun_same_day(self):
        rec = {"run_accession": "SRR1", "sra_bytes": 100, "source": "ncbi"}
        upsert(self.conn, [rec], "2026-05-20")
        new, updated = upsert(self.conn, [rec], "2026-05-20")
        # nothing new, nothing to fill, source already present -> no-op update
        self.assertEqual((new, updated), (0, 0))
        count = self.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        self.assertEqual(count, 1)
```

- [ ] **Step 2: Run tests to verify they pass (behavior already implemented)**

Run: `python3 -m unittest tests.test_store -v`
Expected: PASS (5 tests total). If `test_does_not_overwrite_populated_with_empty` or `test_idempotent_rerun_same_day` fails, fix `upsert` in `srw/store.py` so that: (a) populated fields are never overwritten by empty values, and (b) when nothing changes and the source is already recorded, the row is left untouched and counted as neither new nor updated.

- [ ] **Step 3: Commit**

```bash
git add tests/test_store.py srw/store.py
git commit -m "test: lock merge contract (fill-empty, no-clobber, idempotent)"
```

---

### Task 7: Output — `compute_sra_url`, `write_daily_file`

**Files:**
- Create: `srw/output.py`
- Test: `tests/test_output.py`

- [ ] **Step 1: Write the failing test**

`tests/test_output.py`:

```python
import os
import tempfile
import unittest
from srw.output import compute_sra_url, write_daily_file, COLUMNS


class TestComputeSraUrl(unittest.TestCase):
    def test_srr_gets_odp_url(self):
        self.assertEqual(
            compute_sra_url("SRR38673021"),
            "https://sra-pub-run-odp.s3.amazonaws.com/sra/SRR38673021/SRR38673021",
        )

    def test_non_srr_returns_empty(self):
        self.assertEqual(compute_sra_url("ERR1358750"), "")
        self.assertEqual(compute_sra_url("DRR196884"), "")


class TestWriteDailyFile(unittest.TestCase):
    def test_writes_tsv_with_header_and_mapped_columns(self):
        rows = [
            {"run_accession": "SRR1", "reg_date": "2026-05-18", "sequenced_bases": None,
             "sra_bytes": 100, "fastq_bytes": None, "fastq_ftp": None},
            {"run_accession": "DRR2", "reg_date": "2025-10-01",
             "sequenced_bases": 30197652282, "sra_bytes": None,
             "fastq_bytes": "13397979872", "fastq_ftp": "ftp.x/y.fastq.gz"},
        ]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "new_runs_2026-05-20.tsv")
            write_daily_file(rows, path)
            with open(path, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        self.assertEqual(lines[0].split("\t"), COLUMNS)
        self.assertEqual(lines[0].split("\t")[1], "date")  # reg_date -> "date"
        srr = lines[1].split("\t")
        self.assertEqual(srr[0], "SRR1")
        self.assertEqual(srr[1], "2026-05-18")
        self.assertEqual(srr[2], "")  # None -> empty
        self.assertEqual(srr[3], "100")
        self.assertEqual(srr[6], "https://sra-pub-run-odp.s3.amazonaws.com/sra/SRR1/SRR1")
        drr = lines[2].split("\t")
        self.assertEqual(drr[6], "")  # non-SRR has no sra_url


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_output -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'srw.output'`

- [ ] **Step 3: Write minimal implementation**

`srw/output.py`:

```python
"""Write the dated TSV of runs first seen today."""

import csv

COLUMNS = [
    "run_accession",
    "date",
    "sequenced_bases",
    "sra_bytes",
    "fastq_bytes",
    "fastq_ftp",
    "sra_url",
]

_ODP = "https://sra-pub-run-odp.s3.amazonaws.com/sra/{acc}/{acc}"


def compute_sra_url(accession):
    """Public ODP S3 URL for an SRR .sra file; empty string for ERR/DRR."""
    if accession[:3].upper() == "SRR":
        return _ODP.format(acc=accession)
    return ""


def _cell(value):
    return "" if value is None else str(value)


def write_daily_file(rows, path):
    """Write rows (sqlite3.Row or dict) to a TSV at path with COLUMNS header."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(COLUMNS)
        for row in rows:
            acc = row["run_accession"]
            writer.writerow(
                [
                    acc,
                    _cell(row["reg_date"]),
                    _cell(row["sequenced_bases"]),
                    _cell(row["sra_bytes"]),
                    _cell(row["fastq_bytes"]),
                    _cell(row["fastq_ftp"]),
                    compute_sra_url(acc),
                ]
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_output -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add srw/output.py tests/test_output.py
git commit -m "feat: daily TSV writer and sra_url derivation"
```

---

### Task 8: Feeds — pure request builders + HTTP with retry

**Files:**
- Create: `srw/feeds.py`
- Test: `tests/test_feeds.py`

- [ ] **Step 1: Write the failing test**

`tests/test_feeds.py`:

```python
import unittest
import urllib.error
from srw.feeds import ncbi_delta_url, ena_search_params, http_with_retry


class TestRequestBuilders(unittest.TestCase):
    def test_ncbi_delta_url(self):
        base, ll, fi = ncbi_delta_url("2026-05-19")
        self.assertEqual(
            base,
            "https://ftp.ncbi.nlm.nih.gov/sra/reports/Mirroring/"
            "NCBI_SRA_Mirroring_20260519",
        )
        self.assertTrue(ll.endswith("/livelist.csv.gz"))
        self.assertTrue(fi.endswith("/fileinfo_runs.csv.gz"))

    def test_ena_search_params(self):
        p = ena_search_params("2026-04-20", "2026-05-20")
        self.assertEqual(p["result"], "read_run")
        self.assertEqual(p["format"], "tsv")
        self.assertIn("first_public>=2026-04-20", p["query"])
        self.assertIn("first_public<=2026-05-20", p["query"])
        self.assertIn("run_accession", p["fields"])
        self.assertIn("base_count", p["fields"])
        self.assertIn("fastq_ftp", p["fields"])


class TestHttpRetry(unittest.TestCase):
    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.URLError("boom")
            return b"ok"

        out = http_with_retry(flaky, retries=3, sleep=lambda s: None)
        self.assertEqual(out, b"ok")
        self.assertEqual(calls["n"], 3)

    def test_raises_after_exhausting_retries(self):
        def always_fail():
            raise urllib.error.URLError("boom")

        with self.assertRaises(urllib.error.URLError):
            http_with_retry(always_fail, retries=3, sleep=lambda s: None)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_feeds -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'srw.feeds'`

- [ ] **Step 3: Write minimal implementation**

`srw/feeds.py`:

```python
"""Network feeds: NCBI Mirroring delta and ENA Portal API.

Pure request builders and a retry wrapper are unit-tested; the fetch_*
orchestrators are exercised by tests with an injected http function and by the
opt-in smoke test.
"""

import urllib.error
import urllib.parse
import urllib.request

from srw.parsers import gunzip_text, parse_ncbi_delta, parse_ena_tsv

_NCBI_BASE = (
    "https://ftp.ncbi.nlm.nih.gov/sra/reports/Mirroring/NCBI_SRA_Mirroring_{ymd}"
)
_ENA_SEARCH = "https://www.ebi.ac.uk/ena/portal/api/search"
_ENA_FIELDS = "run_accession,first_public,base_count,fastq_bytes,sra_bytes,fastq_ftp"
_USER_AGENT = "sra-run-watch/0.1 (+https://github.com/inutano/sra-run-watch)"


def ncbi_delta_url(date_str):
    """date_str 'YYYY-MM-DD' -> (base_url, livelist_url, fileinfo_url)."""
    ymd = date_str.replace("-", "")
    base = _NCBI_BASE.format(ymd=ymd)
    return base, base + "/livelist.csv.gz", base + "/fileinfo_runs.csv.gz"


def ena_search_params(start_date, end_date):
    """Build the POST body params for an ENA read_run first_public-window query."""
    return {
        "result": "read_run",
        "query": (
            f"first_public>={start_date} AND first_public<={end_date}"
        ),
        "fields": _ENA_FIELDS,
        "format": "tsv",
        "limit": "0",
    }


def http_with_retry(call, retries=3, sleep=None, backoff=2.0):
    """Call a zero-arg fn, retrying URLError with exponential backoff."""
    import time

    sleep = sleep or time.sleep
    last = None
    for attempt in range(retries):
        try:
            return call()
        except urllib.error.URLError as exc:
            last = exc
            if attempt < retries - 1:
                sleep(backoff ** attempt)
    raise last


def _get_bytes(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _post_bytes(url, params, timeout=300):
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"User-Agent": _USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_feeds -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add srw/feeds.py tests/test_feeds.py
git commit -m "feat: feed request builders and http retry wrapper"
```

---

### Task 9: Feeds — `fetch_ncbi_delta` and `fetch_ena_sweep` orchestration

**Files:**
- Modify: `srw/feeds.py`
- Test: `tests/test_feeds.py` (append cases with injected http)

- [ ] **Step 1: Write the failing tests (append to `tests/test_feeds.py`)**

Extend the import line:

```python
from srw.feeds import (
    ncbi_delta_url,
    ena_search_params,
    http_with_retry,
    fetch_ncbi_delta,
    fetch_ena_sweep,
)
```

Add `import gzip` at the top, then append:

```python
LIVELIST = (
    "Accession,Type,Status,Received,Published,LastUpdate,LastMetaUpdate,"
    "ReplacedBy,BioSample,BioProject,Insdc\n"
    "SRR1,RUN,live,2026-05-18 02:00:00,2026-05-18 02:17:20,"
    "2026-05-18 02:17:20,2026-05-18 02:00:00,None,SAMN1,PRJNA1,True\n"
)
FILEINFO = "Accession,FileSize,FileMd5,FileDate\nSRR1,100,abc,2026-05-18 02:17:20\n"
ENA_TSV = (
    "run_accession\tfirst_public\tbase_count\tfastq_bytes\tsra_bytes\tfastq_ftp\n"
    "ERR1\t2026-05-10\t500\t55\t\tftp.x/y.fastq.gz\n"
)


class TestFetchNcbiDelta(unittest.TestCase):
    def test_fetches_and_parses(self):
        def fake_get(url):
            if url.endswith("/livelist.csv.gz"):
                return gzip.compress(LIVELIST.encode())
            if url.endswith("/fileinfo_runs.csv.gz"):
                return gzip.compress(FILEINFO.encode())
            raise AssertionError(url)

        recs = fetch_ncbi_delta("2026-05-19", get_bytes=fake_get)
        self.assertEqual(recs[0]["run_accession"], "SRR1")
        self.assertEqual(recs[0]["sra_bytes"], 100)

    def test_missing_dir_returns_empty(self):
        def fake_get(url):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

        recs = fetch_ncbi_delta("2099-01-01", get_bytes=fake_get)
        self.assertEqual(recs, [])


class TestFetchEnaSweep(unittest.TestCase):
    def test_fetches_and_parses(self):
        def fake_post(url, params):
            return ENA_TSV.encode()

        recs = fetch_ena_sweep("2026-04-20", "2026-05-20", post_bytes=fake_post)
        self.assertEqual(recs[0]["run_accession"], "ERR1")
        self.assertEqual(recs[0]["sequenced_bases"], 500)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_feeds -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_ncbi_delta'`

- [ ] **Step 3: Add implementation to `srw/feeds.py`**

Append to `srw/feeds.py`:

```python
def fetch_ncbi_delta(date_str, get_bytes=None):
    """Download + parse the NCBI Mirroring delta for a date. Missing dir -> []."""
    get_bytes = get_bytes or _get_bytes
    _base, ll_url, fi_url = ncbi_delta_url(date_str)
    try:
        ll_raw = http_with_retry(lambda: get_bytes(ll_url))
        fi_raw = http_with_retry(lambda: get_bytes(fi_url))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise
    return parse_ncbi_delta(gunzip_text(ll_raw), gunzip_text(fi_raw))


def fetch_ena_sweep(start_date, end_date, post_bytes=None):
    """Query the ENA Portal API for read_run rows in a first_public window."""
    post_bytes = post_bytes or _post_bytes
    params = ena_search_params(start_date, end_date)
    raw = http_with_retry(lambda: post_bytes(_ENA_SEARCH, params))
    return parse_ena_tsv(raw.decode("utf-8"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_feeds -v`
Expected: PASS (7 tests total)

- [ ] **Step 5: Commit**

```bash
git add srw/feeds.py tests/test_feeds.py
git commit -m "feat: fetch_ncbi_delta and fetch_ena_sweep orchestration"
```

---

### Task 10: Orchestrator `main()` + entry point

**Files:**
- Create: `sra_run_watch.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write the failing test**

`tests/test_main.py`:

```python
import os
import tempfile
import unittest
import sra_run_watch as cli


class TestRun(unittest.TestCase):
    def test_end_to_end_with_fake_feeds(self):
        ncbi_recs = [
            {"run_accession": "SRR1", "archive": "NCBI", "reg_date": "2026-05-18",
             "sra_bytes": 100, "source": "ncbi"},
        ]
        ena_recs = [
            {"run_accession": "ERR1", "archive": "ENA", "reg_date": "2026-05-10",
             "sequenced_bases": 500, "fastq_bytes": "55",
             "fastq_ftp": "ftp.x/y.fastq.gz", "sra_bytes": None, "source": "ena"},
        ]
        with tempfile.TemporaryDirectory() as d:
            result = cli.run(
                data_dir=d,
                today="2026-05-20",
                ncbi_lookback_days=2,
                ena_window_days=30,
                fetch_ncbi=lambda date: ncbi_recs if date == "2026-05-20" else [],
                fetch_ena=lambda start, end: ena_recs,
            )
            self.assertEqual(result["new"], 2)
            out = os.path.join(d, "new_runs_2026-05-20.tsv")
            self.assertTrue(os.path.exists(out))
            with open(out, encoding="utf-8") as fh:
                body = fh.read()
            self.assertIn("SRR1", body)
            self.assertIn("ERR1", body)
            # DB persisted
            self.assertTrue(os.path.exists(os.path.join(d, "runs.sqlite")))

    def test_rerun_same_day_is_idempotent(self):
        recs = [{"run_accession": "SRR1", "source": "ncbi"}]
        with tempfile.TemporaryDirectory() as d:
            kw = dict(data_dir=d, today="2026-05-20", ncbi_lookback_days=1,
                      ena_window_days=30,
                      fetch_ncbi=lambda date: recs, fetch_ena=lambda s, e: [])
            cli.run(**kw)
            result = cli.run(**kw)
            self.assertEqual(result["new"], 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_main -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sra_run_watch'`

- [ ] **Step 3: Write minimal implementation**

`sra_run_watch.py`:

```python
#!/usr/bin/env python3
"""sra-run-watch: daily harvester of newly registered INSDC sequencing runs."""

import argparse
import datetime
import os
import sys

from srw import feeds, output, store


def _daterange_back(today, days):
    """['today', 'today-1', ... ] for `days` entries, as YYYY-MM-DD strings."""
    base = datetime.date.fromisoformat(today)
    return [(base - datetime.timedelta(days=i)).isoformat() for i in range(days)]


def run(data_dir, today, ncbi_lookback_days, ena_window_days,
        fetch_ncbi=None, fetch_ena=None):
    """Execute one daily harvest. fetch_* are injectable for testing."""
    fetch_ncbi = fetch_ncbi or feeds.fetch_ncbi_delta
    fetch_ena = fetch_ena or feeds.fetch_ena_sweep

    os.makedirs(data_dir, exist_ok=True)
    conn = store.connect(os.path.join(data_dir, "runs.sqlite"))
    try:
        ncbi_ok = ena_ok = False
        total_new = total_updated = 0

        for date_str in _daterange_back(today, ncbi_lookback_days):
            try:
                recs = fetch_ncbi(date_str)
                ncbi_ok = True
            except Exception as exc:  # network/parse failure for one day
                sys.stderr.write(f"[warn] NCBI delta {date_str} failed: {exc}\n")
                continue
            n, u = store.upsert(conn, recs, today)
            total_new += n
            total_updated += u

        start = (datetime.date.fromisoformat(today)
                 - datetime.timedelta(days=ena_window_days)).isoformat()
        try:
            ena_recs = fetch_ena(start, today)
            ena_ok = True
            n, u = store.upsert(conn, ena_recs, today)
            total_new += n
            total_updated += u
        except Exception as exc:
            sys.stderr.write(f"[warn] ENA sweep failed: {exc}\n")

        if not ncbi_ok and not ena_ok:
            raise RuntimeError("both feeds failed; no data harvested")

        new_rows = store.select_new(conn, today)
        out_path = os.path.join(data_dir, f"new_runs_{today}.tsv")
        output.write_daily_file(new_rows, out_path)

        sys.stderr.write(
            f"[info] {today}: {len(new_rows)} new, {total_updated} updated; "
            f"ncbi_ok={ncbi_ok} ena_ok={ena_ok}; wrote {out_path}\n"
        )
        return {"new": len(new_rows), "updated": total_updated,
                "ncbi_ok": ncbi_ok, "ena_ok": ena_ok, "out_path": out_path}
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Daily INSDC new-run harvester")
    parser.add_argument("--data-dir", default="./data")
    parser.add_argument("--ncbi-lookback-days", type=int, default=3)
    parser.add_argument("--ena-window-days", type=int, default=30)
    parser.add_argument(
        "--date",
        default=datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
        help="processing date (UTC today by default)",
    )
    args = parser.parse_args(argv)
    try:
        run(
            data_dir=args.data_dir,
            today=args.date,
            ncbi_lookback_days=args.ncbi_lookback_days,
            ena_window_days=args.ena_window_days,
        )
    except Exception as exc:
        sys.stderr.write(f"[error] {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_main -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full suite**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS (all tests across all modules)

- [ ] **Step 6: Commit**

```bash
git add sra_run_watch.py tests/test_main.py
git commit -m "feat: orchestrator main() and CLI entry point"
```

---

### Task 11: Network smoke test (opt-in)

**Files:**
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Write the smoke test**

`tests/test_smoke.py`:

```python
import os
import tempfile
import unittest
import sra_run_watch as cli


@unittest.skipUnless(os.environ.get("SRW_SMOKE") == "1",
                     "network smoke test; set SRW_SMOKE=1 to run")
class TestSmoke(unittest.TestCase):
    def test_real_run_recent_date(self):
        # Use a date a few days back so the NCBI Mirroring dir certainly exists.
        import datetime
        date = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        with tempfile.TemporaryDirectory() as d:
            result = cli.run(
                data_dir=d, today=date,
                ncbi_lookback_days=1, ena_window_days=7,
            )
            # At least one feed must have succeeded and produced an output file.
            self.assertTrue(result["ncbi_ok"] or result["ena_ok"])
            self.assertTrue(os.path.exists(result["out_path"]))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the smoke test against live services**

Run: `SRW_SMOKE=1 python3 -m unittest tests.test_smoke -v`
Expected: PASS — exercises real NCBI FTP + ENA API, writes a TSV. (If it fails due to a transient network/service issue, re-run; do not weaken the assertions.)

- [ ] **Step 3: Confirm it is skipped by default**

Run: `python3 -m unittest tests.test_smoke -v`
Expected: `skipped` (1 test skipped)

- [ ] **Step 4: Commit**

```bash
git add tests/test_smoke.py
git commit -m "test: opt-in network smoke test"
```

---

### Task 12: Final verification and push

**Files:** none (verification only)

- [ ] **Step 1: Run the full offline suite**

Run: `python3 -m unittest discover -s tests -v`
Expected: all PASS, smoke test skipped.

- [ ] **Step 2: Manual end-to-end against a real recent date**

Run: `python3 sra_run_watch.py --date $(python3 -c "import datetime;print((datetime.date.today()-datetime.timedelta(days=3)).isoformat())") --ncbi-lookback-days 1 --ena-window-days 7`
Expected: exit code 0; a `data/new_runs_<date>.tsv` is written with the header
`run_accession  date  sequenced_bases  sra_bytes  fastq_bytes  fastq_ftp  sra_url`
and at least some rows. Inspect a few rows for sanity (SRR rows should have `sra_url`).

- [ ] **Step 3: Confirm runtime data is gitignored**

Run: `git status --porcelain`
Expected: `data/runs.sqlite` and `data/new_runs_*.tsv` do NOT appear (only `data/.gitkeep` is tracked).

- [ ] **Step 4: Push**

```bash
git push -u origin main
```

---

## Self-Review Notes

- **Spec coverage:** NCBI delta feed (Tasks 3–4, 8–9), ENA sweep (Tasks 4, 8–9), "new to us" novelty via `first_seen` (Tasks 5–6, 10), merge fill-empty/no-clobber rule (Task 6), daily TSV with exact columns + derived `sra_url` (Task 7), error handling per-feed + non-zero exit when both fail (Task 10), idempotency (Tasks 6, 10), unit tests on all pure functions + opt-in smoke test (Tasks 2–11), CLI config flags (Task 10), cron usage (README). All spec sections map to tasks.
- **Schema note vs spec:** spec listed `date` and `sra_url` columns; the plan uses `reg_date` in the DB (output header is still `date`) and derives `sra_url` at output rather than storing it. Intentional simplification; output is unchanged.
- **Type consistency:** record dict keys (`run_accession`, `archive`, `reg_date`, `sequenced_bases`, `sra_bytes`, `sra_md5`, `fastq_bytes`, `fastq_ftp`, `source`) are used identically across parsers, store, and output. `fetch_ncbi_delta(date, get_bytes=)` and `fetch_ena_sweep(start, end, post_bytes=)` signatures match their callers in `run()` (which wraps them as `fetch_ncbi(date)` / `fetch_ena(start, end)`).
