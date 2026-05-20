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
