import os
import tempfile
import unittest
import sra_run_watch as cli


@unittest.skipUnless(os.environ.get("SRW_SMOKE") == "1",
                     "network smoke test; set SRW_SMOKE=1 to run")
class TestSmoke(unittest.TestCase):
    def test_real_run_recent_date(self):
        # Use a date a few days back so the NCBI Mirroring dir certainly exists.
        import datetime
        date = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        with tempfile.TemporaryDirectory() as d:
            result = cli.run(
                data_dir=d, today=date,
                ncbi_lookback_days=1, ena_window_days=7,
            )
            # At least one feed must have succeeded and produced an output file.
            self.assertTrue(result["ncbi_ok"] or result["ena_ok"])
            self.assertTrue(os.path.exists(result["out_path"]))


if __name__ == "__main__":
    unittest.main()
