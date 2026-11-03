from django.urls import path

from recruitment import views

app_name = "recruitment"

urlpatterns = [
    path("", views.vacancies, name="vacancies"),
    path("vacancies/slot-line/", views.vacancy_slot_line, name="vacancy_slot_line"),
    path("vacancies/add/", views.vacancy_add, name="vacancy_add"),
    path("vacancies/<int:pk>/", views.vacancy_detail, name="vacancy_detail"),
    path("vacancies/<int:pk>/edit/", views.vacancy_edit, name="vacancy_edit"),
    path("vacancies/<int:pk>/candidates/add/", views.candidate_add, name="candidate_add"),
    path("candidates/<int:pk>/", views.candidate_detail, name="candidate_detail"),
    path("candidates/<int:pk>/convert/", views.candidate_convert, name="candidate_convert"),
    path("candidates/<int:pk>/move/", views.candidate_move, name="candidate_move"),
    path("candidates/<int:pk>/reject/", views.candidate_reject, name="candidate_reject"),
    path("candidates/<int:pk>/reopen/", views.candidate_reopen, name="candidate_reopen"),
    path("candidates/<int:pk>/comment/", views.candidate_comment, name="candidate_comment"),
    path("candidates/<int:pk>/files/upload/", views.candidate_file_upload, name="candidate_file_upload"),
    path("purge/", views.purge, name="purge"),
    path("files/<int:pk>/", views.candidate_file, name="candidate_file"),
]
