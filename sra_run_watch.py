#!/usr/bin/env python3
"""sra-run-watch: daily harvester of newly registered INSDC sequencing runs."""

import argparse
import datetime
import os
import sys

from srw import feeds, output, store


def _daterange_back(today, days):
    """['today', 'today-1', ... ] for `days` entries, as YYYY-MM-DD strings."""
    base = datetime.date.fromisoformat(today)
    return [(base - datetime.timedelta(days=i)).isoformat() for i in range(days)]


def run(data_dir, today, ncbi_lookback_days, ena_window_days,
        fetch_ncbi=None, fetch_ena=None):
    """Execute one daily harvest. fetch_* are injectable for testing."""
    fetch_ncbi = fetch_ncbi or feeds.fetch_ncbi_delta
    fetch_ena = fetch_ena or feeds.fetch_ena_sweep

    os.makedirs(data_dir, exist_ok=True)
    conn = store.connect(os.path.join(data_dir, "runs.sqlite"))
    try:
        ncbi_ok = ena_ok = False
        total_updated = 0

        for date_str in _daterange_back(today, ncbi_lookback_days):
            try:
                recs = fetch_ncbi(date_str)
                _new, updated = store.upsert(conn, recs, today)
                total_updated += updated
                ncbi_ok = True
            except Exception as exc:  # one day's fetch/store failure is non-fatal
                sys.stderr.write(f"[warn] NCBI delta {date_str} failed: {exc}\n")
                continue

        start = (datetime.date.fromisoformat(today)
                 - datetime.timedelta(days=ena_window_days)).isoformat()
        try:
            ena_recs = fetch_ena(start, today)
            _new, updated = store.upsert(conn, ena_recs, today)
            total_updated += updated
            ena_ok = True
        except Exception as exc:
            sys.stderr.write(f"[warn] ENA sweep failed: {exc}\n")

        if not ncbi_ok and not ena_ok:
            raise RuntimeError("both feeds failed; no data harvested")

        new_rows = store.select_new(conn, today)
        out_path = os.path.join(data_dir, f"new_runs_{today}.tsv")
        output.write_daily_file(new_rows, out_path)

        sys.stderr.write(
            f"[info] {today}: {len(new_rows)} new, {total_updated} updated; "
            f"ncbi_ok={ncbi_ok} ena_ok={ena_ok}; wrote {out_path}\n"
        )
        return {"new": len(new_rows), "updated": total_updated,
                "ncbi_ok": ncbi_ok, "ena_ok": ena_ok, "out_path": out_path}
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Daily INSDC new-run harvester")
    parser.add_argument("--data-dir", default="./data")
    parser.add_argument("--ncbi-lookback-days", type=int, default=3)
    parser.add_argument("--ena-window-days", type=int, default=30)
    parser.add_argument(
        "--date",
        default=datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
        help="processing date (UTC today by default)",
    )
    args = parser.parse_args(argv)
    try:
        run(
            data_dir=args.data_dir,
            today=args.date,
            ncbi_lookback_days=args.ncbi_lookback_days,
            ena_window_days=args.ena_window_days,
        )
    except Exception as exc:
        sys.stderr.write(f"[error] {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
