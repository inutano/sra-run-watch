import unittest
import urllib.error
import gzip
from srw.feeds import (
    ncbi_delta_url,
    ena_search_params,
    http_with_retry,
    fetch_ncbi_delta,
    fetch_ena_sweep,
)


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


if __name__ == "__main__":
    unittest.main()
