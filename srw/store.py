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
