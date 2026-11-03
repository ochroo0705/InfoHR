"""Purge screen: lists what is eligible, POST removes only that and its files (Review Focus 4)."""

from datetime import timedelta

from accounts.models import SystemLogEntry, User
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from recruitment.models import Candidate, CandidateFile, RecruitmentSettings, Vacancy
from recruitment.services import files, pipeline

from .conftest import make_manager, make_vacancy

URL = "recruitment:purge"


def _login(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _closed(vacancy: Vacancy, actor: User, surname: str, months_ago: int, *, withdrawn: bool = False) -> Candidate:
    cand = pipeline.add_candidate(vacancy, by=actor, surname=surname, given_name="Х")
    pipeline.reject(cand, by=actor, reason="" if withdrawn else "Тохирохгүй", withdrawn=withdrawn)
    Candidate.objects.filter(pk=cand.pk).update(closed_at=timezone.now() - timedelta(days=31 * months_ago))
    return cand


def test_get_lists_only_eligible_with_vacancy_and_setting(hr_user: User, vacancy: Vacancy, actor: User) -> None:
    _closed(vacancy, actor, "Хуучин", 14)
    _closed(vacancy, actor, "Өөрөө", 14, withdrawn=True)
    _closed(vacancy, actor, "Шинэхэн", 2)
    pipeline.add_candidate(vacancy, by=actor, surname="Идэвхтэй", given_name="Х")
    page = _login(hr_user).get(reverse(URL))
    body = page.content.decode()
    assert "Хуучин" in body and "Өөрөө" in body
    assert "Шинэхэн" not in body and "Идэвхтэй" not in body
    assert vacancy.title in body
    assert page.context["months"] == 12
    assert len(page.context["rows"]) == 2


def test_empty_state_has_no_purge_button(hr_user: User, vacancy: Vacancy) -> None:
    body = _login(hr_user).get(reverse(URL)).content.decode()
    assert "олдсонгүй" in body
    assert "Устгах</button>" not in body


def test_settings_link_only_for_admin(hr_user: User, vacancy: Vacancy) -> None:
    link = reverse("admin:recruitment_recruitmentsettings_changelist")
    assert link not in _login(hr_user).get(reverse(URL)).content.decode()
    admin_user = User.objects.create_user("rec_admin", password="x-long-pass-123")  # noqa: S106
    admin_user.groups.add(Group.objects.get(name="Admin"))
    assert link in _login(admin_user).get(reverse(URL)).content.decode()


def test_post_removes_only_eligible_rows_and_their_files(hr_user: User, vacancy: Vacancy, actor: User) -> None:
    old = _closed(vacancy, actor, "Хуучин", 14)
    keep = _closed(vacancy, actor, "Шинэхэн", 2)
    live = pipeline.add_candidate(vacancy, by=actor, surname="Идэвхтэй", given_name="Х")
    old_file = files.save(old, SimpleUploadedFile("old.pdf", b"%PDF-old"), by=actor)
    keep_file = files.save(keep, SimpleUploadedFile("keep.pdf", b"%PDF-keep"), by=actor)
    old_path, keep_path = old_file.file, keep_file.file
    assert files.storage().exists(old_path)
    response = _login(hr_user).post(reverse(URL))
    assert response.status_code == 302
    assert response["Location"] == f"{reverse(URL)}?done=1"
    assert not Candidate.objects.filter(pk=old.pk).exists()
    assert not CandidateFile.objects.filter(pk=old_file.pk).exists()
    assert not files.storage().exists(old_path)
    assert Candidate.objects.filter(pk__in=[keep.pk, live.pk]).count() == 2
    assert CandidateFile.objects.filter(pk=keep_file.pk).exists()
    assert files.storage().exists(keep_path)
    entry = SystemLogEntry.objects.filter(action="candidates_purged").latest("pk")
    assert "Хуучин" not in entry.message
    assert f"#{vacancy.pk}" in entry.message and "1 ажил хүсэгч" in entry.message and "1 ажлын байр" in entry.message
    assert "Шинэхэн" not in entry.message and "Идэвхтэй" not in entry.message


def test_done_note_shows_the_count(hr_user: User, vacancy: Vacancy) -> None:
    body = _login(hr_user).get(reverse(URL) + "?done=3").content.decode()
    assert "Устгасан: 3" in body
    assert _login(hr_user).get(reverse(URL) + "?done=abc").status_code == 200


def test_retention_setting_moves_the_cutoff(hr_user: User, vacancy: Vacancy, actor: User) -> None:
    _closed(vacancy, actor, "Дунд", 5)
    assert "Дунд" not in _login(hr_user).get(reverse(URL)).content.decode()
    settings_row = RecruitmentSettings.get()
    settings_row.retention_months = 3
    settings_row.save()
    assert "Дунд" in _login(hr_user).get(reverse(URL)).content.decode()


def test_hiring_manager_and_stranger_are_refused(actor: User, hr_user: User) -> None:
    manager_user, manager_emp = make_manager(actor, "mgr_p", "УБ10000009")
    make_vacancy("В", manager=manager_emp)
    stranger = User.objects.create_user("stranger_p", password="x-long-pass-123")  # noqa: S106
    for user in (manager_user, stranger):
        client = _login(user)
        assert client.get(reverse(URL)).status_code == 403
        assert client.post(reverse(URL)).status_code == 403


def test_vacancy_list_links_to_purge_for_managers_only(hr_user: User, actor: User) -> None:
    manager_user, manager_emp = make_manager(actor, "mgr_q", "УБ10000010")
    make_vacancy("В", manager=manager_emp)
    assert reverse(URL) in _login(hr_user).get(reverse("recruitment:vacancies")).content.decode()
    assert reverse(URL) not in _login(manager_user).get(reverse("recruitment:vacancies")).content.decode()


def test_purge_audit_has_counts_and_ids_and_no_names_or_emails(hr_user: User, actor: User) -> None:
    v1, v2 = make_vacancy("Нэг"), make_vacancy("Хоёр")
    a = _closed(v1, actor, "Нууцлал", 14)
    b = _closed(v2, actor, "Хаяг", 14)
    Candidate.objects.filter(pk__in=[a.pk, b.pk]).update(email="secret@example.com")
    assert _login(hr_user).post(reverse(URL)).status_code == 302
    message = SystemLogEntry.objects.filter(action="candidates_purged").latest("pk").message
    assert "2 ажил хүсэгч" in message and "2 ажлын байр" in message
    assert f"#{v1.pk}" in message and f"#{v2.pk}" in message
    for secret in ("Нууцлал", "Хаяг", "secret@example.com", "Нэг", "Хоёр"):
        assert secret not in message
