"""Email service facade.

This service provides a unified interface for sending emails using
any configured provider. It handles template rendering and provider
selection.
"""

import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from jinja2 import (
    Environment,
    FileSystemLoader,
    TemplateError,
    TemplateSyntaxError,
    meta,
    pass_context,
    select_autoescape,
)
from jinja2.runtime import Context
from jinja2.sandbox import ImmutableSandboxedEnvironment
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email.providers.base import (
    EmailMessage,
    EmailProvider,
    EmailResult,
    EmailStatus,
)
from app.core.email.providers.console import ConsoleProvider
from app.core.email.providers.smtp import SMTPProvider
from app.core.pdf_locales import LOCALE_BY_LANG
from app.core.utils.currency import DEFAULT_CURRENCY, format_currency, money_locale

logger = logging.getLogger(__name__)

# Template directory path
TEMPLATES_DIR = Path(__file__).parent.parent.parent.parent / "templates" / "email"


@pass_context
def _money_filter(context: Context, amount: Any) -> str:
    """``{{ total | money }}`` — amount in the clinic currency from the context."""
    if amount is None or amount == "":
        return ""
    currency = context.get("currency") or DEFAULT_CURRENCY
    locale = money_locale(LOCALE_BY_LANG.get(context.get("locale") or "en"), currency)
    try:
        return format_currency(amount, currency, locale=locale)
    except (TypeError, ValueError, ArithmeticError):
        return str(amount)


def describe_template_error(exc: TemplateError) -> str:
    """Human-readable template error for the editor, with the line when known."""
    message = exc.message or exc.__class__.__name__
    if isinstance(exc, TemplateSyntaxError) and exc.lineno:
        return f"Line {exc.lineno}: {message}"
    return message


class EmailService:
    """Facade for sending emails through configured providers.

    This service:
    - Selects the appropriate provider based on configuration
    - Renders email templates using Jinja2
    - Provides a simple interface for sending templated emails
    """

    def __init__(self) -> None:
        """Initialize the email service."""
        self._provider: EmailProvider | None = None
        self._jinja_env: Environment | None = None
        # Clinic-written templates and subjects (editable from Settings) are
        # untrusted input: they only ever render in the sandbox, which blocks
        # access to Python internals.
        self._sandbox_html_env: ImmutableSandboxedEnvironment | None = None
        self._sandbox_text_env: ImmutableSandboxedEnvironment | None = None
        self._initialized = False

    def _initialize(self) -> None:
        """Lazy initialization of provider and template engine."""
        if self._initialized:
            return

        from app.config import settings

        # Initialize provider based on settings
        if settings.TESTING or not settings.EMAIL_ENABLED:
            self._provider = ConsoleProvider()
            logger.info("Email service using console provider (testing/disabled mode)")
        elif settings.EMAIL_PROVIDER == "console":
            self._provider = ConsoleProvider()
            logger.info("Email service using console provider")
        elif settings.EMAIL_PROVIDER == "smtp":
            self._provider = SMTPProvider(
                host=settings.EMAIL_SMTP_HOST,
                port=settings.EMAIL_SMTP_PORT,
                username=settings.EMAIL_SMTP_USER or None,
                password=settings.EMAIL_SMTP_PASSWORD or None,
                use_tls=settings.EMAIL_SMTP_TLS,
                default_from_email=settings.EMAIL_FROM_ADDRESS,
                default_from_name=settings.EMAIL_FROM_NAME,
            )
            logger.info(
                f"Email service using SMTP provider: {settings.EMAIL_SMTP_HOST}:{settings.EMAIL_SMTP_PORT}"
            )
        else:
            # Fallback to console if unknown provider
            self._provider = ConsoleProvider()
            logger.warning(
                f"Unknown email provider '{settings.EMAIL_PROVIDER}', falling back to console"
            )

        self._init_templates()
        self._initialized = True

    def _init_templates(self) -> None:
        """Build the Jinja2 environments (idempotent, no provider needed)."""
        if self._sandbox_text_env is not None:
            return

        self._sandbox_text_env = ImmutableSandboxedEnvironment(autoescape=False)
        self._sandbox_text_env.filters["money"] = _money_filter

        if TEMPLATES_DIR.exists():
            loader = FileSystemLoader(str(TEMPLATES_DIR))
            self._jinja_env = Environment(
                loader=loader,
                autoescape=select_autoescape(["html", "xml"]),
                trim_blocks=True,
                lstrip_blocks=True,
            )
            self._jinja_env.filters["money"] = _money_filter
            # Same loader so clinic templates can ``{% extends "base.html" %}``.
            self._sandbox_html_env = ImmutableSandboxedEnvironment(
                loader=loader,
                autoescape=True,
                trim_blocks=True,
                lstrip_blocks=True,
            )
            self._sandbox_html_env.filters["money"] = _money_filter
            logger.info(f"Email templates loaded from {TEMPLATES_DIR}")
        else:
            logger.warning(f"Email templates directory not found: {TEMPLATES_DIR}")

    def render_custom(self, source: str, context: dict, locale: str, *, html: bool = True) -> str:
        """Render clinic-written template source in the sandbox.

        Raises ``jinja2.TemplateError`` (syntax, unsafe access, missing
        parent template) so the editor can show the problem.
        """
        self._init_templates()
        env = self._sandbox_html_env if html else self._sandbox_text_env
        if env is None:
            raise TemplateError("Email templates are not available on this server")
        return env.from_string(source).render({"locale": locale, **context})

    def render_subject(self, subject: str, context: dict, locale: str = "en") -> str:
        """Render a subject line; falls back to the raw text on any template error."""
        if "{{" not in subject and "{%" not in subject:
            return subject
        try:
            rendered = self.render_custom(subject, context, locale, html=False)
        except TemplateError as e:
            logger.warning(f"Failed to render subject template: {e}")
            return subject
        return " ".join(rendered.split())

    def template_variables(self, source: str) -> set[str]:
        """Context names a template reads (for the editor's placeholder list)."""
        self._init_templates()
        env = self._sandbox_html_env or self._sandbox_text_env
        if env is None:
            return set()
        try:
            return meta.find_undeclared_variables(env.parse(source))
        except TemplateError:
            return set()

    def default_source(self, template_key: str, locale: str, extension: str = "html") -> str | None:
        """Source of the built-in template file for ``template_key``/``locale``."""
        self._init_templates()
        if self._jinja_env is None or self._jinja_env.loader is None:
            return None
        for template_path in (
            f"{locale}/{template_key}.{extension}",
            f"default/{template_key}.{extension}",
            f"{template_key}.{extension}",
        ):
            try:
                source, _, _ = self._jinja_env.loader.get_source(self._jinja_env, template_path)
            except TemplateError:
                continue
            return source
        return None

    @property
    def provider(self) -> EmailProvider:
        """Get the current email provider."""
        self._initialize()
        if self._provider is None:
            raise RuntimeError("Email service not properly initialized")
        return self._provider

    async def create_provider_for_clinic(
        self,
        db: AsyncSession,
        clinic_id: UUID,
    ) -> EmailProvider | None:
        """Create an email provider for a specific clinic.

        Reads the clinic's SMTP settings from the database and creates
        an appropriate provider. Falls back to global config if no
        clinic-specific settings are configured.

        Args:
            db: Database session.
            clinic_id: Clinic UUID.

        Returns:
            EmailProvider configured for the clinic, or None to use global.
        """
        from sqlalchemy import select

        from app.core.email.encryption import decrypt_password
        from app.modules.notifications.models import ClinicSmtpSettings

        # Get clinic SMTP settings
        result = await db.execute(
            select(ClinicSmtpSettings).where(ClinicSmtpSettings.clinic_id == clinic_id)
        )
        settings = result.scalar_one_or_none()

        if not settings or not settings.is_active:
            # No clinic-specific settings, use global
            return None

        if settings.provider == "disabled":
            # Email disabled for this clinic
            logger.info(f"Email disabled for clinic {clinic_id}")
            return None

        if settings.provider == "console":
            return ConsoleProvider()

        if settings.provider == "smtp" and settings.host:
            # Decrypt password if set
            password = None
            if settings.password_encrypted:
                password = decrypt_password(settings.password_encrypted)

            return SMTPProvider(
                host=settings.host,
                port=settings.port,
                username=settings.username,
                password=password,
                use_tls=settings.use_tls,
                use_ssl=settings.use_ssl,
                # Most providers (Zoho, Gmail, M365) refuse to relay for a
                # sender the login doesn't own, so the login is the safe
                # fallback when no From address is configured.
                default_from_email=settings.from_email or settings.username or "",
                default_from_name=settings.from_name or "DentalPin",
            )

        # Fallback to global
        return None

    async def send(
        self,
        message: EmailMessage,
        db: AsyncSession | None = None,
        clinic_id: UUID | None = None,
    ) -> EmailResult:
        """Send an email message.

        Args:
            message: The email message to send.
            db: Database session (required for clinic-specific config).
            clinic_id: Clinic UUID for per-clinic SMTP settings.

        Returns:
            EmailResult with the status of the operation.
        """
        self._initialize()

        # Try to get clinic-specific provider
        provider = self.provider  # Default to global
        clinic_provider = None
        if db and clinic_id:
            clinic_provider = await self.create_provider_for_clinic(db, clinic_id)
            if clinic_provider:
                provider = clinic_provider
                logger.info(f"Using clinic-specific email provider for clinic {clinic_id}")

        # The global sender only belongs to the global provider. A clinic's
        # own SMTP sends from its configured address (the provider's
        # default); stamping the global one here made Zoho reject the relay.
        if not message.from_email and clinic_provider is None:
            from app.config import settings

            message.from_email = settings.EMAIL_FROM_ADDRESS
            message.from_name = message.from_name or settings.EMAIL_FROM_NAME

        return await provider.send(message)

    async def send_templated(
        self,
        to_email: str,
        template_key: str,
        context: dict,
        subject: str,
        locale: str = "en",
        to_name: str | None = None,
        from_email: str | None = None,
        from_name: str | None = None,
        reply_to: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        template_html: str | None = None,
        template_text: str | None = None,
        db: AsyncSession | None = None,
        clinic_id: UUID | None = None,
    ) -> EmailResult:
        """Send an email using a template.

        This method renders a Jinja2 template with the provided context
        and sends the resulting email.

        Args:
            to_email: Recipient email address.
            template_key: Template identifier (e.g., 'appointment_confirmation').
            context: Template context variables.
            subject: Email subject (can include template variables).
            locale: Language code for template selection (default 'en').
            to_name: Recipient name (optional).
            from_email: Sender email (optional, uses default).
            from_name: Sender name (optional, uses default).
            reply_to: Reply-to address (optional).
            cc: CC recipients (optional).
            bcc: BCC recipients (optional).
            template_html: Custom HTML template content (overrides file template).
            template_text: Custom text template content (overrides file template).
            db: Database session (required for clinic-specific config).
            clinic_id: Clinic UUID for per-clinic SMTP settings.

        Returns:
            EmailResult with the status of the operation.
        """
        self._initialize()

        # Render HTML template
        body_html = self._render_template(
            template_key=template_key,
            locale=locale,
            context=context,
            extension="html",
            custom_template=template_html,
        )

        if not body_html:
            logger.error(f"Failed to render HTML template: {template_key}")
            return EmailResult(
                status=EmailStatus.FAILED,
                provider=self.provider.name,
                error_message=f"Template not found: {template_key}",
            )

        # Render text template (optional)
        body_text = self._render_template(
            template_key=template_key,
            locale=locale,
            context=context,
            extension="txt",
            custom_template=template_text,
        )

        rendered_subject = self.render_subject(subject, context, locale)

        message = EmailMessage(
            to_email=to_email,
            to_name=to_name,
            subject=rendered_subject,
            body_html=body_html,
            body_text=body_text,
            from_email=from_email,
            from_name=from_name,
            reply_to=reply_to,
            cc=cc or [],
            bcc=bcc or [],
        )

        return await self.send(message, db=db, clinic_id=clinic_id)

    def _render_template(
        self,
        template_key: str,
        locale: str,
        context: dict,
        extension: str = "html",
        custom_template: str | None = None,
    ) -> str | None:
        """Render a Jinja2 template.

        Args:
            template_key: Template identifier.
            locale: Language code.
            context: Template context.
            extension: File extension (html or txt).
            custom_template: Custom template string (overrides file).

        Returns:
            Rendered template string, or None if template not found.
        """
        # A broken clinic template must not stop the email: fall back to the
        # built-in file for the same key.
        if custom_template:
            try:
                return self.render_custom(
                    custom_template, context, locale, html=extension == "html"
                )
            except Exception as e:
                logger.error(f"Custom {template_key}.{extension} failed, using the default: {e}")

        if not self._jinja_env:
            logger.warning("Jinja2 environment not initialized")
            return None

        # Try locale-specific template first, then fallback to default
        template_paths = [
            f"{locale}/{template_key}.{extension}",
            f"default/{template_key}.{extension}",
            f"{template_key}.{extension}",
        ]

        for template_path in template_paths:
            try:
                template = self._jinja_env.get_template(template_path)
                # base.html reads ``locale`` for ``lang``/``dir``.
                return template.render({"locale": locale, **context})
            except Exception:
                continue

        # Plain-text bodies are optional (no .txt templates ship today), so
        # only a missing HTML template is worth a warning.
        log = logger.warning if extension == "html" else logger.debug
        log(f"Template not found: {template_key}.{extension} for locale {locale}")
        return None

    async def health_check(self) -> bool:
        """Check if the email service is healthy.

        Returns:
            True if the service can send emails, False otherwise.
        """
        self._initialize()
        return await self.provider.health_check()

    def get_provider_name(self) -> str:
        """Get the name of the current provider.

        Returns:
            Provider name string.
        """
        self._initialize()
        return self.provider.name


# Global singleton instance
email_service = EmailService()
