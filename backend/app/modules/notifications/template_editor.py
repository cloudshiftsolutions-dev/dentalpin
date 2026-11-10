"""Clinic email template editor: read, preview, save and reset overrides.

A clinic override is a ``NotificationTemplate`` row (channel ``email``)
for one notification type and language. The gateway prefers it over the
built-in file at send time; deleting it restores the default. Clinic
HTML is untrusted and only ever renders in the email service sandbox.
"""

from __future__ import annotations

from uuid import UUID

from jinja2 import TemplateError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.core.email.providers.base import EmailMessage, EmailResult
from app.core.email.service import describe_template_error, email_service

from .email_defaults import (
    COMMON_FIELDS,
    EDITABLE_EMAIL_TYPES,
    MONEY_FIELDS,
    default_subject,
    sample_context,
)
from .models import NotificationTemplate
from .schemas import (
    EmailTemplateEditorDetail,
    EmailTemplateEditorSummary,
    EmailTemplatePreviewResponse,
    EmailTemplateVariable,
)

_LAYOUT_FIELDS = frozenset({"locale", "subject", "footer_sent_by", "sent_by_label", "currency"})

_LOOP_SNIPPETS = {
    "treatments": "{% for t in treatments %}{{ t.name }} – {{ t.price | money }}\n{% endfor %}",
    "items": "{% for item in items %}{{ item.description }} – {{ item.line_total | money }}\n"
    "{% endfor %}",
}


class TemplateEditorError(ValueError):
    """Template source that cannot be saved or previewed (message is user-facing)."""


def is_editable(template_key: str) -> bool:
    return template_key in EDITABLE_EMAIL_TYPES


def _snippet(name: str) -> str:
    if name in _LOOP_SNIPPETS:
        return _LOOP_SNIPPETS[name]
    if name in MONEY_FIELDS:
        return f"{{{{ {name} | money }}}}"
    return f"{{{{ {name} }}}}"


def _variables(default_body: str) -> list[EmailTemplateVariable]:
    found = email_service.template_variables(default_body) - _LAYOUT_FIELDS
    names = [*COMMON_FIELDS, *sorted(found - set(COMMON_FIELDS))]
    return [EmailTemplateVariable(name=n, snippet=_snippet(n)) for n in names]


async def _override(
    db: AsyncSession, clinic_id: UUID, template_key: str, locale: str
) -> NotificationTemplate | None:
    return await db.scalar(
        select(NotificationTemplate).where(
            NotificationTemplate.clinic_id == clinic_id,
            NotificationTemplate.template_key == template_key,
            NotificationTemplate.locale == locale,
            NotificationTemplate.channel == "email",
        )
    )


async def list_summaries(db: AsyncSession, clinic_id: UUID) -> list[EmailTemplateEditorSummary]:
    rows = (
        await db.scalars(
            select(NotificationTemplate).where(
                NotificationTemplate.clinic_id == clinic_id,
                NotificationTemplate.channel == "email",
                NotificationTemplate.template_key.in_(EDITABLE_EMAIL_TYPES),
            )
        )
    ).all()
    return [
        EmailTemplateEditorSummary(
            template_key=key,
            default_subject=default_subject(key) or "",
            customized_locales=sorted(
                r.locale for r in rows if r.template_key == key and r.is_active
            ),
            disabled_locales=sorted(
                r.locale for r in rows if r.template_key == key and not r.is_active
            ),
        )
        for key in EDITABLE_EMAIL_TYPES
    ]


async def get_detail(
    db: AsyncSession, clinic_id: UUID, template_key: str, locale: str
) -> EmailTemplateEditorDetail:
    override = await _override(db, clinic_id, template_key, locale)
    default_body = email_service.default_source(template_key, locale) or ""
    default_subj = default_subject(template_key) or ""
    return EmailTemplateEditorDetail(
        template_key=template_key,
        locale=locale,
        is_custom=override is not None,
        is_active=override.is_active if override else True,
        subject=(override.subject if override and override.subject else default_subj),
        body_html=(override.body_html if override and override.body_html else default_body),
        default_subject=default_subj,
        default_body_html=default_body,
        variables=_variables(default_body),
        updated_at=override.updated_at if override else None,
    )


def render_preview(
    clinic: Clinic | None, locale: str, subject: str, body_html: str
) -> EmailTemplatePreviewResponse:
    """Render a draft with sample data; raises ``TemplateEditorError``."""
    context = sample_context(clinic)
    try:
        html = email_service.render_custom(body_html, context, locale)
        rendered_subject = email_service.render_custom(subject, context, locale, html=False)
    except TemplateError as exc:
        raise TemplateEditorError(describe_template_error(exc)) from exc
    return EmailTemplatePreviewResponse(subject=" ".join(rendered_subject.split()), html=html)


async def save_override(
    db: AsyncSession,
    clinic: Clinic,
    template_key: str,
    locale: str,
    *,
    subject: str,
    body_html: str,
    is_active: bool,
) -> EmailTemplateEditorDetail:
    # A template that cannot render must never reach patients.
    render_preview(clinic, locale, subject, body_html)

    override = await _override(db, clinic.id, template_key, locale)
    if override is None:
        override = NotificationTemplate(
            clinic_id=clinic.id,
            channel="email",
            template_key=template_key,
            locale=locale,
            is_system=False,
            description="Edited in Settings",
        )
        db.add(override)
    override.subject = subject
    override.body_html = body_html
    override.is_active = is_active
    await db.commit()
    return await get_detail(db, clinic.id, template_key, locale)


async def reset_override(
    db: AsyncSession, clinic_id: UUID, template_key: str, locale: str
) -> EmailTemplateEditorDetail:
    override = await _override(db, clinic_id, template_key, locale)
    if override is not None:
        await db.delete(override)
        await db.commit()
    return await get_detail(db, clinic_id, template_key, locale)


async def send_test(
    db: AsyncSession,
    clinic: Clinic,
    to_email: str,
    locale: str,
    *,
    subject: str,
    body_html: str,
) -> EmailResult:
    preview = render_preview(clinic, locale, subject, body_html)
    return await email_service.send(
        EmailMessage(
            to_email=to_email,
            subject=f"[Test] {preview.subject}",
            body_html=preview.html,
        ),
        db=db,
        clinic_id=clinic.id,
    )
