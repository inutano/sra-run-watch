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
