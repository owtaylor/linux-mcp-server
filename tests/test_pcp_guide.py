"""Tests for the docs://pcp metrics guide resource.

The guide exists so models stop inventing PCP metric names, so the name checks
below are the point of this file: a name that drifts out of the real PMNS makes
the guide worse than useless. The reference lists are ``pminfo -t`` and
``pminfo -t -a <archive>`` captured from a stock RHEL 10 install with a default
pmlogger configuration.
"""

import re

from pathlib import Path

import pytest

from linux_mcp_server.utils.pcp import PCP_GUIDE_URI


DATA_DIR = Path(__file__).parent / "data"

#: The guide is loaded into a model's context on demand, so it has to stay small
#: enough that reading it is cheaper than the pcp_list_metrics dump it replaces.
MAX_GUIDE_BYTES = 20_000

#: Metrics that are in the PMNS but not recorded by a default pmlogger config.
#: They only work against the live system, and the guide has to say so.
LIVE_ONLY = {
    "network.tcpconn.established",
    "network.tcpconn.time_wait",
    "network.tcpconn.close_wait",
}


def _read_names(filename: str) -> set[str]:
    """The metric names in a captured pminfo listing, dropping any help text."""
    lines = (DATA_DIR / filename).read_text().splitlines()
    return {line.split(maxsplit=1)[0] for line in lines if line.strip()}


@pytest.fixture(scope="module")
def guide() -> str:
    from linux_mcp_server.server import pcp_guide

    return pcp_guide()


@pytest.fixture(scope="module")
def guide_metrics(guide: str) -> set[str]:
    """Every dotted, backticked name in the guide, which is how it cites metrics.

    Subtree prefixes such as ``kernel.cpu.util`` are deliberately written without
    backticks in the guide, since they are not queryable names.
    """
    return set(re.findall(r"`([a-z][a-z0-9_]*(?:\.[a-zA-Z0-9_]+)+)`", guide))


def test_guide_cites_metrics(guide_metrics: set[str]):
    assert len(guide_metrics) > 100, "guide should cover the common metrics across all subsystems"


def test_every_metric_exists(guide_metrics: set[str]):
    """No invented names: every cited metric is in the RHEL 10 PMNS."""
    unknown = guide_metrics - _read_names("pcp-metrics-rhel10.txt")
    assert unknown == set(), f"guide cites metrics that do not exist: {sorted(unknown)}"


def test_archived_metrics_are_not_marked_live_only(guide_metrics: set[str], guide: str):
    """A metric a default pmlogger records should not be written off as live only."""
    logged = _read_names("pcp-metrics-rhel10-logged.txt")
    mislabelled = {name for name in guide_metrics & logged & LIVE_ONLY}
    assert mislabelled == set(), f"metrics marked live only but actually archived: {sorted(mislabelled)}"


def test_unarchived_metrics_are_marked_live_only(guide_metrics: set[str], guide: str):
    """Anything a default pmlogger misses must be flagged, or historical queries mislead."""
    logged = _read_names("pcp-metrics-rhel10-logged.txt")
    lines = guide.splitlines()

    for name in sorted(guide_metrics - logged):
        # The marker may sit on the line after the name when an entry wraps.
        cited = [i for i, line in enumerate(lines) if f"`{name}`" in line]
        assert cited, f"{name} not found on its own line"
        assert any("[live only]" in "\n".join(lines[i : i + 2]) for i in cited), (
            f"{name} is not recorded by a default pmlogger but is not marked [live only]"
        )


def _catalog_entries(guide: str) -> list[str]:
    """Each catalog bullet, joined with the continuation lines it wraps onto.

    Only bullets count. Metrics are also named in the surrounding prose, and
    attributing a prose mention to whichever bullet happens to precede it would
    check the annotations of an unrelated metric.
    """
    entries: list[str] = []
    for line in guide.splitlines():
        if line.lstrip().startswith("- "):
            entries.append(line.strip())
        elif entries and line.startswith("  ") and line.strip():
            entries[-1] += " " + line.strip()
        elif not line.strip():
            entries.append("")  # a blank line ends any open bullet
    return [e for e in entries if e]


def _catalog_entry(guide: str, name: str) -> str | None:
    """The catalog bullet that *defines* ``name``, or None if nothing does.

    An entry reads ``- `a`, `b` — description [markers]``. Only the names before
    the dash are defined by it; ones in the description are cross-references to
    an entry elsewhere, and carry no annotations of their own.
    """
    defining = [e for e in _catalog_entries(guide) if f"`{name}`" in e.split("—")[0]]
    assert len(defining) <= 1, f"{name} is defined by {len(defining)} catalog entries; annotations could disagree"
    return defining[0] if defining else None


@pytest.fixture(scope="module")
def declared_semantics() -> dict[str, tuple[str, str]]:
    """``pminfo -d`` semantics and instancing, keyed by metric name."""
    rows = (DATA_DIR / "pcp-metrics-rhel10-semantics.tsv").read_text().splitlines()
    parsed = {}
    for row in rows:
        if row.startswith("#"):
            continue
        name, semantics, instancing, _units = row.split("\t")
        parsed[name] = (semantics, instancing)
    return parsed


def test_every_catalog_metric_resolves_against_an_archive(
    guide: str, guide_metrics: set[str], declared_semantics: dict[str, tuple[str, str]]
):
    """Listing a metric the archive cannot resolve just buys the caller a failed query.

    ``pminfo -a <archive>`` names derived metrics whether or not their definitions
    bind, so presence in the logged list is not enough; the semantics capture is the
    one that actually tried to look each descriptor up.
    """
    unresolved = []
    for name in sorted(guide_metrics - declared_semantics.keys()):
        entry = _catalog_entry(guide, name)
        if entry is not None and "[live only]" not in entry:
            unresolved.append(name)
    assert unresolved == [], f"catalog metrics with no descriptor in the archive: {unresolved}"


@pytest.mark.parametrize("marker", ["[counter]", "[gauge]"])
def test_counter_and_gauge_markers_match_pcp(
    guide: str, guide_metrics: set[str], declared_semantics: dict[str, tuple[str, str]], marker: str
):
    """A counter read as a gauge is reported as a rate and silently misinterpreted."""
    wrong = []
    for name in sorted(guide_metrics & declared_semantics.keys()):
        entry = _catalog_entry(guide, name)
        if entry is None:  # cited in prose only, not a catalog entry
            continue
        semantics, _ = declared_semantics[name]
        expected = "[counter]" if semantics == "counter" else "[gauge]"
        if (marker == expected) != (marker in entry):
            wrong.append(f"{name} is {semantics!r} but its entry {'omits' if marker == expected else 'has'} {marker}")
    assert wrong == [], "\n".join(wrong)


def test_per_instance_markers_match_pcp(
    guide: str, guide_metrics: set[str], declared_semantics: dict[str, tuple[str, str]]
):
    """An unflagged instance domain means unexpected `metric-instance` columns."""
    wrong = []
    for name in sorted(guide_metrics & declared_semantics.keys()):
        entry = _catalog_entry(guide, name)
        if entry is None:
            continue
        _, instancing = declared_semantics[name]
        if (instancing == "instanced") != ("[per-" in entry):
            wrong.append(
                f"{name} is {instancing} but its entry {'lacks' if instancing == 'instanced' else 'has'} a [per-X] marker"
            )
    assert wrong == [], "\n".join(wrong)


def test_guide_fits_in_budget(guide: str):
    size = len(guide.encode())
    assert size <= MAX_GUIDE_BYTES, f"guide is {size} bytes, over the {MAX_GUIDE_BYTES} byte budget"


async def test_guide_is_readable(mcp_client):
    result = await mcp_client.read_resource(PCP_GUIDE_URI)

    assert len(result) == 1
    assert result[0].mimeType == "text/markdown"
    assert "# Performance Co-Pilot (PCP) metrics guide" in result[0].text
