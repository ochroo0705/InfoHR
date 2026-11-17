from pathlib import Path

from django.core.management import call_command


def test_route_inventory_writes_rows_and_step_counts(tmp_path: Path) -> None:
    out = tmp_path / "inventory.md"

    call_command("route_inventory", str(out))

    lines = out.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("| /employees/ |") for line in lines)
    assert any(line.startswith("| /apply/") for line in lines)
    assert "## Routes per step" in lines
    assert not any(line.startswith("| /admin") for line in lines)
