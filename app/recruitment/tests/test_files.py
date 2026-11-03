from pathlib import Path

import pytest
from accounts.models import SystemLogEntry, User
from django.core.files.uploadedfile import SimpleUploadedFile

from recruitment.models import Candidate
from recruitment.services import files


def test_save_stores_under_random_name_and_keeps_original(candidate: Candidate, actor: User) -> None:
    row = files.save(candidate, SimpleUploadedFile("Миний CV.PDF", b"%PDF-1 hello"), by=actor)
    assert row.name == "Миний CV.PDF"
    assert row.file.startswith(f"{candidate.pk}/") and row.file.endswith(".pdf")
    assert "CV" not in row.file
    assert Path(files.storage().path(row.file)).read_bytes() == b"%PDF-1 hello"
    assert row.uploaded_by == actor
    assert SystemLogEntry.objects.filter(action="candidate_file_added").exists()


def test_two_uploads_of_same_name_do_not_collide(candidate: Candidate, actor: User) -> None:
    a = files.save(candidate, SimpleUploadedFile("cv.pdf", b"1"), by=actor)
    b = files.save(candidate, SimpleUploadedFile("cv.pdf", b"2"), by=actor)
    assert a.file != b.file


@pytest.mark.parametrize("name", ["virus.exe", "page.html", "noext", "cv.pdf.exe", "../x.sh"])
def test_bad_extension_refused(candidate: Candidate, actor: User, name: str) -> None:
    with pytest.raises(files.FileRejected) as exc:
        files.save(candidate, SimpleUploadedFile(name, b"x"), by=actor)
    assert exc.value.message
    assert not candidate.files.exists()


@pytest.mark.parametrize("name", ["a.pdf", "a.doc", "a.docx", "a.png", "a.jpg", "a.JPEG"])
def test_allowed_extensions(candidate: Candidate, actor: User, name: str) -> None:
    assert files.save(candidate, SimpleUploadedFile(name, b"x"), by=actor).pk


def test_size_limit(candidate: Candidate, actor: User) -> None:
    files.save(candidate, SimpleUploadedFile("ok.pdf", b"x" * files.MAX_BYTES), by=actor)
    with pytest.raises(files.FileRejected):
        files.save(candidate, SimpleUploadedFile("big.pdf", b"x" * (files.MAX_BYTES + 1)), by=actor)
    assert candidate.files.count() == 1


def test_open_returns_download(candidate: Candidate, actor: User) -> None:
    row = files.save(candidate, SimpleUploadedFile("cv.pdf", b"%PDF-bytes"), by=actor)
    response = files.open(row, by=actor)
    assert b"".join(response.streaming_content) == b"%PDF-bytes"  # type: ignore[arg-type]
    assert "attachment" in response["Content-Disposition"] and "cv.pdf" in response["Content-Disposition"]
    assert SystemLogEntry.objects.filter(action="candidate_file_downloaded").exists()
