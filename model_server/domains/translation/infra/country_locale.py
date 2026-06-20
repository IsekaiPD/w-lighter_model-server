from __future__ import annotations

from typing import Final

from .locale_utils import TARGET_COUNTRY_TO_LOCALE, TARGET_LOCALE_TO_COUNTRY

COUNTRY_TO_LOCALE: Final[dict[str, str]] = dict(TARGET_COUNTRY_TO_LOCALE)
LOCALE_TO_COUNTRY: Final[dict[str, str]] = dict(TARGET_LOCALE_TO_COUNTRY)


def resolve_locale_for_country(country: str) -> str | None:
    return COUNTRY_TO_LOCALE.get((country or "").strip())


def resolve_country_for_locale(locale: str) -> str | None:
    return LOCALE_TO_COUNTRY.get((locale or "").strip())
