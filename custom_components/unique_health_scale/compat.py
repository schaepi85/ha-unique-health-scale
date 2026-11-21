"""Welche Waagen getestet sind, und Hinweise (Reparaturen) fuer alle anderen.

Die Unique-Health-App bedient viele Lefu-Waagen. Sie unterscheiden sich im
Funkprotokoll, in der Zahl der Elektroden und in den Kalibrierfaktoren der
Koerperwert-Berechnung. Getestet ist diese Integration nur mit den Modellen
in TESTED_MODELS. Bei allen anderen gilt:

* Gewicht, Herzfrequenz und Impedanzen werden angezeigt, sofern das
  Protokoll passt (Pruefsumme und Plausibilitaet sichern das ab).
* Koerperwerte werden nur berechnet, wenn das in den Einstellungen
  ausdruecklich eingeschaltet ist, weil die Kalibrierung abweichen kann.
* Passt das Protokoll erkennbar nicht, meldet die Integration das unter
  Einstellungen -> Reparaturen, statt falsche Werte zu liefern.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Bluetooth-Namen getesteter Waagen (klein geschrieben)
TESTED_MODELS = {
    "smart scale p1": "PAVABA 8-Elektroden-Waage mit Griff (Lefu CF597)",
}

COMPAT_URL = "https://github.com/schaepi85/ha-unique-health-scale#kompatibilität"
REPORT_URL = (
    "https://github.com/schaepi85/ha-unique-health-scale/issues/new?template=testbericht.yml"
)

# Gruende, aus denen das Protokoll erkennbar nicht passt (Schluessel der Uebersetzung)
REASON_FOUR_ELECTRODE = "four_electrode"
REASON_UNKNOWN_ADVERTISING = "unknown_advertising"
REASON_UNKNOWN_FRAMES = "unknown_frames"
REASON_NO_NOTIFY = "no_notify"

# So viele Messungen hintereinander ohne Impedanzen, bevor ein Hinweis erscheint
NO_IMPEDANCE_LIMIT = 3
# So viele unbekannte Advertising-Pakete ohne ein einziges gueltiges
UNKNOWN_ADVERTISING_LIMIT = 10


def is_tested(model: str | None) -> bool:
    """True, wenn das Modell (Bluetooth-Name) getestet ist."""
    return (model or "").strip().casefold() in TESTED_MODELS


def _issue_id(kind: str, entry_id: str) -> str:
    return f"{kind}_{entry_id}"


def async_report_untested(hass: HomeAssistant, entry_id: str, model: str) -> None:
    """Hinweis: Modell ungetestet, Koerperwerte nur auf Wunsch."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id("untested_model", entry_id),
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="untested_model",
        translation_placeholders={"model": model, "url": REPORT_URL},
        learn_more_url=COMPAT_URL,
    )


def async_clear_untested(hass: HomeAssistant, entry_id: str) -> None:
    ir.async_delete_issue(hass, DOMAIN, _issue_id("untested_model", entry_id))


def async_report_unsupported(
    hass: HomeAssistant, entry_id: str, model: str, reason: str
) -> None:
    """Hinweis: Das Protokoll dieser Waage passt nicht."""
    _LOGGER.warning(
        "Waage %s sendet in einem Format, das diese Integration nicht kennt (%s)."
        " Bitte einen Testbericht anlegen: %s",
        model,
        reason,
        REPORT_URL,
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id("unsupported_protocol", entry_id),
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=f"unsupported_{reason}",
        translation_placeholders={"model": model, "url": REPORT_URL},
        learn_more_url=COMPAT_URL,
    )


def async_report_no_impedance(hass: HomeAssistant, entry_id: str, model: str) -> None:
    """Hinweis: Mehrere Messungen ohne Impedanzen."""
    _LOGGER.warning(
        "Waage %s: %d Messungen hintereinander ohne Impedanzen, keine Koerperwerte",
        model,
        NO_IMPEDANCE_LIMIT,
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id("no_impedance", entry_id),
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="no_impedance",
        translation_placeholders={"model": model, "count": str(NO_IMPEDANCE_LIMIT)},
        learn_more_url=COMPAT_URL,
    )


def async_clear_no_impedance(hass: HomeAssistant, entry_id: str) -> None:
    ir.async_delete_issue(hass, DOMAIN, _issue_id("no_impedance", entry_id))


def async_clear_all(hass: HomeAssistant, entry_id: str) -> None:
    """Alle Hinweise einer Waage entfernen (beim Loeschen der Integration)."""
    for kind in ("untested_model", "unsupported_protocol", "no_impedance"):
        ir.async_delete_issue(hass, DOMAIN, _issue_id(kind, entry_id))
