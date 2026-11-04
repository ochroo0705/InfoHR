"""Recruitment screens: visibility (Review Focus 1), manage-only actions, files, stage moves, query counts."""

from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from accounts.models import SystemLogEntry, User
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from macs.models import Employee

from recruitment.models import Candidate, CandidateComment, CandidateFile, Stage, Vacancy, VacancyStatus
from recruitment.services import files, pipeline

from .conftest import make_manager, make_vacancy

PASSWORD = "x-long-pass-123"  # noqa: S105


def login(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


class World:
    """HR, two hiring managers, a vacancy and a candidate (with a CV file) for each."""

    def __init__(self, actor: User, hr_user: User) -> None:
        self.hr = hr_user
        # Real HR also holds the employee right; the hiring-manager choice lists only people the user may see.
        hr_user.user_permissions.add(Permission.objects.get(codename="view_employees", content_type__app_label="macs"))
        self.user_a, self.emp_a = make_manager(actor, "mgr_a", "УБ10000001")
        self.user_b, self.emp_b = make_manager(actor, "mgr_b", "УБ10000002")
        self.va = make_vacancy("Вакансий А", manager=self.emp_a)
        self.vb = make_vacancy("Вакансий Б", manager=self.emp_b)
        self.ca = pipeline.add_candidate(self.va, by=actor, surname="Аа", given_name="Анар")
        self.cb = pipeline.add_candidate(self.vb, by=actor, surname="Бб", given_name="Билгүүн")
        self.fa = files.save(self.ca, SimpleUploadedFile("a.pdf", b"%PDF-A bytes"), by=actor)
        self.fb = files.save(self.cb, SimpleUploadedFile("b.pdf", b"%PDF-B bytes"), by=actor)


@pytest.fixture
def world(actor: User, hr_user: User) -> World:
    return World(actor, hr_user)


# ---- visibility: manager of A against vacancy B ----


def test_manager_list_shows_only_own_vacancy(world: World) -> None:
    body = login(world.user_a).get(reverse("recruitment:vacancies")).content.decode()
    assert "Вакансий А" in body
    assert "Вакансий Б" not in body


def test_hr_list_shows_all(world: World) -> None:
    body = login(world.hr).get(reverse("recruitment:vacancies")).content.decode()
    assert "Вакансий А" in body and "Вакансий Б" in body


def test_manager_gets_404_on_other_vacancy_and_candidate_pages(world: World) -> None:
    client = login(world.user_a)
    assert client.get(reverse("recruitment:vacancy_detail", args=[world.vb.pk])).status_code == 404
    assert client.get(reverse("recruitment:candidate_detail", args=[world.cb.pk])).status_code == 404
    assert client.get(reverse("recruitment:vacancy_detail", args=[world.va.pk])).status_code == 200
    assert client.get(reverse("recruitment:candidate_detail", args=[world.ca.pk])).status_code == 200


def test_manager_gets_404_on_other_file_download(world: World) -> None:
    client = login(world.user_a)
    assert client.get(reverse("recruitment:candidate_file", args=[world.fb.pk])).status_code == 404
    assert not SystemLogEntry.objects.filter(action="candidate_file_downloaded").exists()


def test_manager_gets_404_and_writes_nothing_on_other_candidate_posts(world: World) -> None:
    client = login(world.user_a)
    comment = client.post(reverse("recruitment:candidate_comment", args=[world.cb.pk]), {"text": "hello"})
    assert comment.status_code == 404
    assert not CandidateComment.objects.filter(candidate=world.cb).exists()
    for name, data in (
        ("candidate_move", {"to": "screening"}),
        ("candidate_reject", {"reason": "x"}),
        ("candidate_reopen", {}),
        ("candidate_file_upload", {"file": SimpleUploadedFile("c.pdf", b"x")}),
    ):
        assert client.post(reverse(f"recruitment:{name}", args=[world.cb.pk]), data).status_code == 404, name
    assert client.post(reverse("recruitment:vacancy_edit", args=[world.vb.pk]), {}).status_code == 404
    assert client.post(reverse("recruitment:candidate_add", args=[world.vb.pk]), {}).status_code == 404
    world.cb.refresh_from_db()
    assert world.cb.stage == Stage.NEW


def test_stranger_without_employee_sees_empty_list_and_404s(world: World) -> None:
    stranger = User.objects.create_user("stranger", password=PASSWORD)
    client = login(stranger)
    body = client.get(reverse("recruitment:vacancies")).content.decode()
    assert "Вакансий А" not in body and "Вакансий Б" not in body
    assert client.get(reverse("recruitment:vacancy_detail", args=[world.va.pk])).status_code == 404
    assert client.get(reverse("recruitment:candidate_file", args=[world.fa.pk])).status_code == 404


def test_anonymous_is_sent_to_login(world: World) -> None:
    response = Client().get(reverse("recruitment:candidate_file", args=[world.fa.pk]))
    assert response.status_code == 302 and "/login/" in response["Location"]


def test_hr_sees_everything(world: World) -> None:
    client = login(world.hr)
    for name, pk in (
        ("vacancy_detail", world.vb.pk),
        ("candidate_detail", world.cb.pk),
    ):
        assert client.get(reverse(f"recruitment:{name}", args=[pk])).status_code == 200


# ---- manager: read, download, comment only ----


def test_manager_cannot_manage(world: World) -> None:
    client = login(world.user_a)
    assert client.get(reverse("recruitment:vacancy_add")).status_code == 403
    assert client.post(reverse("recruitment:vacancy_add"), {"title": "x"}).status_code == 403
    assert client.get(reverse("recruitment:vacancy_edit", args=[world.va.pk])).status_code == 403
    assert client.post(reverse("recruitment:vacancy_edit", args=[world.va.pk]), {"status": "closed"}).status_code == 403
    assert client.get(reverse("recruitment:candidate_add", args=[world.va.pk])).status_code == 403
    assert client.post(reverse("recruitment:candidate_add", args=[world.va.pk]), {"surname": "x"}).status_code == 403
    assert (
        client.post(reverse("recruitment:candidate_move", args=[world.ca.pk]), {"to": "screening"}).status_code == 403
    )
    assert client.get(reverse("recruitment:candidate_reject", args=[world.ca.pk])).status_code == 403
    assert client.post(reverse("recruitment:candidate_reject", args=[world.ca.pk]), {"reason": "x"}).status_code == 403
    assert client.post(reverse("recruitment:candidate_reopen", args=[world.ca.pk])).status_code == 403
    upload = {"file": SimpleUploadedFile("c.pdf", b"x")}
    assert client.post(reverse("recruitment:candidate_file_upload", args=[world.ca.pk]), upload).status_code == 403
    world.ca.refresh_from_db()
    world.va.refresh_from_db()
    assert world.ca.stage == Stage.NEW and world.va.status == VacancyStatus.OPEN
    assert Candidate.objects.filter(vacancy=world.va).count() == 1
    assert CandidateFile.objects.filter(candidate=world.ca).count() == 1


def test_manager_page_has_no_manage_buttons_and_no_salary(world: World) -> None:
    client = login(world.user_a)
    for url in (
        reverse("recruitment:vacancy_detail", args=[world.va.pk]),
        reverse("recruitment:candidate_detail", args=[world.ca.pk]),
    ):
        body = client.get(url).content.decode()
        assert reverse("recruitment:vacancy_edit", args=[world.va.pk]) not in body
        assert reverse("recruitment:vacancy_add") not in body
        assert reverse("recruitment:candidate_add", args=[world.va.pk]) not in body
        assert reverse("recruitment:candidate_move", args=[world.ca.pk]) not in body
        assert reverse("recruitment:candidate_reject", args=[world.ca.pk]) not in body
        assert "2,500,000" not in body and "2500000" not in body
        assert "УБ10000001" not in body  # the hiring manager's register number is employee data
        assert reverse("employees:detail", args=[world.emp_a.pk]) not in body


def test_manager_can_comment_on_own_candidate(world: World) -> None:
    client = login(world.user_a)
    response = client.post(reverse("recruitment:candidate_comment", args=[world.ca.pk]), {"text": "  Сайн  "})
    assert response.status_code == 200
    assert "Сайн" in response.content.decode()
    row = CandidateComment.objects.get(candidate=world.ca)
    assert row.text == "Сайн" and row.by == world.user_a
    assert SystemLogEntry.objects.filter(action="candidate_commented").exists()


def test_empty_comment_is_refused_with_a_message(world: World) -> None:
    response = login(world.user_a).post(reverse("recruitment:candidate_comment", args=[world.ca.pk]), {"text": " "})
    assert response.status_code == 200
    assert "хоосон" in response.content.decode()
    assert not CandidateComment.objects.exists()


def test_download_returns_bytes_and_logs(world: World) -> None:
    response = login(world.user_a).get(reverse("recruitment:candidate_file", args=[world.fa.pk]))
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"%PDF-A bytes"  # type: ignore[attr-defined]
    assert "attachment" in response["Content-Disposition"] and "a.pdf" in response["Content-Disposition"]
    assert SystemLogEntry.objects.filter(action="candidate_file_downloaded").count() == 1


# ---- HR: vacancy add / edit ----


def _vacancy_post(**extra: Any) -> dict[str, Any]:
    from macs.models import Department, Position

    data: dict[str, Any] = {
        "title": "Борлуулагч",
        "position": Position.objects.first().pk,  # type: ignore[union-attr]
        "department": Department.objects.first().pk,  # type: ignore[union-attr]
        "headcount": 2,
        "hiring_manager": "",
        "deadline": "2026-12-01",
        "desired_start": "2027-01-15",
        "description": "Тайлбар",
    }
    data.update(extra)
    return data


def test_hr_adds_a_vacancy(world: World) -> None:
    client = login(world.hr)
    assert client.get(reverse("recruitment:vacancy_add")).status_code == 200
    response = client.post(reverse("recruitment:vacancy_add"), _vacancy_post(hiring_manager=world.emp_a.pk))
    assert response.status_code == 204, response.content.decode()[-2500:]
    assert response["HX-Refresh"] == "true"
    vacancy = Vacancy.objects.get(title="Борлуулагч")
    assert vacancy.status == VacancyStatus.OPEN and vacancy.created_by == world.hr
    assert vacancy.hiring_manager == world.emp_a and vacancy.headcount == 2
    assert vacancy.deadline == date(2026, 12, 1) and vacancy.desired_start == date(2027, 1, 15)
    assert SystemLogEntry.objects.filter(action="vacancy_created").exists()


def test_vacancy_form_errors_keep_the_modal(world: World) -> None:
    response = login(world.hr).post(reverse("recruitment:vacancy_add"), _vacancy_post(headcount=0, title=""))
    assert response.status_code == 200
    assert "text-red-600" in response.content.decode()
    assert not Vacancy.objects.filter(title="").exists()


def test_hr_edits_and_closes_and_reopens(world: World) -> None:
    client = login(world.hr)
    url = reverse("recruitment:vacancy_edit", args=[world.va.pk])
    body = client.get(url).content.decode()
    assert 'name="status"' in body
    response = client.post(url, _vacancy_post(title="Шинэ нэр", status="closed"))
    assert response.status_code == 204
    world.va.refresh_from_db()
    assert world.va.title == "Шинэ нэр" and world.va.status == VacancyStatus.CLOSED
    assert SystemLogEntry.objects.filter(action="vacancy_changed").exists()
    client.post(url, _vacancy_post(title="Шинэ нэр", status="open"))
    world.va.refresh_from_db()
    assert world.va.status == VacancyStatus.OPEN


def test_editing_headcount_reevaluates_filled(world: World, new_employee: Employee, actor: User) -> None:
    client = login(world.hr)
    url = reverse("recruitment:vacancy_edit", args=[world.va.pk])
    cand = pipeline.add_candidate(world.va, by=actor, surname="Х", given_name="Ү")
    pipeline.mark_hired(cand, new_employee, by=actor)  # headcount 1 -> filled
    world.va.refresh_from_db()
    assert world.va.status == VacancyStatus.FILLED
    assert client.post(url, _vacancy_post(headcount=3, status="filled")).status_code == 204
    world.va.refresh_from_db()
    assert world.va.status == VacancyStatus.OPEN  # raised above the hired count
    assert client.post(url, _vacancy_post(headcount=1, status="open")).status_code == 204
    world.va.refresh_from_db()
    assert world.va.status == VacancyStatus.FILLED  # lowered to the hired count
    assert client.post(url, _vacancy_post(headcount=1, status="closed")).status_code == 204
    world.va.refresh_from_db()
    assert world.va.status == VacancyStatus.CLOSED  # an explicit close stays closed


def test_add_form_has_no_status_field(world: World) -> None:
    body = login(world.hr).get(reverse("recruitment:vacancy_add")).content.decode()
    assert 'name="status"' not in body


# ---- candidates ----


def test_hr_adds_candidate_to_open_vacancy(world: World) -> None:
    client = login(world.hr)
    url = reverse("recruitment:candidate_add", args=[world.va.pk])
    assert client.get(url).status_code == 200
    response = client.post(url, {"surname": "Новый", "given_name": "Нэр", "phone": "99", "source": "Referral"})
    assert response.status_code == 204 and response["HX-Refresh"] == "true"
    candidate = Candidate.objects.get(surname="Новый")
    assert candidate.stage == Stage.NEW and candidate.vacancy == world.va
    assert candidate.events.count() == 1


def test_add_candidate_refused_when_vacancy_not_open(world: World) -> None:
    world.va.status = VacancyStatus.CLOSED
    world.va.save()
    client = login(world.hr)
    url = reverse("recruitment:candidate_add", args=[world.va.pk])
    for response in (client.get(url), client.post(url, {"surname": "Новый", "given_name": "Нэр"})):
        assert response.status_code == 200
        assert "нээлттэй биш" in response.content.decode()
    assert not Candidate.objects.filter(surname="Новый").exists()


def test_add_candidate_requires_names(world: World) -> None:
    response = login(world.hr).post(reverse("recruitment:candidate_add", args=[world.va.pk]), {"surname": ""})
    assert response.status_code == 200
    assert Candidate.objects.count() == 2


def test_hr_candidate_page_shows_everything(world: World) -> None:
    pipeline.comment(world.ca, by=world.hr, text="Тэмдэглэл-1")
    body = login(world.hr).get(reverse("recruitment:candidate_detail", args=[world.ca.pk])).content.decode()
    assert "Аа" in body and "Анар" in body
    assert "a.pdf" in body and reverse("recruitment:candidate_file", args=[world.fa.pk]) in body
    assert "Тэмдэглэл-1" in body
    assert reverse("recruitment:candidate_move", args=[world.ca.pk]) in body
    assert reverse("recruitment:candidate_reject", args=[world.ca.pk]) in body
    assert "Шинэ" in body  # history row and stage chip


def test_move_stages_and_refusals(world: World) -> None:
    client = login(world.hr)
    url = reverse("recruitment:candidate_move", args=[world.ca.pk])
    response = client.post(url, {"to": "screening"})
    assert response.status_code == 204 and response["HX-Refresh"] == "true"
    world.ca.refresh_from_db()
    assert world.ca.stage == Stage.SCREENING
    refused = client.post(url, {"to": "hired"})
    assert refused.status_code == 200 and "text-red-" in refused.content.decode()
    junk = client.post(url, {"to": "bogus"})
    assert junk.status_code == 200
    world.ca.refresh_from_db()
    assert world.ca.stage == Stage.SCREENING


def test_stepper_asks_before_a_skip_or_back_move_but_not_the_next_step(world: World) -> None:
    page = reverse("recruitment:candidate_detail", args=[world.ca.pk])
    body = login(world.hr).get(page).content.decode()  # a new candidate: the next step is «Шалгаруулалт»
    assert 'hx-confirm="«Шалгаруулалт»' not in body
    assert 'hx-confirm="«Ярилцлага»' in body and 'hx-confirm="«Санал»' in body
    assert 'aria-current="step"' in body


def test_vacancy_form_shows_hints_and_the_new_labels(world: World) -> None:
    body = login(world.hr).get(reverse("recruitment:vacancy_add")).content.decode()
    assert "Ажлын байрны нэр" in body
    for hint in ("салбараар шалгана", "сэтгэгдэл бичих удирдлага", "ажилд орохыг хүсэж буй өдөр"):
        assert hint in body


def test_reject_modal_explains_itself_and_confirms_in_red(world: World) -> None:
    body = login(world.hr).get(reverse("recruitment:candidate_reject", args=[world.ca.pk])).content.decode()
    assert 'role="dialog"' in body and "bg-red-600" in body and "шатны түүхэнд хадгалагдана" in body


def test_move_and_reopen_need_post(world: World) -> None:
    client = login(world.hr)
    assert client.get(reverse("recruitment:candidate_move", args=[world.ca.pk])).status_code == 405
    assert client.get(reverse("recruitment:candidate_reopen", args=[world.ca.pk])).status_code == 405


def test_reject_modal_needs_reason_then_closes_and_reopens(world: World) -> None:
    client = login(world.hr)
    url = reverse("recruitment:candidate_reject", args=[world.ca.pk])
    assert 'name="reason"' in client.get(url).content.decode()
    invalid = client.post(url, {"reason": " "})
    assert invalid.status_code == 200 and "text-red-600" in invalid.content.decode()
    world.ca.refresh_from_db()
    assert world.ca.stage == Stage.NEW
    ok = client.post(url, {"reason": "Туршлага хүрэлцэхгүй"})
    assert ok.status_code == 204
    world.ca.refresh_from_db()
    assert world.ca.stage == Stage.REJECTED and world.ca.reject_reason == "Туршлага хүрэлцэхгүй"
    assert world.ca.closed_at is not None
    body = client.get(reverse("recruitment:candidate_detail", args=[world.ca.pk])).content.decode()
    assert "Туршлага хүрэлцэхгүй" in body
    assert reverse("recruitment:candidate_reopen", args=[world.ca.pk]) in body
    assert reverse("recruitment:candidate_move", args=[world.ca.pk]) not in body  # closed: no stage buttons
    assert client.post(reverse("recruitment:candidate_reopen", args=[world.ca.pk])).status_code == 204
    world.ca.refresh_from_db()
    assert world.ca.stage == Stage.NEW and world.ca.closed_at is None


def test_withdrawn_needs_no_reason(world: World) -> None:
    url = reverse("recruitment:candidate_reject", args=[world.ca.pk])
    assert login(world.hr).post(url, {"reason": "", "withdrawn": "on"}).status_code == 204
    world.ca.refresh_from_db()
    assert world.ca.stage == Stage.WITHDRAWN


def test_reject_of_hired_candidate_shows_the_refusal(world: World, new_employee: Employee) -> None:
    pipeline.mark_hired(world.ca, new_employee, by=world.hr)
    response = login(world.hr).post(reverse("recruitment:candidate_reject", args=[world.ca.pk]), {"reason": "x"})
    assert response.status_code == 200 and "text-red-" in response.content.decode()
    world.ca.refresh_from_db()
    assert world.ca.stage == Stage.HIRED


# ---- files ----


def test_hr_uploads_a_file(world: World) -> None:
    url = reverse("recruitment:candidate_file_upload", args=[world.ca.pk])
    response = login(world.hr).post(url, {"file": SimpleUploadedFile("Миний CV.pdf", b"%PDF-new")})
    assert response.status_code == 200
    assert "Миний CV.pdf" in response.content.decode()
    row = CandidateFile.objects.get(candidate=world.ca, name="Миний CV.pdf")
    assert row.uploaded_by == world.hr


def test_bad_upload_shows_message(world: World) -> None:
    url = reverse("recruitment:candidate_file_upload", args=[world.ca.pk])
    response = login(world.hr).post(url, {"file": SimpleUploadedFile("virus.exe", b"MZ")})
    assert response.status_code == 200 and "text-red-" in response.content.decode()
    assert CandidateFile.objects.filter(candidate=world.ca).count() == 1
    missing = login(world.hr).post(url, {})
    assert missing.status_code == 200 and "text-red-" in missing.content.decode()


# ---- vacancy list and detail ----


def test_list_filters_by_status_and_search(world: World) -> None:
    world.vb.status = VacancyStatus.CLOSED
    world.vb.save()
    client = login(world.hr)
    url = reverse("recruitment:vacancies")
    default = client.get(url).content.decode()
    assert "Вакансий А" in default and "Вакансий Б" not in default  # default: open
    closed = client.get(url, {"status": "closed"}).content.decode()
    assert "Вакансий Б" in closed and "Вакансий А" not in closed
    everything = client.get(url, {"status": "all"}).content.decode()
    assert "Вакансий А" in everything and "Вакансий Б" in everything
    found = client.get(url, {"status": "all", "q": "вакансий б"}).content.decode()
    assert "Вакансий Б" in found and "Вакансий А" not in found
    assert client.get(url, {"status": "zzz", "q": "x" * 500}).status_code == 200


def test_list_shows_counts_per_stage(world: World, actor: User) -> None:
    pipeline.add_candidate(world.va, by=actor, surname="C", given_name="c")
    pipeline.move(world.ca, Stage.SCREENING, by=actor)
    response = login(world.hr).get(reverse("recruitment:vacancies"))
    rows = {row.pk: row for row in response.context["rows"]}
    assert rows[world.va.pk].c_new == 1 and rows[world.va.pk].c_screening == 1
    assert rows[world.vb.pk].c_new == 1 and rows[world.vb.pk].c_screening == 0


def test_list_htmx_returns_rows_only(world: World) -> None:
    body = login(world.hr).get(reverse("recruitment:vacancies"), HTTP_HX_REQUEST="true").content.decode()
    assert "<html" not in body and "Вакансий А" in body


def test_list_batches(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from config import batching

    for number in range(5):
        make_vacancy(f"Дахин {number}")
    monkeypatch.setattr(batching, "LIST_BATCH", 3)
    client = login(world.hr)
    first = client.get(reverse("recruitment:vacancies"))
    assert len(first.context["rows"]) == 3 and "data-more-batch" in first.content.decode()
    more = client.get(reverse("recruitment:vacancies"), {"offset": "3"}, HTTP_HX_REQUEST="true")
    assert "<html" not in more.content.decode()


def test_detail_stage_filter(world: World, actor: User) -> None:
    second = pipeline.add_candidate(world.va, by=actor, surname="Хоёр", given_name="Хоёрдахь")
    pipeline.reject(second, by=actor, reason="x")
    client = login(world.hr)
    url = reverse("recruitment:vacancy_detail", args=[world.va.pk])
    default = client.get(url).content.decode()
    assert "Анар" in default and "Хоёрдахь" not in default  # default: still in the running
    rejected = client.get(url, {"stage": "rejected"}).content.decode()
    assert "Хоёрдахь" in rejected and "Анар" not in rejected
    everyone = client.get(url, {"stage": "all"}).content.decode()
    assert "Анар" in everyone and "Хоёрдахь" in everyone
    assert client.get(url, {"stage": "bogus"}).status_code == 200
    assert 'aria-current="true"' in default


def test_detail_stage_bar_counts(world: World, actor: User) -> None:
    pipeline.add_candidate(world.va, by=actor, surname="C", given_name="c")
    response = login(world.hr).get(reverse("recruitment:vacancy_detail", args=[world.va.pk]))
    counts = {item.key: item.count for item in response.context["stage_bar"]}
    assert counts["new"] == 2 and counts["screening"] == 0


def test_detail_htmx_swaps_the_list_block(world: World) -> None:
    url = reverse("recruitment:vacancy_detail", args=[world.va.pk])
    body = login(world.hr).get(url, {"stage": "all"}, HTTP_HX_REQUEST="true").content.decode()
    assert 'id="cand-list"' in body


# ---- query counts do not grow with candidates ----


def _count(client: Client, url: str) -> int:
    with CaptureQueriesContext(connection) as queries:
        assert client.get(url).status_code == 200
    return len(queries)


@pytest.mark.parametrize("who", ["hr", "manager"])
def test_query_count_does_not_grow_with_candidates(world: World, actor: User, who: str) -> None:
    client = login(world.hr if who == "hr" else world.user_a)
    urls: list[Callable[[], str]] = [
        lambda: reverse("recruitment:vacancies"),
        lambda: reverse("recruitment:vacancy_detail", args=[world.va.pk]),
        lambda: reverse("recruitment:candidate_detail", args=[world.ca.pk]),
    ]
    for url in urls:
        _count(client, url())  # warm up (caches, first-request writes)
    before = [_count(client, url()) for url in urls]
    for number in range(12):
        candidate = pipeline.add_candidate(world.va, by=actor, surname=f"К{number}", given_name="к")
        pipeline.comment(world.ca, by=actor, text=f"сэтгэгдэл {number}")
        files.save(world.ca, SimpleUploadedFile(f"f{number}.pdf", b"x"), by=actor)
        pipeline.move(candidate, Stage.SCREENING, by=actor)
        make_vacancy(f"V{number}", manager=world.emp_a)
    after = [_count(client, url()) for url in urls]
    assert after == before


# ---- menu and palette ----


def test_palette_offers_recruitment_by_the_same_rule_as_the_menu(world: World) -> None:
    from employees import palette

    stranger = User.objects.create_user("pal_stranger", password=PASSWORD)

    def titles(user: User) -> list[str]:
        return [screen.title for screen in palette.screens(User.objects.get(pk=user.pk), "")]

    assert "Ажилд авах" in titles(world.hr)
    assert "Ажилд авах" in titles(world.user_a)
    assert "Ажилд авах" not in titles(stranger)
    url = next(s.url for s in palette.screens(world.user_a, "") if s.title == "Ажилд авах")
    assert url == reverse("recruitment:vacancies")


def test_menu_link_in_the_page(world: World) -> None:
    client = login(world.user_a)
    body = client.get(reverse("recruitment:vacancies")).content.decode()
    assert f'href="{reverse("recruitment:vacancies")}"' in body and "Ажилд авах" in body
    stranger = User.objects.create_user("menu_stranger", password=PASSWORD)
    other = login(stranger).get(reverse("me"))
    assert reverse("recruitment:vacancies") not in other.content.decode()


def test_stage_bar_chips_wrap_instead_of_overflowing(world: World) -> None:
    body = login(world.hr).get(reverse("recruitment:vacancy_detail", args=[world.va.pk])).content.decode()
    start = body.index('<nav class="flex flex-wrap')
    bar = body[start : body.index("</nav>", start)]
    assert "overflow-x-auto" not in bar and "shrink-0" not in bar


def test_vacancy_form_and_detail_show_both_dates_with_new_labels(world: World) -> None:
    client = login(world.hr)
    form = client.get(reverse("recruitment:vacancy_add")).content.decode()
    assert "Авах эцсийн хугацаа" in form and "Ажил эхлэх огноо" in form
    assert form.index("Авах эцсийн хугацаа") < form.index("Ажил эхлэх огноо")
    world.va.deadline, world.va.desired_start = date(2026, 12, 1), date(2027, 1, 15)
    world.va.save()
    page = client.get(reverse("recruitment:vacancy_detail", args=[world.va.pk])).content.decode()
    assert "Авах эцсийн хугацаа" in page and "2026-12-01" in page
    assert "Ажил эхлэх огноо" in page and "2027-01-15" in page
    listing = client.get(reverse("recruitment:vacancies")).content.decode()
    assert "Авах эцсийн хугацаа" in listing and "Ажил эхлэх огноо" not in listing
