from django.urls import path

from . import views

app_name = "employees"

urlpatterns = [
    path("", views.employee_list, name="list"),
    path("orders/", views.orders_page, name="orders"),
    path("orders/print/", views.orders_print, name="orders_print"),
    path("new/", views.employee_add, name="add"),
    path("attention/", views.attention_toggle, name="attention"),
    path("check-register/", views.check_register, name="check_register"),
    path("districts/", views.district_options, name="district_options"),
    path("<int:pk>/", views.employee_detail, name="detail"),
    path("<int:pk>/save/", views.employee_save, name="save"),
    path("<int:pk>/login/", views.login_create, name="login_create"),
    path("<int:pk>/setup/<str:key>/", views.toggle_setup, name="setup_toggle"),
    path("<int:pk>/section/<str:section>/", views.personal_section, name="personal_section"),
    path("<int:pk>/note/", views.add_note, name="note"),
    path("<int:pk>/job/<int:record_id>/correct/", views.correct_job, name="correct_job"),
    path("<int:pk>/salary/<int:record_id>/correct/", views.correct_salary, name="correct_salary"),
    path("<int:pk>/salary/set/", views.set_salary, name="set_salary"),
    path("<int:pk>/event/<str:type>/", views.event_form, name="event"),
    path("<int:pk>/event/<int:event_id>/cancel/", views.event_cancel, name="event_cancel"),
    path("<int:pk>/order/<int:order_id>/", views.order_edit, name="order_edit"),
    path("<int:pk>/order/<int:order_id>/upload/", views.order_upload, name="order_upload"),
    path("<int:pk>/order/<int:order_id>/file/", views.order_file, name="order_file"),
    path("<int:pk>/personal/<str:kind>/add/", views.personal_add, name="personal_add"),
    path("<int:pk>/personal/<str:kind>/<int:key>/edit/", views.personal_edit, name="personal_edit"),
    path("<int:pk>/personal/<str:kind>/<int:key>/delete/", views.personal_delete, name="personal_delete"),
]
