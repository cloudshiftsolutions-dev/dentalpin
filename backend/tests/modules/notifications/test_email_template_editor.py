"""Email template editor: sandboxing, previews, default subjects (no DB)."""

from types import SimpleNamespace

import pytest

from app.core.email.service import email_service
from app.modules.notifications import template_editor
from app.modules.notifications.email_defaults import (
    DEFAULT_SUBJECTS,
    EDITABLE_EMAIL_TYPES,
    default_subject,
    sample_context,
)

CLINIC = SimpleNamespace(
    name="Aruna Dental Hospital",
    phone="+91 44 1234 5678",
    address={"street": "12 MG Road", "city": "Chennai", "postal_code": "600001", "country": "IN"},
    currency="INR",
)


def test_every_editable_type_has_a_subject_and_a_built_in_email() -> None:
    assert set(DEFAULT_SUBJECTS) == set(EDITABLE_EMAIL_TYPES)
    for key in EDITABLE_EMAIL_TYPES:
        assert email_service.default_source(key, "en"), key


@pytest.mark.parametrize("key", EDITABLE_EMAIL_TYPES)
def test_built_in_email_previews_with_sample_data(key: str) -> None:
    source = email_service.default_source(key, "en")
    preview = template_editor.render_preview(CLINIC, "en", default_subject(key), source)
    assert "Priya Raman" in preview.html or key == "budget_accepted"
    assert "{{" not in preview.subject
    assert "€" not in preview.html


def test_preview_formats_money_and_readable_clinic_address() -> None:
    source = email_service.default_source("invoice_sent", "en")
    preview = template_editor.render_preview(CLINIC, "en", default_subject("invoice_sent"), source)
    assert preview.subject == "Invoice FAC-2026-0010 from Aruna Dental Hospital"
    assert "₹15,000.00" in preview.html
    assert "12 MG Road, Chennai, 600001" in preview.html
    assert "{'street'" not in preview.html


@pytest.mark.parametrize(
    "source",
    [
        "{{ ''.__class__.__mro__ }}",
        "{{ patient_name.__class__.__init__.__globals__ }}",
        "{% for c in ().__class__.__base__.__subclasses__() %}{{ c }}{% endfor %}",
    ],
)
def test_sandbox_blocks_access_to_python_internals(source: str) -> None:
    with pytest.raises(template_editor.TemplateEditorError):
        template_editor.render_preview(CLINIC, "en", "Subject", source)


def test_syntax_error_reports_the_line() -> None:
    with pytest.raises(template_editor.TemplateEditorError, match=r"^Line 2: "):
        template_editor.render_preview(CLINIC, "en", "Subject", "<p>\n{{ patient_name }\n</p>")


def test_unknown_parent_template_is_reported() -> None:
    with pytest.raises(template_editor.TemplateEditorError):
        template_editor.render_preview(CLINIC, "en", "S", '{% extends "../../app/config.py" %}')


def test_custom_template_can_extend_the_branded_layout() -> None:
    body = '{% extends "base.html" %}{% block content %}<p>Hi {{ patient_name }}</p>{% endblock %}'
    preview = template_editor.render_preview(CLINIC, "en", "Hello {{ patient_name }}", body)
    assert "<p>Hi Priya Raman</p>" in preview.html
    assert "Aruna Dental Hospital" in preview.html
    assert preview.subject == "Hello Priya Raman"


def test_subject_is_not_html_escaped() -> None:
    out = email_service.render_subject(
        "Invoice for {{ patient_name }}", {"patient_name": "O'Brien & Co"}
    )
    assert out == "Invoice for O'Brien & Co"


def test_html_body_escapes_patient_data() -> None:
    preview = template_editor.render_preview(
        SimpleNamespace(**{**vars(CLINIC), "name": "<script>x</script>"}),
        "en",
        "S",
        "<p>{{ clinic_name }}</p>",
    )
    assert "<script>" not in preview.html


def test_broken_custom_template_falls_back_to_built_in_email() -> None:
    html = email_service._render_template(
        template_key="welcome",
        locale="en",
        context=sample_context(CLINIC),
        custom_template="{{ ''.__class__.__mro__ }}",
    )
    assert html and "Priya Raman" in html


def test_editor_variables_offer_money_and_loop_snippets() -> None:
    source = email_service.default_source("invoice_sent", "en")
    snippets = {v.name: v.snippet for v in template_editor._variables(source)}
    assert snippets["total"] == "{{ total | money }}"
    assert snippets["items"].startswith("{% for item in items %}")
    assert snippets["patient_name"] == "{{ patient_name }}"
    assert "locale" not in snippets
