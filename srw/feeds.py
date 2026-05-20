"""Network feeds: NCBI Mirroring delta and ENA Portal API.

Pure request builders and a retry wrapper are unit-tested; the fetch_*
orchestrators are exercised by tests with an injected http function and by the
opt-in smoke test.
"""

import urllib.error
import urllib.parse
import urllib.request

from srw.parsers import gunzip_text, parse_ncbi_delta, parse_ena_tsv

_NCBI_BASE = (
    "https://ftp.ncbi.nlm.nih.gov/sra/reports/Mirroring/NCBI_SRA_Mirroring_{ymd}"
)
_ENA_SEARCH = "https://www.ebi.ac.uk/ena/portal/api/search"
_ENA_FIELDS = "run_accession,first_public,base_count,fastq_bytes,sra_bytes,fastq_ftp"
_USER_AGENT = "sra-run-watch/0.1 (+https://github.com/inutano/sra-run-watch)"


def ncbi_delta_url(date_str):
    """date_str 'YYYY-MM-DD' -> (base_url, livelist_url, fileinfo_url)."""
    ymd = date_str.replace("-", "")
    base = _NCBI_BASE.format(ymd=ymd)
    return base, base + "/livelist.csv.gz", base + "/fileinfo_runs.csv.gz"


def ena_search_params(start_date, end_date):
    """Build the POST body params for an ENA read_run first_public-window query."""
    return {
        "result": "read_run",
        "query": (
            f"first_public>={start_date} AND first_public<={end_date}"
        ),
        "fields": _ENA_FIELDS,
        "format": "tsv",
        "limit": "0",
    }


def http_with_retry(call, retries=3, sleep=None, backoff=2.0):
    """Call a zero-arg fn, retrying URLError with exponential backoff."""
    import time

    sleep = sleep or time.sleep
    last = None
    for attempt in range(retries):
        try:
            return call()
        except urllib.error.URLError as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code < 500:
                raise
            last = exc
            if attempt < retries - 1:
                sleep(backoff ** attempt)
    raise last


def _get_bytes(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _post_bytes(url, params, timeout=300):
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"User-Agent": _USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_ncbi_delta(date_str, get_bytes=None):
    """Download + parse the NCBI Mirroring delta for a date. Missing dir -> []."""
    get_bytes = get_bytes or _get_bytes
    _base, ll_url, fi_url = ncbi_delta_url(date_str)
    try:
        ll_raw = http_with_retry(lambda: get_bytes(ll_url))
        fi_raw = http_with_retry(lambda: get_bytes(fi_url))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise
    return parse_ncbi_delta(gunzip_text(ll_raw), gunzip_text(fi_raw))


def fetch_ena_sweep(start_date, end_date, post_bytes=None):
    """Query the ENA Portal API for read_run rows in a first_public window."""
    post_bytes = post_bytes or _post_bytes
    params = ena_search_params(start_date, end_date)
    raw = http_with_retry(lambda: post_bytes(_ENA_SEARCH, params))
    return parse_ena_tsv(raw.decode("utf-8"))
