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
