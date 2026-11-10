"""Locale-aware currency formatting.

Single helper used by every server-rendered surface (PDFs, emails,
report exports) so the format is consistent and never reinvents
symbols, separators, or decimal places. Wraps ``babel.numbers`` —
the standard for ICU-quality formatting in Python.
"""

from decimal import Decimal

from babel.numbers import format_currency as _babel_format_currency

DEFAULT_CURRENCY = "INR"
DEFAULT_MONEY_LOCALE = "en_IN"


def money_locale(lang_locale: str | None, currency: str | None) -> str:
    """Pick the Babel locale for rendering amounts.

    Rupee amounts always use Indian digit grouping (1,64,000.00),
    whatever the viewer's UI language.
    """
    if (currency or DEFAULT_CURRENCY) == "INR" or not lang_locale:
        return DEFAULT_MONEY_LOCALE
    return lang_locale


def format_currency(
    amount: Decimal | float | int,
    currency: str | None = DEFAULT_CURRENCY,
    locale: str = DEFAULT_MONEY_LOCALE,
) -> str:
    """Render ``amount`` as a localized currency string.

    ``locale`` accepts both BCP 47 (``en-US``) and POSIX (``en_US``);
    babel only accepts the latter, so we normalize.
    """
    return _babel_format_currency(
        amount, currency or DEFAULT_CURRENCY, locale=locale.replace("-", "_")
    )
