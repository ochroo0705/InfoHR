from django.conf import settings
from django.core.mail import send_mail

from welcome.models import DemoRequest


def create_request(
    *,
    name: str,
    email: str,
    organisation: str,
    phone: str,
    size_band: str,
    note: str,
    ip: str | None,
    notify: bool = True,
) -> DemoRequest:
    """Save the request first, then try to mail HR. Mail problems never lose the request.

    notify=False (the mail budget is used up) stores the request with status "failed" and sends no mail.
    """
    demo_request = DemoRequest.objects.create(
        name=name.strip(),
        email=email.strip(),
        organisation=organisation.strip(),
        phone=phone.strip(),
        size_band=size_band.strip(),
        note=note.strip(),
        ip=(ip or "").strip(),
        mail_status="pending",
    )
    if notify:
        send_hr_mail(demo_request)
    else:
        demo_request.mail_status = "failed"
        demo_request.mail_error = "mail budget used"
        demo_request.save(update_fields=["mail_status", "mail_error"])
    demo_request.refresh_from_db()
    return demo_request


def clean_recipients(raw: list[str]) -> list[str]:
    """Strip each address and drop blanks, so "a@x.mn, b@x.mn" in the env never yields " b@x.mn"."""
    return [address.strip() for address in raw if address.strip()]


def send_hr_mail(demo_request: DemoRequest) -> None:
    """Mail the configured recipients about a new request and record the outcome on the row."""
    recipients = clean_recipients(list(settings.DEMO_REQUEST_NOTIFY))
    if not settings.EMAIL_HOST or not recipients:
        demo_request.mail_status = "not_configured"
        demo_request.mail_error = ""
        demo_request.save(update_fields=["mail_status", "mail_error"])
        return

    body = "\n".join(
        [
            f"Нэр: {demo_request.name}",
            f"Имэйл: {demo_request.email}",
            f"Байгууллага: {demo_request.organisation}",
            f"Утас: {demo_request.phone}",
            f"Ажилтны тоо: {demo_request.size_band}",
            f"Тайлбар: {demo_request.note}",
            f"IP хаяг: {demo_request.ip}",
            f"Үүсгэсэн огноо: {demo_request.created_at}",
        ]
    )
    try:
        send_mail(
            # send_mail rejects CR/LF in headers, so a newline in the organisation name becomes a space.
            subject=f"Шинэ демо хүсэлт: {' '.join(demo_request.organisation.split())}",
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )
    except Exception as exc:
        demo_request.mail_status = "failed"
        demo_request.mail_error = str(exc)[:300]
    else:
        demo_request.mail_status = "sent"
        demo_request.mail_error = ""
    demo_request.save(update_fields=["mail_status", "mail_error"])
