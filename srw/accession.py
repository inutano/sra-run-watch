"""Map an INSDC run accession to its source archive by prefix."""

_ARCHIVE_BY_PREFIX = {"SRR": "NCBI", "ERR": "ENA", "DRR": "DDBJ"}


def accession_to_archive(accession):
    """Return 'NCBI'/'ENA'/'DDBJ' for a run accession, or None if unknown."""
    if not accession:
        return None
    return _ARCHIVE_BY_PREFIX.get(accession[:3].upper())
