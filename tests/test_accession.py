import unittest
from srw.accession import accession_to_archive


class TestAccessionToArchive(unittest.TestCase):
    def test_srr_is_ncbi(self):
        self.assertEqual(accession_to_archive("SRR38673021"), "NCBI")

    def test_err_is_ena(self):
        self.assertEqual(accession_to_archive("ERR1358750"), "ENA")

    def test_drr_is_ddbj(self):
        self.assertEqual(accession_to_archive("DRR196884"), "DDBJ")

    def test_lowercase_prefix(self):
        self.assertEqual(accession_to_archive("srr1"), "NCBI")

    def test_unknown_prefix_returns_none(self):
        self.assertIsNone(accession_to_archive("XYZ123"))

    def test_empty_returns_none(self):
        self.assertIsNone(accession_to_archive(""))


if __name__ == "__main__":
    unittest.main()
