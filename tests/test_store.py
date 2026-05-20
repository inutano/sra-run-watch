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


if __name__ == "__main__":
    unittest.main()
