"""Orchestrator bridge — wires a conversation to the core engine.

Builds the :class:`AgentContext` (permissions = the caller's own, a
guardrail config that defers writes to inline confirmation, audit linked
to the core agent session), reconstructs the message history, drives
``run_turn``, persists the new messages, and yields ``TurnEvent``s that
the router frames as SSE. Provider is injectable for tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.agents.context import AgentContext, AgentMode
from app.core.agents.guardrails import GuardrailConfig
from app.core.agents.orchestrator import ConfirmationRequired, ToolCallFinished, TurnUsage, run_turn
from app.core.agents.redaction import Redactor
from app.core.agents.tools.registry import tool_registry
from app.core.auth.permissions import permission_matches
from app.core.llm.base import ProviderMessage, Role, TextBlock, ToolResultBlock, ToolUseBlock
from app.core.llm.factory import get_provider, get_provider_spec

from .models import CopilotConversation, CopilotSettings
from .serde import message_from_row
from .service import ClinicBudgetGuard, ConversationService

_BASE_PROMPT = (
    "You are the DentalPin copilot, the assistant of a dental clinic. "
    "Answer concisely and precisely. Use the available tools to look up and "
    "act on the clinic's data; never invent information that did not come "
    "from a tool. For actions that change data (create, book, cancel) call "
    "the matching tool: the system asks the user for confirmation before "
    "running it. Never assume permissions you do not have. "
    "Invoiced and collected amounts are separate accounting axes: NEVER "
    "calculate, subtract or show the difference between them (debt, "
    "outstanding, arrears). Report each axis separately when asked."
)

# Multi-step recipes the model chains with its own tool calls. The tool
# list is already filtered per-user (RBAC) and per-redaction; if a step's
# tool is missing, the model skips it and says so.
_PLAYBOOKS = (
    "\n\nCommon playbooks (chain the tools yourself; if a tool for a step "
    "is missing, say so and continue with the rest):\n"
    "- Daily briefing: get_day_overview(today) → list_due_recalls(overdue=true) → "
    "list_budgets(status=['sent']). Summarise in three blocks: appointments, "
    "pending calls, budgets awaiting a reply.\n"
    "- Prepare a patient's visit: get_patient → their appointment (get_appointment "
    "or get_day_overview) → list_due_recalls(patient_id) → "
    "list_budgets(patient_id, status=['sent','accepted']) → "
    "patient_payment_history. Return a one-screen summary. There are no "
    "clinical tools (odontogram, medical history): say so if asked.\n"
    "- Fill a cancellation gap: after cancel_appointment (or when the user "
    "mentions a gap) → list_due_recalls(overdue=true), prioritise "
    "priority=high → propose 2-3 candidates with their phone → if the user "
    "picks one and confirms: book_appointment → log_contact_attempt("
    "outcome='scheduled', linked_appointment_id=the created appointment)."
)

_LANGUAGE_NAMES = {
    "es": "Spanish",
    "en": "English",
    "fr": "French",
    "pt": "Portuguese",
    "ta": "Tamil",
    "te": "Telugu",
    "de": "German",
    "hu": "Hungarian",
    "it": "Italian",
    "pl": "Polish",
    "ar": "Arabic",
}


def _time_rule(timezone: str, now: datetime | None) -> str:
    try:
        tz = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return ""
    local = (now or datetime.now(UTC)).astimezone(tz)
    return (
        f"\n\nThe clinic's time zone is {timezone}; it is now "
        f"{local:%A %d %B %Y, %H:%M} there. Tool results give timestamps in UTC "
        "(ending in +00:00 or Z): always convert them to the clinic's time zone "
        "before showing them, and read 'today' and 'tomorrow' in clinic time."
    )


def build_system_prompt(
    locale: str, timezone: str | None = None, now: datetime | None = None
) -> str:
    """System prompt that pins the reply language and clock to the clinic.

    Tool descriptions and tool payloads may be in another language (several
    modules describe their tools in Spanish); the explicit rule keeps that
    from leaking into the reply. Tool timestamps are UTC, so without the
    clinic's zone the model reports appointment times hours off.
    """
    language = _LANGUAGE_NAMES.get(locale, _LANGUAGE_NAMES["en"])
    return (
        _BASE_PROMPT + f"\n\nAlways reply in {language}, the clinic's working language, unless the "
        "user writes to you in another language — then reply in the user's "
        "language. Tool descriptions and tool results may be written in a "
        "different language; never let that change the language of your reply, "
        "and translate any status or label you quote from them."
        + (_time_rule(timezone, now) if timezone else "")
        + _PLAYBOOKS
    )


SYSTEM_PROMPT = build_system_prompt(settings.CONTENT_LOCALE)


async def _clinic_row(db: AsyncSession, clinic_id: UUID):
    return (
        await db.execute(
            text("SELECT settings, timezone FROM clinics WHERE id = :id"), {"id": clinic_id}
        )
    ).first()


def _locale_of(row) -> str:
    # Same lookup as notifications.resolve_clinic_communication_locale,
    # inlined to keep copilot's depends = [] (notifications is a module).
    clinic_settings = (row.settings or {}) if row else {}
    lang = (
        clinic_settings.get("communication_language") if isinstance(clinic_settings, dict) else None
    )
    return lang or settings.CONTENT_LOCALE


async def clinic_locale(db: AsyncSession, clinic_id: UUID) -> str:
    return _locale_of(await _clinic_row(db, clinic_id))


async def clinic_system_prompt(db: AsyncSession, clinic_id: UUID) -> str:
    row = await _clinic_row(db, clinic_id)
    return build_system_prompt(_locale_of(row), row.timezone if row else None)


# Copilot gates writes via inline confirmation (a turn-level pause), so
# the approval-queue triggers are disabled. Rate limits + denylist stay.
COPILOT_GUARDRAILS = GuardrailConfig(
    require_approval_for=[],
    auto_require_approval_for_destructive=False,
    blocked_tools=[],
)


def _tool_names_for(permissions: list[str], *, include_free_text: bool = True) -> list[str]:
    """Registry tools the caller is allowed to use (AND of permissions).

    With ``include_free_text=False`` (redaction on), tools flagged
    ``exposes_free_text`` are excluded — their prose results can't be
    tokenized, so they never reach the cloud provider.
    """
    out: list[str] = []
    for name in tool_registry.list():
        tool = tool_registry.get(name)
        if tool is None:
            continue
        if not include_free_text and tool.exposes_free_text:
            continue
        if all(
            any(permission_matches(req, granted) for granted in permissions)
            for req in tool.permissions
        ):
            out.append(name)
    return out


def _build_context(
    *,
    db: AsyncSession,
    clinic_id: UUID,
    permissions: list[str],
    user_id: UUID,
    agent_id: UUID,
    session_id: UUID,
) -> AgentContext:
    return AgentContext(
        agent_id=agent_id,
        session_id=session_id,
        clinic_id=clinic_id,
        mode=AgentMode.AUTONOMOUS,  # writes gated by inline confirm, not the queue
        permissions=permissions,
        tools=tool_registry,
        db=db,
        supervisor_id=user_id,
        guardrail_config=COPILOT_GUARDRAILS,
    )


def _dialect_for(provider_name: str) -> str:
    """Tool-schema dialect for the conversation's provider."""
    return get_provider_spec(provider_name).tool_dialect


def _redactor_for(conv: CopilotConversation, settings_row: CopilotSettings) -> Redactor:
    r = Redactor(enabled=settings_row.redaction_enabled)
    r.seed(conv.context)
    return r


async def _history(db: AsyncSession, conv: CopilotConversation) -> list[ProviderMessage]:
    rows = await ConversationService.list_messages(db, conv.id)
    return [message_from_row(m.role, m.content) for m in rows]


async def _persist_tail(
    db: AsyncSession, conv: CopilotConversation, history: list[ProviderMessage], start: int
) -> None:
    for msg in history[start:]:
        await ConversationService.append_message(db, conv, role=msg.role.value, blocks=msg.content)


async def drive_turn(
    *,
    db: AsyncSession,
    conv: CopilotConversation,
    settings_row: CopilotSettings,
    permissions: list[str],
    user_id: UUID,
    agent_id: UUID,
    session_id: UUID,
    user_text: str,
    provider=None,
) -> AsyncIterator:
    """Append the user message, run one turn, persist + yield events."""
    history = await _history(db, conv)
    user_msg = ProviderMessage(Role.USER, [TextBlock(user_text)])
    await ConversationService.append_message(db, conv, role="user", blocks=user_msg.content)
    history.append(user_msg)

    provider = provider or get_provider(conv.provider)
    redactor = _redactor_for(conv, settings_row)
    budget = ClinicBudgetGuard(settings_row, conv)
    ctx = _build_context(
        db=db,
        clinic_id=conv.clinic_id,
        permissions=permissions,
        user_id=user_id,
        agent_id=agent_id,
        session_id=session_id,
    )

    system = await clinic_system_prompt(db, conv.clinic_id)
    start = len(history)
    async for ev in run_turn(
        ctx=ctx,
        provider=provider,
        system=system,
        history=history,
        tool_names=_tool_names_for(permissions, include_free_text=not redactor.enabled),
        redactor=redactor,
        model=conv.model,
        max_tokens=4096,
        budget=budget,
        dialect=_dialect_for(conv.provider),
    ):
        yield ev
    await _persist_tail(db, conv, history, start)


async def resume_turn(
    *,
    db: AsyncSession,
    conv: CopilotConversation,
    settings_row: CopilotSettings,
    permissions: list[str],
    user_id: UUID,
    agent_id: UUID,
    session_id: UUID,
    call_id: str,
    approve: bool,
    provider=None,
) -> AsyncIterator:
    """Execute (or skip) the pending tool, then resume the turn."""
    history = await _history(db, conv)
    pending = _find_pending(history, call_id)
    if pending is None:
        return

    provider = provider or get_provider(conv.provider)
    redactor = _redactor_for(conv, settings_row)
    budget = ClinicBudgetGuard(settings_row, conv)
    ctx = _build_context(
        db=db,
        clinic_id=conv.clinic_id,
        permissions=permissions,
        user_id=user_id,
        agent_id=agent_id,
        session_id=session_id,
    )

    if approve:
        res = await ctx.tools.call(ctx, pending.name, pending.input)
        payload = res.data if res.ok else {"error": res.error}
        is_error = not res.ok
        yield ToolCallFinished(call_id, pending.name, res.ok, payload)
    else:
        payload = {"status": "cancelled_by_user"}
        is_error = False

    tool_msg = ProviderMessage(Role.TOOL, [ToolResultBlock(call_id, payload, is_error)])
    history.append(tool_msg)
    await ConversationService.append_message(db, conv, role="tool", blocks=tool_msg.content)

    system = await clinic_system_prompt(db, conv.clinic_id)
    start = len(history)
    async for ev in run_turn(
        ctx=ctx,
        provider=provider,
        system=system,
        history=history,
        tool_names=_tool_names_for(permissions, include_free_text=not redactor.enabled),
        redactor=redactor,
        model=conv.model,
        max_tokens=4096,
        budget=budget,
        dialect=_dialect_for(conv.provider),
    ):
        yield ev
    await _persist_tail(db, conv, history, start)


def _find_pending(history: list[ProviderMessage], call_id: str) -> ToolUseBlock | None:
    for msg in reversed(history):
        if msg.role is Role.ASSISTANT:
            for block in msg.content:
                if isinstance(block, ToolUseBlock) and block.id == call_id:
                    return block
    return None


__all__ = ["drive_turn", "resume_turn", "ConfirmationRequired", "TurnUsage"]
