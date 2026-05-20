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
