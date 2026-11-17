import json

from django.core.management import call_command


def test_export_openapi_writes_schema(tmp_path) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "o.json"

    call_command("export_openapi", str(out))

    schema = json.loads(out.read_text(encoding="utf-8"))
    assert "/api/v1/meta" in schema["paths"]
    assert "/api/v1/nav" in schema["paths"]
    assert "/api/v1/auth/login" in schema["paths"]
    assert out.read_text(encoding="utf-8").endswith("}\n")
