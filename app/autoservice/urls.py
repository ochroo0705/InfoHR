from django.urls import path

from autoservice import repairs, views, views_cards, views_discounts, views_quotes, views_repairs, views_settings

app_name = "autoservice"


def _shop(prefix: str, kind: int, tag: str) -> list:  # type: ignore[type-arg]
    """The repair routes of one shop: aggregate (`repairs/...`) or body (`body-repairs/...`)."""
    k = {"kind": kind}
    return [
        path(f"{prefix}", views_repairs.repair_list, k, name=tag),
        path(f"{prefix}/journal", views_repairs.repair_journal, k, name=f"{tag}-journal"),
        path(f"{prefix}/<int:pk>", views_repairs.repair_detail, k, name=f"{tag}-detail"),
        path(f"{prefix}/<int:pk>/start", views_repairs.repair_start, k, name=f"{tag}-start"),
        path(f"{prefix}/<int:pk>/finish", views_repairs.repair_finish, k, name=f"{tag}-finish"),
        path(f"{prefix}/<int:pk>/payments", views_repairs.repair_pay, k, name=f"{tag}-pay"),
        path(f"{prefix}/<int:pk>/payments/<int:journal_id>", views_repairs.repair_payment, k, name=f"{tag}-payment"),
    ]


urlpatterns = [
    path("login", views.login, name="login"),
    path("logout", views.logout, name="logout"),
    path("me", views.me, name="me"),
    path("dirs", views.directory_index, name="directories"),
    path("dirs/<slug:slug>", views.directory, name="directory"),
    path("quotes", views_quotes.quote_list, name="quotes"),
    path("quotes/<int:pk>", views_quotes.quote_detail, name="quote"),
    *_shop("repairs", repairs.AGGREGATE, "repairs"),
    *_shop("body-repairs", repairs.BODY, "body-repairs"),
    path("payment-methods", views_repairs.payment_methods, name="payment-methods"),
    path("discount-cards", views_cards.card_list, name="discount-cards"),
    path("discount-cards/intervals", views_cards.card_intervals, name="discount-card-intervals"),
    path("discount-cards/<int:pk>", views_cards.card_detail, name="discount-card"),
    path("discount-cards/<int:pk>/statement", views_cards.card_statement, name="discount-card-statement"),
    path("discounts", views_discounts.discount_list, name="discounts"),
    path("discounts/lookups", views_discounts.discount_lookups, name="discount-lookups"),
    path("discounts/items", views_discounts.discount_items, name="discount-items"),
    path("discounts/<int:pk>", views_discounts.discount_detail, name="discount"),
    path("settings", views_settings.settings_main, name="settings"),
    path("settings/advanced/unlock", views_settings.advanced_unlock, name="settings-advanced-unlock"),
    path("settings/advanced", views_settings.settings_advanced, name="settings-advanced"),
]
