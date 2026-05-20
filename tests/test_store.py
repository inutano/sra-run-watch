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
