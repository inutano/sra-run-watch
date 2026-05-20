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
