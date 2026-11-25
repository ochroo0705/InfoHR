"""The writes of /api/v1/recruitment and the CV download: the vacancy, candidate and file actions the React pages post,
and the purge. The rules come from recruitment.services; these tests pin the answers (ok, error, field_errors,
form_errors), the rights (401 without a login, 404 while the module is off, 404 for a hidden object, 403 for a hiring
manager on a write except the comment and the download), that a refused write changes nothing, and the audit lines
the services write.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from accounts import modules
from accounts.models import SystemLogEntry, User
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from employees import daily_sync
from macs.models import Employee
from pytest_django.fixtures import SettingsWrapper
from recruitment.models import Candidate, CandidateComment, CandidateEvent, CandidateFile, Stage, Vacancy, VacancyStatus
from recruitment.services import files, pipeline
from recruitment.services.convert import NOT_CONVERTIBLE, VACANCY_NOT_OPEN
from recruitment.tests.conftest import make_manager, make_vacancy
from recruitment.views import NOT_OPEN

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
BASE = "/api/v1/recruitment"
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
FORBIDDEN = {"field_errors": {}, "form_errors": ["Хандах эрх байхгүй."], "code": "forbidden"}
NOT_FOUND = {"field_errors": {}, "form_errors": ["Хуудас олдсонгүй"]}
OK = {"ok": True, "error": "", "field_errors": {}, "form_errors": []}
NOT_HIRED_BY_MOVE = "«Ажилд авсан» шатанд зөвхөн ажилтан болгож хөрвүүлэх замаар оруулна."
REJECT_BY_REJECT = "Татгалзахдаа «Татгалзах» үйлдлийг ашиглана уу."
REOPEN_FIRST = "Татгалзсан ажил хүсэгчийг эхлээд дахин нээнэ үү."
UNKNOWN_STAGE = "Тодорхойгүй шат байна."
REASON_NEEDED = "Татгалзсан шалтгаанаа бичнэ үү."
ALREADY_CLOSED = "Ажил хүсэгч аль хэдийн хаагдсан байна."
NOT_REOPENABLE = "Зөвхөн татгалзсан ажил хүсэгчийг дахин нээнэ."
EMPTY_COMMENT = "Сэтгэгдэл хоосон байна."
NO_FILE = "Файл сонгоно уу."
BAD_TYPE = "Зөвхөн PDF, Word (doc, docx) эсвэл зураг (png, jpg) файл оруулна уу."
TOO_BIG = "Файл 10 MB-аас том байна."
EMPTY_FILE = "Файл хоосон байна."
MAX_BYTES = files.MAX_BYTES


@pytest.fixture(autouse=True)
def _no_request_time_daily_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """The daily sync runs on the first signed-in request of a process; these tests do not want it to write anything."""
    monkeypatch.setattr(daily_sync, "_needs_sync", lambda request: False)


@pytest.fixture(autouse=True)
def _files_tmp(settings: SettingsWrapper, tmp_path: Path) -> None:
    """Candidate files go to a temporary folder, never to app/private."""
    settings.RECRUITMENT_FILES_ROOT = tmp_path / "recruitment"


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_superuser("rec_w_actor", password=PASSWORD)  # noqa: S106


@pytest.fixture
def hr(db: None) -> User:
    user = User.objects.create_user("rec_w_hr", password=PASSWORD)  # noqa: S106
    user.user_permissions.add(Permission.objects.get(codename="manage_recruitment"))
    return User.objects.get(pk=user.pk)  # fresh permission cache


@pytest.fixture
def manager(actor: User) -> tuple[User, Employee]:
    """A hiring manager: a login linked to its own employee record, with no recruitment right."""
    return make_manager(actor, "rec_w_mgr", "УБ10000041")


@pytest.fixture
def manager_user(manager: tuple[User, Employee]) -> User:
    return User.objects.get(pk=manager[0].pk)


@pytest.fixture
def vacancy(actor: User) -> Vacancy:
    return make_vacancy("Нягтлан")


@pytest.fixture
def candidate(vacancy: Vacancy, actor: User) -> Candidate:
    return _add(vacancy, actor, "Дорж")


@pytest.fixture
def mine(manager: tuple[User, Employee]) -> Vacancy:
    """A vacancy the hiring manager manages."""
    return make_vacancy("Миний", manager=manager[1])


@pytest.fixture
def mine_candidate(mine: Vacancy, actor: User) -> Candidate:
    return _add(mine, actor, "Мөнх")


def _add(vacancy: Vacancy, by: User, surname: str) -> Candidate:
    return pipeline.add_candidate(vacancy, by=by, surname=surname, given_name="Бат")


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _rows() -> tuple[int, ...]:
    """The row counts of every table a write can change: a refused write leaves them as they were."""
    return (
        Vacancy.objects.count(),
        Candidate.objects.count(),
        CandidateEvent.objects.count(),
        CandidateComment.objects.count(),
        CandidateFile.objects.count(),
    )


def _post(client: Client, url: str, body: dict[str, Any] | None = None) -> Any:
    """A JSON body, or no body at all."""
    if body is None:
        return client.post(url)
    return client.post(url, json.dumps(body), content_type="application/json")


def _upload(client: Client, candidate_pk: int, upload: SimpleUploadedFile | None = None) -> Any:
    """The CV upload as the browser posts it: a multipart form with the file part, or no file part at all."""
    data = {} if upload is None else {"file": upload}
    return client.post(f"{BASE}/candidates/{candidate_pk}/files", data)


def _vacancy_body(vacancy: Vacancy, **over: Any) -> dict[str, Any]:
    """The vacancy pop-up as the React form posts it: ids as numbers or null, dates as text ("" when blank)."""
    body: dict[str, Any] = {
        "title": vacancy.title,
        "position": vacancy.position_id,
        "department": vacancy.department_id,
        "branch": vacancy.branch_id,
        "headcount": vacancy.headcount,
        "hiring_manager": vacancy.hiring_manager_id,
        "deadline": "",
        "desired_start": "",
        "description": vacancy.description,
        "status": vacancy.status,
    }
    body.update(over)
    return body


def _new_body(vacancy: Vacancy, **over: Any) -> dict[str, Any]:
    """The add pop-up: the same fields, without a status."""
    body = _vacancy_body(vacancy, **over)
    body.pop("status")
    return body


def _candidate_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "surname": "Шинэ",
        "given_name": "Бат",
        "phone": "",
        "email": "",
        "source": "",
        "notes": "",
    }
    body.update(over)
    return body


def _write_calls(vacancy: Vacancy, candidate: Candidate) -> list[tuple[str, dict[str, Any] | None]]:
    """Every write route with a body the schema takes, so a refusal comes from the rights and not from the body."""
    return [
        (f"{BASE}/vacancies", _new_body(vacancy)),
        (f"{BASE}/vacancies/{vacancy.pk}", _vacancy_body(vacancy)),
        (f"{BASE}/vacancies/{vacancy.pk}/candidates", _candidate_body()),
        (f"{BASE}/candidates/{candidate.pk}/move", {"to": "screening", "note": ""}),
        (f"{BASE}/candidates/{candidate.pk}/reject", {"reason": "Туршлага", "withdrawn": False}),
        (f"{BASE}/candidates/{candidate.pk}/reopen", None),
        (f"{BASE}/candidates/{candidate.pk}/files", None),
        (f"{BASE}/candidates/{candidate.pk}/convert", None),
        (f"{BASE}/purge", None),
    ]


def _bad_upload(kind: str) -> SimpleUploadedFile:
    if kind == "exe":
        return SimpleUploadedFile("virus.exe", b"MZ", content_type="application/octet-stream")
    if kind == "empty":
        return SimpleUploadedFile("cv.pdf", b"", content_type="application/pdf")
    return SimpleUploadedFile("big.pdf", b"0" * (MAX_BYTES + 1), content_type="application/pdf")


# --- rights, login and the module gate -----------------------------------------------------------------------------


def test_every_write_needs_a_signed_in_user(vacancy: Vacancy, candidate: Candidate) -> None:
    before = _rows()
    anonymous = Client()
    for url, body in _write_calls(vacancy, candidate):
        response = _post(anonymous, url, body)
        assert response.status_code == 401, url
        assert response.json() == NOT_LOGGED_IN, url
    assert _rows() == before


def test_the_download_needs_a_signed_in_user(candidate: Candidate, actor: User) -> None:
    row = files.save(candidate, SimpleUploadedFile("cv.pdf", b"%PDF", content_type="application/pdf"), by=actor)
    response = Client().get(f"{BASE}/files/{row.pk}")
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN


def test_module_off_is_404_on_every_write_and_the_download(
    hr: User, manager_user: User, vacancy: Vacancy, candidate: Candidate, actor: User
) -> None:
    row = files.save(candidate, SimpleUploadedFile("cv.pdf", b"%PDF", content_type="application/pdf"), by=actor)
    modules.set_state({"recruitment": False})
    before = _rows()
    for user in (hr, manager_user):
        client = _client(user)
        for url, body in _write_calls(vacancy, candidate):
            response = _post(client, url, body)
            assert response.status_code == 404, url
            assert response.json() == NOT_FOUND, url
        download = client.get(f"{BASE}/files/{row.pk}")
        assert download.status_code == 404
    assert _rows() == before


def test_hiring_manager_gets_403_on_every_write_and_nothing_is_written(
    manager_user: User, mine: Vacancy, mine_candidate: Candidate
) -> None:
    client = _client(manager_user)
    before = _rows()
    for url, body in _write_calls(mine, mine_candidate):
        response = _post(client, url, body)
        assert response.status_code == 403, url
        assert response.json() == FORBIDDEN, url
    assert _rows() == before


def test_hiring_manager_may_comment_and_download_on_own_candidate(
    manager_user: User, mine_candidate: Candidate, actor: User
) -> None:
    client = _client(manager_user)
    comment = _post(client, f"{BASE}/candidates/{mine_candidate.pk}/comment", {"text": "Сайн нэр дэвшигч"})
    assert comment.json() == OK
    assert CandidateComment.objects.filter(candidate=mine_candidate, text="Сайн нэр дэвшигч").exists()
    row = files.save(mine_candidate, SimpleUploadedFile("cv.pdf", b"%PDF", content_type="application/pdf"), by=actor)
    download = client.get(f"{BASE}/files/{row.pk}")
    assert download.status_code == 200


def test_writes_on_a_vacancy_or_candidate_the_user_cannot_see_are_404(
    manager_user: User, vacancy: Vacancy, candidate: Candidate
) -> None:
    client = _client(manager_user)
    before = _rows()
    for pk in (999999, vacancy.pk):
        response = _post(client, f"{BASE}/vacancies/{pk}", _vacancy_body(vacancy, title="Өөрчилсөн"))
        assert response.status_code == 404
        assert response.json() == NOT_FOUND
    for url, body in (
        (f"{BASE}/vacancies/{vacancy.pk}/candidates", _candidate_body()),
        (f"{BASE}/candidates/{candidate.pk}/move", {"to": "screening"}),
        (f"{BASE}/candidates/{candidate.pk}/comment", {"text": "Сэтгэгдэл"}),
        (f"{BASE}/candidates/{candidate.pk}/reject", {"reason": "Туршлага"}),
        (f"{BASE}/candidates/{candidate.pk}/convert", None),
    ):
        assert _post(client, url, body).status_code == 404, url
    assert _upload(client, candidate.pk).status_code == 404
    assert _rows() == before
    vacancy.refresh_from_db()
    assert vacancy.title == "Нягтлан"


# --- vacancy create and update -------------------------------------------------------------------------------------


def test_create_vacancy_opens_it_and_writes_the_audit_line(hr: User, vacancy: Vacancy) -> None:
    logged = SystemLogEntry.objects.filter(action="vacancy_created").count()
    body = _post(_client(hr), f"{BASE}/vacancies", _new_body(vacancy, title="Шинэ ажлын байр")).json()
    assert set(body) == {"ok", "error", "field_errors", "form_errors", "id"}
    assert body["ok"] is True and body["error"] == "" and body["field_errors"] == {} and body["form_errors"] == []
    created = Vacancy.objects.get(pk=body["id"])
    assert created.title == "Шинэ ажлын байр"
    assert created.status == VacancyStatus.OPEN
    assert created.created_by_id == hr.pk
    assert SystemLogEntry.objects.filter(action="vacancy_created").count() == logged + 1


@pytest.mark.parametrize(
    ("field", "over"),
    [
        ("title", {"title": ""}),
        ("title", {"title": "Б" * 201}),
        ("headcount", {"headcount": 0}),
        ("position", {"position": 999999}),
    ],
)
def test_create_vacancy_refusals_are_field_errors_and_write_nothing(
    hr: User, vacancy: Vacancy, field: str, over: dict[str, Any]
) -> None:
    before = _rows()
    body = _post(_client(hr), f"{BASE}/vacancies", _new_body(vacancy, **over)).json()
    assert body["ok"] is False
    assert field in body["field_errors"]
    assert _rows() == before


def test_update_of_an_unknown_or_foreign_vacancy_is_404_before_the_right_check(
    manager_user: User, vacancy: Vacancy
) -> None:
    client = _client(manager_user)
    response = _post(client, f"{BASE}/vacancies/999999", _vacancy_body(vacancy))
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_status_filled_by_hand_is_refused_and_nothing_changes(hr: User, vacancy: Vacancy) -> None:
    body = _post(_client(hr), f"{BASE}/vacancies/{vacancy.pk}", _vacancy_body(vacancy, status="filled")).json()
    assert body["ok"] is False
    assert "status" in body["field_errors"]
    vacancy.refresh_from_db()
    assert vacancy.status == VacancyStatus.OPEN


def test_raising_the_headcount_reopens_a_filled_vacancy(hr: User, vacancy: Vacancy, candidate: Candidate) -> None:
    Candidate.objects.filter(pk=candidate.pk).update(stage=Stage.HIRED)
    pipeline.refresh_filled(vacancy)
    vacancy.refresh_from_db()
    assert vacancy.status == VacancyStatus.FILLED
    logged = SystemLogEntry.objects.filter(action="vacancy_changed").count()
    body = _post(
        _client(hr), f"{BASE}/vacancies/{vacancy.pk}", _vacancy_body(vacancy, headcount=2, status="filled")
    ).json()
    assert body == OK
    vacancy.refresh_from_db()
    assert vacancy.status == VacancyStatus.OPEN and vacancy.headcount == 2
    assert SystemLogEntry.objects.filter(action="vacancy_changed").count() == logged + 1


# --- candidate add ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [VacancyStatus.CLOSED, VacancyStatus.FILLED])
def test_add_candidate_to_a_closed_or_filled_vacancy_is_refused(hr: User, vacancy: Vacancy, status: str) -> None:
    Vacancy.objects.filter(pk=vacancy.pk).update(status=status)
    before = _rows()
    body = _post(_client(hr), f"{BASE}/vacancies/{vacancy.pk}/candidates", _candidate_body()).json()
    assert body == {"ok": False, "error": NOT_OPEN, "field_errors": {}, "form_errors": []}
    assert _rows() == before


def test_add_candidate_with_an_empty_surname_is_a_field_error(hr: User, vacancy: Vacancy) -> None:
    before = _rows()
    body = _post(_client(hr), f"{BASE}/vacancies/{vacancy.pk}/candidates", _candidate_body(surname="")).json()
    assert body["ok"] is False
    assert "surname" in body["field_errors"]
    assert _rows() == before


def test_add_candidate_adds_a_new_candidate_with_its_first_event(hr: User, vacancy: Vacancy) -> None:
    body = _post(
        _client(hr),
        f"{BASE}/vacancies/{vacancy.pk}/candidates",
        _candidate_body(surname="Сүхээ", given_name="Ганаа", phone="99112233", source="Вэбсайт"),
    ).json()
    assert body == OK
    row = Candidate.objects.get(vacancy=vacancy, surname="Сүхээ")
    assert row.stage == Stage.NEW
    assert row.created_by_id == hr.pk
    assert row.phone == "99112233" and row.source == "Вэбсайт"
    first = CandidateEvent.objects.get(candidate=row)
    assert first.from_stage == "" and first.to_stage == Stage.NEW


# --- moves, rejection, reopen, comments ------------------------------------------------------------------------------


def test_move_to_the_next_step_is_ok_and_logs_without_the_name(hr: User, candidate: Candidate) -> None:
    logged = SystemLogEntry.objects.filter(action="candidate_moved").count()
    body = _post(_client(hr), f"{BASE}/candidates/{candidate.pk}/move", {"to": "screening", "note": " Ярилцлага "})
    assert body.json() == OK
    candidate.refresh_from_db()
    assert candidate.stage == Stage.SCREENING
    assert CandidateEvent.objects.filter(candidate=candidate, to_stage=Stage.SCREENING, note="Ярилцлага").exists()
    assert SystemLogEntry.objects.filter(action="candidate_moved").count() == logged + 1
    entry = SystemLogEntry.objects.filter(action="candidate_moved").latest("pk")
    assert entry.target_label == f"Ажил хүсэгч #{candidate.pk}"
    assert "Дорж" not in f"{entry.target_label} {entry.message}"


@pytest.mark.parametrize(
    ("to", "text"),
    [("hired", NOT_HIRED_BY_MOVE), ("rejected", REJECT_BY_REJECT), ("garbage", UNKNOWN_STAGE)],
)
def test_move_refusals_carry_the_service_text_and_change_nothing(
    hr: User, candidate: Candidate, to: str, text: str
) -> None:
    before = _rows()
    body = _post(_client(hr), f"{BASE}/candidates/{candidate.pk}/move", {"to": to, "note": ""}).json()
    assert body == {"ok": False, "error": text, "field_errors": {}, "form_errors": []}
    candidate.refresh_from_db()
    assert candidate.stage == Stage.NEW
    assert _rows() == before


def test_move_of_a_rejected_candidate_asks_to_reopen_first(hr: User, candidate: Candidate, actor: User) -> None:
    pipeline.reject(candidate, by=actor, reason="Туршлага хүрэлцэхгүй")
    body = _post(_client(hr), f"{BASE}/candidates/{candidate.pk}/move", {"to": "screening"}).json()
    assert body["ok"] is False and body["error"] == REOPEN_FIRST
    candidate.refresh_from_db()
    assert candidate.stage == Stage.REJECTED


def test_reject_without_a_reason_is_a_field_error(hr: User, candidate: Candidate) -> None:
    body = _post(_client(hr), f"{BASE}/candidates/{candidate.pk}/reject", {"reason": "  ", "withdrawn": False}).json()
    assert body["ok"] is False
    assert body["field_errors"] == {"reason": [REASON_NEEDED]}
    candidate.refresh_from_db()
    assert candidate.stage == Stage.NEW


def test_withdrawn_without_a_reason_is_ok(hr: User, candidate: Candidate) -> None:
    body = _post(_client(hr), f"{BASE}/candidates/{candidate.pk}/reject", {"reason": "", "withdrawn": True}).json()
    assert body == OK
    candidate.refresh_from_db()
    assert candidate.stage == Stage.WITHDRAWN
    assert candidate.closed_at is not None


def test_a_second_reject_is_refused(hr: User, candidate: Candidate) -> None:
    client = _client(hr)
    assert _post(client, f"{BASE}/candidates/{candidate.pk}/reject", {"reason": "Туршлага"}).json() == OK
    body = _post(client, f"{BASE}/candidates/{candidate.pk}/reject", {"reason": "Дахин"}).json()
    assert body == {"ok": False, "error": ALREADY_CLOSED, "field_errors": {}, "form_errors": []}


def test_reopen_a_rejected_candidate_clears_the_reason(hr: User, candidate: Candidate, actor: User) -> None:
    pipeline.reject(candidate, by=actor, reason="Туршлага")
    assert _post(_client(hr), f"{BASE}/candidates/{candidate.pk}/reopen").json() == OK
    candidate.refresh_from_db()
    assert candidate.stage == Stage.NEW
    assert candidate.reject_reason == ""
    assert candidate.closed_at is None


def test_reopen_an_open_candidate_is_refused(hr: User, candidate: Candidate) -> None:
    body = _post(_client(hr), f"{BASE}/candidates/{candidate.pk}/reopen").json()
    assert body == {"ok": False, "error": NOT_REOPENABLE, "field_errors": {}, "form_errors": []}


def test_comment_adds_a_row(hr: User, candidate: Candidate) -> None:
    body = _post(_client(hr), f"{BASE}/candidates/{candidate.pk}/comment", {"text": "  Сайн  "}).json()
    assert body == OK
    comment = CandidateComment.objects.get(candidate=candidate)
    assert comment.text == "Сайн"


def test_a_blank_comment_is_refused(hr: User, candidate: Candidate) -> None:
    before = _rows()
    body = _post(_client(hr), f"{BASE}/candidates/{candidate.pk}/comment", {"text": "   "}).json()
    assert body == {"ok": False, "error": EMPTY_COMMENT, "field_errors": {}, "form_errors": []}
    assert _rows() == before


# --- CV upload and download ------------------------------------------------------------------------------------------


def test_pdf_upload_is_stored_under_a_random_name(hr: User, candidate: Candidate, settings: SettingsWrapper) -> None:
    upload = SimpleUploadedFile("cv.pdf", b"%PDF-1.4 test", content_type="application/pdf")
    body = _upload(_client(hr), candidate.pk, upload).json()
    assert body == OK
    row = CandidateFile.objects.get(candidate=candidate)
    assert row.name == "cv.pdf"
    stored = Path(row.file)
    assert stored.name != "cv.pdf" and stored.suffix == ".pdf"
    assert Path(settings.RECRUITMENT_FILES_ROOT, row.file).is_file()
    assert Path(settings.RECRUITMENT_FILES_ROOT).resolve() in Path(files.storage().path(row.file)).resolve().parents


@pytest.mark.parametrize(("kind", "text"), [("exe", BAD_TYPE), ("empty", EMPTY_FILE), ("big", TOO_BIG)])
def test_refused_uploads_give_their_text_and_store_nothing(
    hr: User, candidate: Candidate, kind: str, text: str
) -> None:
    body = _upload(_client(hr), candidate.pk, _bad_upload(kind)).json()
    assert body == {"ok": False, "error": text, "field_errors": {}, "form_errors": []}
    assert CandidateFile.objects.count() == 0


def test_no_file_is_refused_with_its_text(hr: User, candidate: Candidate) -> None:
    body = _upload(_client(hr), candidate.pk).json()
    assert body == {"ok": False, "error": NO_FILE, "field_errors": {}, "form_errors": []}
    assert CandidateFile.objects.count() == 0


def test_download_keeps_the_original_name_and_writes_the_audit_line(
    hr: User, candidate: Candidate, actor: User
) -> None:
    row = files.save(
        candidate, SimpleUploadedFile("cv.pdf", b"%PDF-1.4 test", content_type="application/pdf"), by=actor
    )
    logged = SystemLogEntry.objects.filter(action="candidate_file_downloaded").count()
    response = _client(hr).get(f"{BASE}/files/{row.pk}")
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"%PDF-1.4 test"
    assert 'filename="cv.pdf"' in response["Content-Disposition"]
    assert response["Cache-Control"] == "no-store"
    assert SystemLogEntry.objects.filter(action="candidate_file_downloaded").count() == logged + 1


def test_download_of_a_file_the_user_cannot_see_is_404(manager_user: User, candidate: Candidate, actor: User) -> None:
    row = files.save(candidate, SimpleUploadedFile("cv.pdf", b"%PDF", content_type="application/pdf"), by=actor)
    response = _client(manager_user).get(f"{BASE}/files/{row.pk}")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_download_of_a_missing_stored_file_is_404(hr: User, candidate: Candidate, actor: User) -> None:
    row = CandidateFile.objects.create(candidate=candidate, file="missing/none.pdf", name="cv.pdf", uploaded_by=actor)
    response = _client(hr).get(f"{BASE}/files/{row.pk}")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


# --- convert and purge -----------------------------------------------------------------------------------------------


def test_convert_of_an_open_candidate_answers_the_hire_path_and_writes_nothing(hr: User, candidate: Candidate) -> None:
    before = _rows()
    body = _post(_client(hr), f"{BASE}/candidates/{candidate.pk}/convert").json()
    assert body["ok"] is True
    assert body["error"] == ""
    assert body["path"].startswith("/employees/new/?")
    assert f"candidate={candidate.pk}" in body["path"]
    assert _rows() == before
    candidate.refresh_from_db()
    assert candidate.employee_id is None


def test_convert_on_a_closed_vacancy_is_refused(hr: User, vacancy: Vacancy, candidate: Candidate) -> None:
    Vacancy.objects.filter(pk=vacancy.pk).update(status=VacancyStatus.CLOSED)
    before = _rows()
    events_before = CandidateEvent.objects.filter(candidate=candidate).count()
    body = _post(_client(hr), f"{BASE}/candidates/{candidate.pk}/convert").json()
    assert body == {"ok": False, "path": "", "error": VACANCY_NOT_OPEN}
    candidate.refresh_from_db()
    assert candidate.stage == Stage.NEW and candidate.employee_id is None
    assert CandidateEvent.objects.filter(candidate=candidate).count() == events_before
    assert _rows() == before


def test_convert_of_a_hired_candidate_is_refused(hr: User, candidate: Candidate) -> None:
    Candidate.objects.filter(pk=candidate.pk).update(stage=Stage.HIRED)
    before = _rows()
    events_before = CandidateEvent.objects.filter(candidate=candidate).count()
    body = _post(_client(hr), f"{BASE}/candidates/{candidate.pk}/convert").json()
    assert body == {"ok": False, "path": "", "error": NOT_CONVERTIBLE}
    candidate.refresh_from_db()
    assert candidate.stage == Stage.HIRED and candidate.employee_id is None
    assert CandidateEvent.objects.filter(candidate=candidate).count() == events_before
    assert _rows() == before


def test_purge_removes_only_old_closed_candidates_and_their_files(hr: User, actor: User, vacancy: Vacancy) -> None:
    old = _add(vacancy, actor, "Хуучин")
    recent = _add(vacancy, actor, "Шинэ")
    open_one = _add(vacancy, actor, "Нээлттэй")
    pipeline.reject(old, by=actor, reason="Туршлага")
    pipeline.reject(recent, by=actor, reason="Туршлага")
    Candidate.objects.filter(pk=old.pk).update(closed_at=datetime(2020, 1, 1, tzinfo=UTC))
    stored = files.save(old, SimpleUploadedFile("cv.pdf", b"%PDF", content_type="application/pdf"), by=actor)
    stored_path = Path(files.storage().location, stored.file)
    assert stored_path.is_file()

    client = _client(hr)
    assert _post(client, f"{BASE}/purge").json() == {"ok": True, "deleted": 1}
    assert not Candidate.objects.filter(pk=old.pk).exists()
    assert Candidate.objects.filter(pk__in=[recent.pk, open_one.pk]).count() == 2
    assert not stored_path.exists()
    assert _post(client, f"{BASE}/purge").json() == {"ok": True, "deleted": 0}
