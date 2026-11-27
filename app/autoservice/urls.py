from django.urls import path

from autoservice import views, views_quotes, views_repairs

app_name = "autoservice"

urlpatterns = [
    path("login", views.login, name="login"),
    path("logout", views.logout, name="logout"),
    path("me", views.me, name="me"),
    path("dirs", views.directory_index, name="directories"),
    path("dirs/<slug:slug>", views.directory, name="directory"),
    path("quotes", views_quotes.quote_list, name="quotes"),
    path("quotes/<int:pk>", views_quotes.quote_detail, name="quote"),
    path("repairs", views_repairs.repair_list, name="repairs"),
    path("repairs/journal", views_repairs.repair_journal, name="repair-journal"),
    path("repairs/<int:pk>", views_repairs.repair_detail, name="repair"),
    path("repairs/<int:pk>/start", views_repairs.repair_start, name="repair-start"),
    path("repairs/<int:pk>/finish", views_repairs.repair_finish, name="repair-finish"),
    path("repairs/<int:pk>/payments", views_repairs.repair_pay, name="repair-pay"),
    path("repairs/<int:pk>/payments/<int:journal_id>", views_repairs.repair_payment, name="repair-payment"),
    path("payment-methods", views_repairs.payment_methods, name="payment-methods"),
]
