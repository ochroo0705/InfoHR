"""Candidate CV files: private storage outside MEDIA_ROOT, served only through a view that checks visibility."""

import os
import uuid
from pathlib import PurePath
from typing import Any

from accounts.audit import Category, record_safe
from accounts.models import User
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.http import FileResponse

from recruitment.models import Candidate, CandidateFile

MAX_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = frozenset({"pdf", "doc", "docx", "png", "jpg", "jpeg"})

AUDIT_ACTION_ADDED = "candidate_file_added"
AUDIT_ACTION_DOWNLOADED = "candidate_file_downloaded"


class FileRejected(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class RecruitmentFileStorage(FileSystemStorage):
    """Lives under settings.RECRUITMENT_FILES_ROOT, read on every access so tests can override the setting."""

    @property
    def base_location(self) -> str:
        return str(settings.RECRUITMENT_FILES_ROOT)

    @property
    def location(self) -> str:
        return os.path.abspath(self.base_location)


def storage() -> FileSystemStorage:
    return RecruitmentFileStorage()


def save(candidate: Candidate, upload: Any, *, by: User) -> CandidateFile:
    """Store `upload` (a Django UploadedFile) under a random name; the original name is kept in `name`."""
    original = PurePath(str(upload.name).replace("\\", "/")).name.strip()
    extension = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise FileRejected("Зөвхөн PDF, Word (doc, docx) эсвэл зураг (png, jpg) файл оруулна уу.")
    if upload.size > MAX_BYTES:
        raise FileRejected(f"Файл {MAX_BYTES // (1024 * 1024)} MB-аас том байна.")
    if upload.size == 0:
        raise FileRejected("Файл хоосон байна.")
    path = storage().save(f"{candidate.pk}/{uuid.uuid4().hex}.{extension}", upload)
    row = CandidateFile.objects.create(candidate=candidate, file=path, name=original[:255], uploaded_by=by)
    record_safe(
        Category.HR,
        AUDIT_ACTION_ADDED,
        actor=by,
        target_type="Ажил хүсэгч",
        target_label=f"Ажил хүсэгч #{candidate.pk}",
        message=f"Файл нэмсэн ({extension})",
    )
    return row


def open(file: CandidateFile, *, by: User | None = None) -> FileResponse:  # noqa: A001
    """A download response for `file`. The caller has already checked visibility."""
    handle = storage().open(file.file, "rb")
    if by is not None:
        record_safe(
            Category.HR,
            AUDIT_ACTION_DOWNLOADED,
            actor=by,
            target_type="Ажил хүсэгч",
            target_label=f"Ажил хүсэгч #{file.candidate_id}",
        )
    return FileResponse(handle, as_attachment=True, filename=file.name)


def delete_stored(paths: list[str]) -> None:
    """Remove stored files from disk (missing ones are ignored), then empty candidate folders."""
    store = storage()
    folders: set[str] = set()
    for path in paths:
        try:
            store.delete(path)
        except OSError:
            continue
        folders.add(os.path.dirname(path))
    for folder in folders:
        try:
            os.rmdir(store.path(folder))
        except OSError:
            pass
