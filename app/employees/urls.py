from django.urls import path

from . import views

app_name = "employees"

urlpatterns = [
    path("", views.employee_list, name="list"),
    path("new/", views.employee_add, name="add"),
    path("attention/", views.attention_toggle, name="attention"),
    path("check-register/", views.check_register, name="check_register"),
    path("<int:pk>/", views.employee_detail, name="detail"),
    path("<int:pk>/save/", views.employee_save, name="save"),
    path("<int:pk>/login/", views.login_create, name="login_create"),
    path("<int:pk>/setup/<str:key>/", views.toggle_setup, name="setup_toggle"),
    path("<int:pk>/note/", views.add_note, name="note"),
    path("<int:pk>/job/<int:record_id>/correct/", views.correct_job, name="correct_job"),
    path("<int:pk>/salary/<int:record_id>/correct/", views.correct_salary, name="correct_salary"),
    path("<int:pk>/salary/set/", views.set_salary, name="set_salary"),
    path("<int:pk>/event/<str:type>/", views.event_form, name="event"),
    path("<int:pk>/event/<int:event_id>/cancel/", views.event_cancel, name="event_cancel"),
    path("<int:pk>/family/", views.edit_family, name="family"),
    path("<int:pk>/education/", views.edit_education, name="education"),
    path("<int:pk>/talents/", views.edit_talents, name="talents"),
    path("<int:pk>/gifts/", views.edit_gifts, name="gifts"),
]
