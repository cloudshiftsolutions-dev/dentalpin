"""Email template editor API (Settings → Communications → Email templates).

Mounted under ``/notifications/email-templates`` — a separate prefix from
the generic ``/templates/{template_id}`` CRUD so the paths never collide.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import ClinicContext, get_clinic_context, require_permission
from app.core.pdf_locales import PDF_LOCALE_PATTERN
from app.core.schemas import ApiResponse
from app.database import get_db

from . import template_editor
from .schemas import (
    EmailTemplateDraft,
    EmailTemplateEditorDetail,
    EmailTemplateEditorSummary,
    EmailTemplatePreviewResponse,
    EmailTemplateSave,
    EmailTemplateTestResponse,
)

template_editor_router = APIRouter(prefix="/email-templates")

Locale = Annotated[str, Query(pattern=PDF_LOCALE_PATTERN)]
CanRead = Annotated[None, Depends(require_permission("notifications.templates.read"))]
CanWrite = Annotated[None, Depends(require_permission("notifications.templates.write"))]


def _ensure_editable(template_key: str) -> None:
    if not template_editor.is_editable(template_key):
        raise HTTPException(status_code=404, detail="Email template not found")


def _invalid(exc: template_editor.TemplateEditorError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@template_editor_router.get("", response_model=ApiResponse[list[EmailTemplateEditorSummary]])
async def list_email_templates(
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: CanRead,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[EmailTemplateEditorSummary]]:
    """Editable patient emails with the languages this clinic has customised."""
    return ApiResponse(data=await template_editor.list_summaries(db, ctx.clinic_id))


@template_editor_router.get(
    "/{template_key}", response_model=ApiResponse[EmailTemplateEditorDetail]
)
async def get_email_template(
    template_key: str,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: CanRead,
    db: Annotated[AsyncSession, Depends(get_db)],
    locale: Locale = "en",
) -> ApiResponse[EmailTemplateEditorDetail]:
    """Current subject/HTML (custom or built-in) plus the built-in defaults."""
    _ensure_editable(template_key)
    return ApiResponse(
        data=await template_editor.get_detail(db, ctx.clinic_id, template_key, locale)
    )


@template_editor_router.post(
    "/{template_key}/preview", response_model=ApiResponse[EmailTemplatePreviewResponse]
)
async def preview_email_template(
    template_key: str,
    data: EmailTemplateDraft,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: CanRead,
    locale: Locale = "en",
) -> ApiResponse[EmailTemplatePreviewResponse]:
    """Render a draft with sample data. 422 carries the template error."""
    _ensure_editable(template_key)
    try:
        preview = template_editor.render_preview(ctx.clinic, locale, data.subject, data.body_html)
    except template_editor.TemplateEditorError as exc:
        raise _invalid(exc) from exc
    return ApiResponse(data=preview)


@template_editor_router.put(
    "/{template_key}", response_model=ApiResponse[EmailTemplateEditorDetail]
)
async def save_email_template(
    template_key: str,
    data: EmailTemplateSave,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: CanWrite,
    db: Annotated[AsyncSession, Depends(get_db)],
    locale: Locale = "en",
) -> ApiResponse[EmailTemplateEditorDetail]:
    """Create or update this clinic's version of the email."""
    _ensure_editable(template_key)
    try:
        detail = await template_editor.save_override(
            db,
            ctx.clinic,
            template_key,
            locale,
            subject=data.subject,
            body_html=data.body_html,
            is_active=data.is_active,
        )
    except template_editor.TemplateEditorError as exc:
        raise _invalid(exc) from exc
    return ApiResponse(data=detail)


@template_editor_router.delete(
    "/{template_key}", response_model=ApiResponse[EmailTemplateEditorDetail]
)
async def reset_email_template(
    template_key: str,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: CanWrite,
    db: Annotated[AsyncSession, Depends(get_db)],
    locale: Locale = "en",
) -> ApiResponse[EmailTemplateEditorDetail]:
    """Drop the clinic version so the built-in email is used again."""
    _ensure_editable(template_key)
    return ApiResponse(
        data=await template_editor.reset_override(db, ctx.clinic_id, template_key, locale)
    )


@template_editor_router.post(
    "/{template_key}/test", response_model=ApiResponse[EmailTemplateTestResponse]
)
async def send_test_email_template(
    template_key: str,
    data: EmailTemplateDraft,
    ctx: Annotated[ClinicContext, Depends(get_clinic_context)],
    _: CanWrite,
    db: Annotated[AsyncSession, Depends(get_db)],
    locale: Locale = "en",
) -> ApiResponse[EmailTemplateTestResponse]:
    """Send the draft, filled with sample data, to the signed-in user only."""
    _ensure_editable(template_key)
    if not ctx.user.email:
        raise HTTPException(status_code=400, detail="Your account has no email address")
    try:
        result = await template_editor.send_test(
            db,
            ctx.clinic,
            ctx.user.email,
            locale,
            subject=data.subject,
            body_html=data.body_html,
        )
    except template_editor.TemplateEditorError as exc:
        raise _invalid(exc) from exc
    if not result.is_success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The test email could not be sent. Check the email (SMTP) settings.",
        )
    return ApiResponse(data=EmailTemplateTestResponse(sent_to=ctx.user.email))
