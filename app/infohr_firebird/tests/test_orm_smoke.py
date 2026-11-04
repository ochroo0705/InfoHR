"""Everyday ORM queries on Firebird (firebird3-foundation Task 11, discovery tests).

One throwaway pair of related models (Author, Book) holds Mongolian and Latin text. Each test
runs one query family the HR app uses and asserts a real result. A family that fails on Firebird
is marked xfail (strict) with the exact error, so the suite stays green and the gap stays listed.
"""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.db import connections, models, transaction
from django.db.models import (
    Avg,
    Case,
    CharField,
    Count,
    Exists,
    F,
    Max,
    Min,
    OuterRef,
    Q,
    Subquery,
    Sum,
    TextField,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Length, Lower, Upper
from django.test.utils import CaptureQueriesContext, isolate_apps


def _define_shop() -> tuple[Any, Any]:
    class Author(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        name = models.CharField(max_length=80)
        age = models.IntegerField()
        joined = models.DateField()
        note = models.TextField(null=True)  # noqa: DJ001 - the tests need a real NULL text value

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_SM_AUTHOR"

    class Book(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        title = models.CharField(max_length=80)
        author = models.ForeignKey(Author, on_delete=models.CASCADE)
        price = models.DecimalField(max_digits=9, decimal_places=2)
        pages = models.IntegerField()

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_SM_BOOK"

    return Author, Book


def _seed(author: Any, book: Any, alias: str) -> None:
    olzii = author(name="Өлзий", age=30, joined=date(2026, 1, 15), note="first")
    olzii.save(using=alias)
    uuren = author(name="Үүрэн", age=41, joined=date(2025, 6, 1), note=None)
    uuren.save(using=alias)
    bat = author(name="Bat", age=25, joined=date(2026, 3, 10), note="new")
    bat.save(using=alias)
    book(title="Алтан зам", author=olzii, price=Decimal("10.50"), pages=200).save(using=alias)
    book(title="Хөх тэнгэр", author=olzii, price=Decimal("7.25"), pages=120).save(using=alias)
    book(title="River", author=bat, price=Decimal("3.00"), pages=80).save(using=alias)


def _drop_tables(connection: Any, *models_to_drop: Any) -> None:
    """Drop the tables of the given models that exist (a failed create must not leak a table)."""
    existing = set(connection.introspection.table_names())
    with connection.schema_editor() as editor:
        for model in models_to_drop:
            if model._meta.db_table in existing:
                editor.delete_model(model)


@pytest.fixture
def shop(fb_alias: str) -> Iterator[tuple[Any, Any]]:
    """Create the Author and Book tables with three authors and three books; drop them at teardown."""
    with isolate_apps("infohr_firebird"):
        author, book = _define_shop()
        connection = connections[fb_alias]
        try:
            with connection.schema_editor() as editor:
                editor.create_model(author)
                editor.create_model(book)
            _seed(author, book, fb_alias)
            yield author, book
        finally:
            _drop_tables(connection, book, author)


def _names(queryset: Any) -> set[str]:
    return {row.name for row in queryset}


def _id_of(model: Any, alias: str, name: str) -> int:
    return int(model.objects.using(alias).get(name=name).id)


# Count, exists and aggregates


def test_count(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    assert author.objects.using(fb_alias).count() == 3
    assert author.objects.using(fb_alias).filter(age__gte=30).count() == 2


def test_exists(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, book = shop
    assert author.objects.using(fb_alias).filter(name="Bat").exists()
    assert not author.objects.using(fb_alias).filter(age__gt=100).exists()
    assert book.objects.using(fb_alias).exists()


def test_aggregate_count_sum_min_max_avg(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    result = author.objects.using(fb_alias).aggregate(
        n=Count("id"), total=Sum("age"), low=Min("age"), high=Max("age"), average=Avg("age")
    )
    assert result["n"] == 3
    assert result["total"] == 96
    assert result["low"] == 25
    assert result["high"] == 41
    assert float(result["average"]) == pytest.approx(32.0)


# Joins and grouping


def test_annotate_count_over_join_with_filter(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    rows = author.objects.using(fb_alias).annotate(n=Count("book")).filter(n__gte=1)
    assert {row.name: row.n for row in rows} == {"Өлзий": 2, "Bat": 1}


def test_values_annotate_group_by(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, book = shop
    by_name = author.objects.using(fb_alias).values("name").annotate(n=Count("id")).order_by()
    assert {row["name"]: row["n"] for row in by_name} == {"Өлзий": 1, "Үүрэн": 1, "Bat": 1}
    olzii = _id_of(author, fb_alias, "Өлзий")
    bat = _id_of(author, fb_alias, "Bat")
    per_author = book.objects.using(fb_alias).values("author").annotate(n=Count("id"), pages=Sum("pages")).order_by()
    assert {row["author"]: (row["n"], row["pages"]) for row in per_author} == {olzii: (2, 320), bat: (1, 80)}


def test_values_list_flat(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    assert list(author.objects.using(fb_alias).order_by("id").values_list("age", flat=True)) == [30, 41, 25]


def test_distinct(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    rows = author.objects.using(fb_alias).filter(book__pages__gt=0).distinct()
    assert sorted(row.name for row in rows) == sorted(["Өлзий", "Bat"])


# Ordering and slicing


def test_order_by_ascending_and_descending(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    assert list(author.objects.using(fb_alias).order_by("age").values_list("age", flat=True)) == [25, 30, 41]
    assert list(author.objects.using(fb_alias).order_by("-age").values_list("age", flat=True)) == [41, 30, 25]


def test_order_by_two_fields(shop: tuple[Any, Any], fb_alias: str) -> None:
    _, book = shop
    titles = book.objects.using(fb_alias).order_by("author", "-price").values_list("title", flat=True)
    assert list(titles) == ["Алтан зам", "Хөх тэнгэр", "River"]


def test_slice_limit_and_offset(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    qs = author.objects.using(fb_alias).order_by("id")
    assert [row.name for row in qs[:2]] == ["Өлзий", "Үүрэн"]
    assert [row.name for row in qs[1:3]] == ["Үүрэн", "Bat"]


def test_first_and_last(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    assert author.objects.using(fb_alias).first().name == "Өлзий"
    assert author.objects.using(fb_alias).last().name == "Bat"


# Writes


def test_get_or_create_and_update_or_create(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    _, created = author.objects.using(fb_alias).get_or_create(
        name="New", defaults={"age": 20, "joined": date(2026, 5, 1)}
    )
    assert created
    _, created_again = author.objects.using(fb_alias).get_or_create(
        name="New", defaults={"age": 99, "joined": date(2026, 5, 1)}
    )
    assert not created_again
    updated, created_update = author.objects.using(fb_alias).update_or_create(name="New", defaults={"age": 21})
    assert not created_update
    assert updated.age == 21
    assert author.objects.using(fb_alias).count() == 4


def test_bulk_create_then_read_back(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    author.objects.using(fb_alias).bulk_create(
        [
            author(name="Bulk1", age=1, joined=date(2026, 2, 2)),
            author(name="Bulk2", age=2, joined=date(2026, 2, 2)),
        ]
    )
    assert author.objects.using(fb_alias).count() == 5
    assert _names(author.objects.using(fb_alias).filter(name__startswith="Bulk")) == {"Bulk1", "Bulk2"}


def test_update_with_f_expression(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    assert author.objects.using(fb_alias).filter(name="Bat").update(age=F("age") + 1) == 1
    assert author.objects.using(fb_alias).get(name="Bat").age == 26


def test_delete_cascades_to_books(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, book = shop
    deleted, _ = author.objects.using(fb_alias).filter(name="Bat").delete()
    assert deleted == 2  # the author and her one book
    assert book.objects.using(fb_alias).count() == 2
    assert author.objects.using(fb_alias).count() == 2


def test_atomic_rolls_back_on_exception(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    with pytest.raises(RuntimeError):
        with transaction.atomic(using=fb_alias):
            author.objects.using(fb_alias).create(name="Temp", age=1, joined=date(2026, 1, 1))
            raise RuntimeError("boom")
    assert author.objects.using(fb_alias).count() == 3
    with transaction.atomic(using=fb_alias):
        author.objects.using(fb_alias).create(name="Kept", age=1, joined=date(2026, 1, 1))
    assert author.objects.using(fb_alias).count() == 4


# Filters


def test_q_or(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    rows = author.objects.using(fb_alias).filter(Q(name="Bat") | Q(age__gt=40))
    assert _names(rows) == {"Bat", "Үүрэн"}


def test_exclude(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    assert _names(author.objects.using(fb_alias).exclude(age__lt=30)) == {"Өлзий", "Үүрэн"}


def test_in_with_list(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    ids = [_id_of(author, fb_alias, "Өлзий"), _id_of(author, fb_alias, "Bat")]
    assert _names(author.objects.using(fb_alias).filter(id__in=ids)) == {"Өлзий", "Bat"}


def test_in_with_subquery(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, book = shop
    rows = author.objects.using(fb_alias).filter(id__in=book.objects.using(fb_alias).values("author"))
    assert _names(rows) == {"Өлзий", "Bat"}


def test_isnull(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    assert _names(author.objects.using(fb_alias).filter(note__isnull=True)) == {"Үүрэн"}
    assert _names(author.objects.using(fb_alias).filter(book__isnull=True)) == {"Үүрэн"}


def test_range(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    assert _names(author.objects.using(fb_alias).filter(age__range=(25, 30))) == {"Өлзий", "Bat"}


def test_gte_and_lt(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    assert _names(author.objects.using(fb_alias).filter(age__gte=26, age__lt=41)) == {"Өлзий"}


def test_contains_mongolian(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    assert _names(author.objects.using(fb_alias).filter(name__contains="лзи")) == {"Өлзий"}


def test_icontains(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    assert _names(author.objects.using(fb_alias).filter(name__icontains="ЛЗИ")) == {"Өлзий"}
    assert _names(author.objects.using(fb_alias).filter(name__icontains="BAT")) == {"Bat"}


def test_startswith_mongolian(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    assert _names(author.objects.using(fb_alias).filter(name__startswith="Ө")) == {"Өлзий"}


def test_iexact_mongolian(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    assert _names(author.objects.using(fb_alias).filter(name__iexact="өлзий")) == {"Өлзий"}


# Related objects


def test_select_related(shop: tuple[Any, Any], fb_alias: str) -> None:
    _, book = shop
    river = book.objects.using(fb_alias).select_related("author").get(title="River")
    with CaptureQueriesContext(connections[fb_alias]) as ctx:
        assert river.author.name == "Bat"
    assert ctx.captured_queries == []


def test_prefetch_related(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    with CaptureQueriesContext(connections[fb_alias]) as ctx:
        authors = list(author.objects.using(fb_alias).prefetch_related("book_set").order_by("id"))
        counts = {row.name: len(row.book_set.all()) for row in authors}
    assert counts == {"Өлзий": 2, "Үүрэн": 0, "Bat": 1}
    assert len(ctx.captured_queries) == 2


def test_iterator(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    assert [row.name for row in author.objects.using(fb_alias).order_by("id").iterator()] == [
        "Өлзий",
        "Үүрэн",
        "Bat",
    ]


def test_subquery_with_outerref(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, book = shop
    top_price = Subquery(
        book.objects.filter(author=OuterRef("pk")).order_by("-price").values("price")[:1],
        output_field=models.DecimalField(max_digits=9, decimal_places=2),
    )
    rows = author.objects.using(fb_alias).annotate(top=top_price)
    assert {row.name: row.top for row in rows} == {"Өлзий": Decimal("10.50"), "Үүрэн": None, "Bat": Decimal("3.00")}


def test_exists_subquery(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, book = shop
    has_books = Exists(book.objects.filter(author=OuterRef("pk")))
    rows = author.objects.using(fb_alias).annotate(has_books=has_books).filter(has_books=True)
    assert _names(rows) == {"Өлзий", "Bat"}


# Expressions and functions


def test_case_when(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    band = Case(When(age__gte=35, then=Value("old")), default=Value("young"), output_field=CharField())
    rows = author.objects.using(fb_alias).annotate(band=band)
    assert {row.name: row.band for row in rows} == {"Өлзий": "young", "Үүрэн": "old", "Bat": "young"}


def test_coalesce(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    rows = author.objects.using(fb_alias).annotate(shown=Coalesce("note", Value("-"), output_field=TextField()))
    assert {row.name: row.shown for row in rows} == {"Өлзий": "first", "Үүрэн": "-", "Bat": "new"}


def test_lower_upper_length(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    bat = author.objects.using(fb_alias).annotate(l=Lower("name"), u=Upper("name"), n=Length("name")).get(name="Bat")
    assert (bat.l, bat.u, bat.n) == ("bat", "BAT", 3)
    olzii = author.objects.using(fb_alias).annotate(u=Upper("name"), n=Length("name")).get(name="Өлзий")
    assert (olzii.u, olzii.n) == ("ӨЛЗИЙ", 5)


# Dates


def test_date_year_filter(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    assert _names(author.objects.using(fb_alias).filter(joined__year=2026)) == {"Өлзий", "Bat"}


def test_date_gte_filter(shop: tuple[Any, Any], fb_alias: str) -> None:
    author, _ = shop
    assert _names(author.objects.using(fb_alias).filter(joined__gte=date(2026, 2, 1))) == {"Bat"}
