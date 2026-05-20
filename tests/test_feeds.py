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
