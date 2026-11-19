"""The order file routes, as the React page links them (plain links, so the browser downloads or shows the file):

- GET /api/v1/employees/{pk}/orders/{order_id}/file: the signed scan, inline (logged as an export).
- GET /api/v1/employees/{pk}/orders/{order_id}/document: the order as a Word draft (logged as an export).
- GET /api/v1/employees/{pk}/orders/{order_id}/document/pdf: the same as a PDF (logged as an export).
- GET /api/v1/employees/{pk}/orders/{order_id}/signing-image: the signature picture stamped on a signed order.

The rules and the headers are employees.services.order_files (the Django views use the same functions). This module
only resolves the employee and the order (404 outside the user's scope), maps the service's 404/403 and logs the
export. Responses are the Django responses of `file_response`, so no response schema is declared.
"""

from accounts.audit import record_export
from django.http import HttpRequest, HttpResponse
from employees.services import order_files
from ninja import Router
from ninja.security import django_auth

from api.employee_writes import _scoped_employee
from api.orders import _order_of
from api.popups import request_user, service_errors

order_files_router = Router(tags=["employees"])


@order_files_router.get("/{pk}/orders/{order_id}/file", auth=django_auth)
def order_file_download(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    """The signed scan of the order. Hire and rehire scans need the salary right (403 without it)."""
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    order = _order_of(employee, order_id)
    with service_errors():
        payload = order_files.scan_payload(user, order)
    record_export(request, "download_order", "Гарын үсэгтэй файл: " + order_files.order_label(order, employee))
    return order_files.file_response(payload)


def _document(request: HttpRequest, pk: int, order_id: int, *, pdf: bool) -> HttpResponse:
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    order = _order_of(employee, order_id)
    with service_errors():
        payload = order_files.document_payload(user, order, pdf=pdf)
    record_export(request, "download_order", order_files.order_label(order, employee))
    return order_files.file_response(payload)


@order_files_router.get("/{pk}/orders/{order_id}/document", auth=django_auth)
def order_document_download(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    """The order filled from its Word template, as .docx (a draft to print and sign). 403 without the manage right."""
    return _document(request, pk, order_id, pdf=False)


@order_files_router.get("/{pk}/orders/{order_id}/document/pdf", auth=django_auth)
def order_document_pdf_download(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    """The same order as a PDF. 403 without the manage right; a cancelled order is 404."""
    return _document(request, pk, order_id, pdf=True)


@order_files_router.get("/{pk}/orders/{order_id}/signing-image", auth=django_auth)
def order_signing_image_download(request: HttpRequest, pk: int, order_id: int) -> HttpResponse:
    """The signature picture of a signed order. Anyone who may see the employee may see it; not logged."""
    user = request_user(request)
    employee = _scoped_employee(user, pk)
    order = _order_of(employee, order_id)
    with service_errors():
        payload = order_files.signing_image_payload(order)
    return order_files.file_response(payload)
