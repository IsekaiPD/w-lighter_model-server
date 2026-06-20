from __future__ import annotations

from typing import Any


TARGET_COUNTRY_TO_LOCALE: dict[str, str] = {
    "US": "ko_en_us",
    "CN": "ko_zh_cn",
    "JP": "ko_ja",
    "TH": "ko_th_th",
}

TARGET_LOCALE_TO_COUNTRY: dict[str, str] = {locale: country for country, locale in TARGET_COUNTRY_TO_LOCALE.items()}

LEGACY_COUNTRY_ALIASES: dict[str, str] = {
    "us": "US",
    "usa": "US",
    "미국": "US",
    "cn": "CN",
    "china": "CN",
    "중국": "CN",
    "jp": "JP",
    "japan": "JP",
    "일본": "JP",
    "th": "TH",
    "thailand": "TH",
    "태국": "TH",
}


class LocaleNormalizationError(ValueError):
    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        self.message = message
        super().__init__(message)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def normalize_target_country(value: str | None) -> str | None:
    raw = _clean(value)
    if not raw:
        return None
    country = raw.upper()
    if country in TARGET_COUNTRY_TO_LOCALE:
        return country
    alias = LEGACY_COUNTRY_ALIASES.get(raw) or LEGACY_COUNTRY_ALIASES.get(raw.lower())
    if alias:
        return alias
    raise LocaleNormalizationError("invalid_target_country", f"Unsupported targetCountry: {value}")


def normalize_target_locale(value: str | None) -> str | None:
    raw = _clean(value)
    if not raw:
        return None
    locale = raw.lower()
    if locale in TARGET_LOCALE_TO_COUNTRY:
        return locale
    raise LocaleNormalizationError("invalid_target_locale", f"Unsupported targetLocale: {value}")


def country_to_locale(country: str) -> str:
    normalized_country = normalize_target_country(country)
    if normalized_country is None:
        raise LocaleNormalizationError("invalid_target_country", "targetCountry is required.")
    return TARGET_COUNTRY_TO_LOCALE[normalized_country]


def locale_to_country(locale: str) -> str:
    normalized_locale = normalize_target_locale(locale)
    if normalized_locale is None:
        raise LocaleNormalizationError("invalid_target_locale", "targetLocale is required.")
    return TARGET_LOCALE_TO_COUNTRY[normalized_locale]


def normalize_target_fields(payload: dict[str, Any] | None) -> dict[str, str]:
    data = payload if isinstance(payload, dict) else {}
    country_raw = data.get("targetCountry")
    if country_raw is None:
        country_raw = data.get("target_country")
    locale_raw = data.get("targetLocale")
    if locale_raw is None:
        locale_raw = data.get("target_locale")

    country = normalize_target_country(country_raw) if country_raw is not None else None
    locale = normalize_target_locale(locale_raw) if locale_raw is not None else None

    if country is not None and locale is not None:
        expected_locale = TARGET_COUNTRY_TO_LOCALE[country]
        expected_country = TARGET_LOCALE_TO_COUNTRY[locale]
        if expected_locale != locale or expected_country != country:
            raise LocaleNormalizationError(
                "target_country_locale_mismatch",
                f"targetCountry {country!r} does not match targetLocale {locale!r}.",
            )
    elif country is not None:
        locale = country_to_locale(country)
    elif locale is not None:
        country = locale_to_country(locale)
    else:
        raise LocaleNormalizationError("missing_target_locale", "targetLocale or targetCountry is required.")

    assert country is not None
    assert locale is not None
    return {
        "targetCountry": country,
        "target_country": country,
        "targetLocale": locale,
        "target_locale": locale,
    }
