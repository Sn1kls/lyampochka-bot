import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "scripts"))  # the export imports its sibling export_volyn_queues
spec = importlib.util.spec_from_file_location(
    "export_volyn_outages", ROOT / "scripts" / "export_volyn_outages.py"
)
assert spec and spec.loader
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def test_emergency_and_planned_rows_are_kept_and_schedule_rows_left_out() -> None:
    rows = export.outage_rows((FIXTURES / "voe_outages_lutsk.html").read_text())

    assert Counter(row[4] for row in rows) == {"planned": 6, "emergency": 3}
    assert (
        "Луцький",
        "Луцьк",
        "Андрія Марцинюка",
        ("1", "3", "9"),
        "emergency",
        "2026-11-26 10:10",
        "2026-11-26 16:00",
        "Аварійний випадок в мережах",
    ) in rows


def test_nothing_found_is_an_empty_answer() -> None:
    assert export.outage_rows((FIXTURES / "voe_outages_none.html").read_text()) == []


def test_a_changed_layout_stops_the_export() -> None:
    page = (FIXTURES / "voe_outages_none.html").read_text().replace("вимкнень не знайдено", "")

    with pytest.raises(SystemExit):
        export.outage_rows(page)
