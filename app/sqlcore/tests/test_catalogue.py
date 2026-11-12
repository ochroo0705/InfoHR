from sqlcore.catalogue import Catalogue, Column, View


def _view(name: str) -> View:
    return View(name=name, description=f"{name} description", columns=(Column("ID", "identifier"),))


def test_restrict_keeps_only_named_views() -> None:
    catalogue = Catalogue(views=(_view("GOV_A"), _view("GOV_B")))

    restricted = catalogue.restrict(["GOV_A"])

    assert restricted.view_names() == frozenset({"GOV_A"})


def test_names_are_case_insensitive() -> None:
    catalogue = Catalogue(views=(_view("GOV_A"),))

    found = catalogue.get("gov_a")

    assert found is not None
    assert found.name == "GOV_A"


def test_new_fields_default_to_empty() -> None:
    column = Column("ID", "identifier")
    view = _view("GOV_A")

    assert column.description_mn == ""
    assert view.description_mn == ""
    assert view.rules == ()
    assert view.reviewed_by == ""
    assert view.reviewed_on == ""
