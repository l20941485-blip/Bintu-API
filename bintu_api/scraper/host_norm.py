"""Host and IDN normalization helpers, including emoji and symbol labels."""

from __future__ import annotations

import re
import unicodedata

import idna

_ASCII_LABEL_RE = re.compile(r"^[a-z0-9-]+$")


def normalize_idn_host(host: str) -> str:
    """Normalize a domain host to ASCII Punycode, supporting emoji and symbol labels."""
    normalized = host.strip().rstrip(".").lower()
    if not normalized:
        raise idna.IDNAError("Empty hostname")

    try:
        return idna.encode(normalized, uts46=True).decode("ascii")
    except idna.IDNAError:
        encoded_labels: list[str] = []
        for raw_label in normalized.split("."):
            if not raw_label:
                raise idna.IDNAError("Empty domain label") from None

            if raw_label.isascii():
                if len(raw_label) > 63 or not _ASCII_LABEL_RE.match(raw_label):
                    raise idna.IDNAError(f"Invalid ASCII label: {raw_label!r}") from None
                if raw_label.startswith("-") or raw_label.endswith("-"):
                    raise idna.IDNAError(f"Invalid hyphen placement in label: {raw_label!r}") from None
                encoded_labels.append(raw_label)
            else:
                folded = unicodedata.normalize("NFC", raw_label.casefold())
                puny = folded.encode("punycode").decode("ascii")
                ace_label = f"xn--{puny}"
                if len(ace_label) > 63:
                    raise idna.IDNAError("Encoded label exceeds 63 octets") from None
                encoded_labels.append(ace_label)

        candidate = ".".join(encoded_labels)
        if len(candidate) > 253:
            raise idna.IDNAError("Hostname exceeds 253 characters") from None
        return candidate
