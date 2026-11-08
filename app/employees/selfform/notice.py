"""The consent text an employee agrees to when they submit the self-form.

DEFAULT_NOTICE is a PLACEHOLDER. The organisation must read and approve the wording (and its legal basis) before
the self-form is used for real people. An admin can replace it per install with CompanySettings.selfform_notice.

Two tokens are filled in: {company} (CompanySettings.name) and {days} (CompanySettings.selfform_retention_days).
Only those two are replaced, with plain text replacement, so a stray brace in an admin-typed text cannot crash.

Spec: docs/superpowers/specs/2026-11-08-employee-self-form-design.md
"""

import hashlib

from employees.models import CompanySettings

DEFAULT_NOTICE = (
    "{company} нь таны оруулсан хувийн мэдээллийг ажилд авах болон ажилтны бүртгэл хөтлөх зорилгоор боловсруулна. "
    "Таны хариултууд HR хэлтэс шийдвэр гаргах хүртэл хадгалагдана. "
    "HR хэлтэс баталгаажуулсан эсвэл татгалзсанаас, эсвэл холбоосыг цуцалсанаас хойш {days} хоногийн дараа "
    "таны хадгалсан хариултууд болон зургийг түр хуулбараас устгана. "
    "Баталгаажуулсан бол ажилтны бүртгэл үүсгэх ба энэ бүртгэл байгууллагын HR бүртгэл тул хэвээр үлдэнэ. "
    "Илгээгээгүй маягтыг холбоосын хугацаа дууссанаас хойш {days} хоногийн дараа устгана. "
    "Устгасны дараа HR-ийн жагсаалтад зөвхөн таны оруулсан нэр, огноо, шийдвэр үлдэнэ. "
    "Мэдээллээ илгээхээсээ өмнө бүх талбарыг зөв бөглөсөн эсэхээ шалгана уу."
)

_FALLBACK_COMPANY = "Байгууллага"


def notice_for(settings: CompanySettings) -> str:
    """The admin's text when one is set, else DEFAULT_NOTICE; company and retention days filled in."""
    text = settings.selfform_notice.strip() or DEFAULT_NOTICE
    company = settings.name.strip() or _FALLBACK_COMPANY
    return text.replace("{company}", company).replace("{days}", str(settings.selfform_retention_days))


def notice_digest(text: str) -> str:
    """A short SHA-256 hex digest of the notice text. The public form carries it in a hidden input, so the submit
    can tell whether the text the person read is still the text in force."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
