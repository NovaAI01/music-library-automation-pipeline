"""Artist purchase gateway for lawful intake eligibility tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app import db
from app.artist_seeds import match_seed_artist


REQUEST_STATUSES: frozenset[str] = frozenset(
    {"requested", "option_found", "purchased", "rejected", "intake_unlocked"}
)
PROVIDER_NAMES: frozenset[str] = frozenset(
    {
        "Bandcamp",
        "Amazon Music",
        "Apple Music",
        "Beatport",
        "Juno Download",
        "Artist Store",
        "Label Store",
        "Other",
    }
)
PURCHASE_TYPES: frozenset[str] = frozenset(
    {
        "digital_download",
        "licence_purchase",
        "physical_with_download",
        "artist_direct",
        "unknown",
    }
)
PROOF_STATUSES: frozenset[str] = frozenset(
    {"missing", "user_declared", "verified", "rejected"}
)


@dataclass(frozen=True)
class PurchaseRequest:
    id: int
    artist: str
    title: str
    album: str | None
    request_status: str


@dataclass(frozen=True)
class PurchaseOption:
    id: int
    purchase_request_id: int
    provider_name: str
    provider_url: str
    purchase_type: str
    price: float | None
    currency: str | None
    usage_scope: str | None
    option_status: str


@dataclass(frozen=True)
class PurchaseProof:
    id: int
    purchase_option_id: int
    proof_path: str
    proof_type: str
    proof_status: str


@dataclass(frozen=True)
class IntakeUnlock:
    id: int
    purchase_request_id: int
    proof_id: int
    unlock_status: str


@dataclass(frozen=True)
class UnlockDecision:
    can_unlock: bool
    unlock_status: str | None
    proof_id: int | None
    reason: str | None


def validate_artist_in_seed_list(artist: str) -> str:
    """Return canonical seed artist name or raise ValueError."""

    seed = match_seed_artist(artist)
    if seed is None:
        raise ValueError(f"Artist is not in baseline seed list: {artist}")
    return seed.artist


def create_purchase_request(
    *,
    artist: str,
    title: str,
    album: str | None = None,
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> PurchaseRequest:
    """Create a purchase request for a baseline artist."""

    canonical_artist = validate_artist_in_seed_list(artist)
    cleaned_title = _required_text(title, "title")
    cleaned_album = _optional_text(album)
    db.init_db(db_path)

    with db.connect(db_path) as connection:
        row_id = connection.execute(
            """
            INSERT INTO purchase_requests (
                artist,
                title,
                album,
                request_status,
                created_at
            )
            VALUES (?, ?, ?, 'requested', ?)
            """,
            (canonical_artist, cleaned_title, cleaned_album, _now()),
        ).lastrowid

    return PurchaseRequest(
        id=int(row_id),
        artist=canonical_artist,
        title=cleaned_title,
        album=cleaned_album,
        request_status="requested",
    )


def add_purchase_option(
    *,
    request_id: int,
    provider_name: str,
    provider_url: str,
    purchase_type: str,
    price: float | None = None,
    currency: str | None = None,
    format_notes: str | None = None,
    usage_scope: str | None = None,
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> PurchaseOption:
    """Add a manually supplied purchase option URL to a request."""

    provider_name = _validate_provider(provider_name)
    provider_url = _validate_url(provider_url)
    purchase_type = _validate_purchase_type(purchase_type)
    currency = _optional_text(currency)
    format_notes = _optional_text(format_notes)
    usage_scope = _optional_text(usage_scope)
    db.init_db(db_path)

    with db.connect(db_path) as connection:
        _require_purchase_request(connection, request_id)
        row_id = connection.execute(
            """
            INSERT INTO purchase_options (
                purchase_request_id,
                provider_name,
                provider_url,
                purchase_type,
                price,
                currency,
                format_notes,
                usage_scope,
                option_status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'available', ?)
            """,
            (
                request_id,
                provider_name,
                provider_url,
                purchase_type,
                price,
                currency,
                format_notes,
                usage_scope,
                _now(),
            ),
        ).lastrowid
        connection.execute(
            """
            UPDATE purchase_requests
            SET request_status = 'option_found'
            WHERE id = ? AND request_status = 'requested'
            """,
            (request_id,),
        )

    return PurchaseOption(
        id=int(row_id),
        purchase_request_id=request_id,
        provider_name=provider_name,
        provider_url=provider_url,
        purchase_type=purchase_type,
        price=price,
        currency=currency,
        usage_scope=usage_scope,
        option_status="available",
    )


def attach_purchase_proof(
    *,
    option_id: int,
    proof_path: str | Path,
    proof_status: str,
    proof_type: str = "receipt",
    notes: str | None = None,
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> PurchaseProof:
    """Attach user-supplied proof metadata without reading payment details."""

    proof_path = _required_text(str(Path(proof_path).expanduser()), "proof_path")
    proof_status = _validate_proof_status(proof_status)
    proof_type = _required_text(proof_type, "proof_type")
    notes = _optional_text(notes)
    db.init_db(db_path)

    with db.connect(db_path) as connection:
        request_id = _require_purchase_option(connection, option_id)
        row_id = connection.execute(
            """
            INSERT INTO purchase_proofs (
                purchase_option_id,
                proof_path,
                proof_type,
                proof_status,
                notes,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (option_id, proof_path, proof_type, proof_status, notes, _now()),
        ).lastrowid
        if proof_status in {"user_declared", "verified"}:
            connection.execute(
                """
                UPDATE purchase_requests
                SET request_status = 'purchased'
                WHERE id = ? AND request_status IN ('requested', 'option_found')
                """,
                (request_id,),
            )

    return PurchaseProof(
        id=int(row_id),
        purchase_option_id=option_id,
        proof_path=proof_path,
        proof_type=proof_type,
        proof_status=proof_status,
    )


def can_unlock_intake(
    request_id: int, db_path: str | Path = db.DEFAULT_DB_PATH
) -> UnlockDecision:
    """Return whether a request has acceptable proof for intake unlock."""

    db.init_db(db_path)
    with db.connect(db_path) as connection:
        _require_purchase_request(connection, request_id)
        row = connection.execute(
            """
            SELECT
                purchase_proofs.id,
                purchase_proofs.proof_status
            FROM purchase_options
            INNER JOIN purchase_proofs
                ON purchase_proofs.purchase_option_id = purchase_options.id
            WHERE purchase_options.purchase_request_id = ?
            ORDER BY
                CASE purchase_proofs.proof_status
                    WHEN 'verified' THEN 1
                    WHEN 'user_declared' THEN 2
                    WHEN 'rejected' THEN 3
                    WHEN 'missing' THEN 4
                    ELSE 5
                END,
                purchase_proofs.id
            LIMIT 1
            """,
            (request_id,),
        ).fetchone()

    if row is None:
        return UnlockDecision(False, None, None, "proof_missing")
    if row["proof_status"] == "verified":
        return UnlockDecision(True, "clean", int(row["id"]), None)
    if row["proof_status"] == "user_declared":
        return UnlockDecision(True, "flagged", int(row["id"]), None)
    if row["proof_status"] == "rejected":
        return UnlockDecision(False, None, int(row["id"]), "proof_rejected")
    return UnlockDecision(False, None, int(row["id"]), "proof_missing")


def unlock_intake(
    request_id: int, db_path: str | Path = db.DEFAULT_DB_PATH
) -> IntakeUnlock:
    """Unlock intake once acceptable proof exists, without duplicating rows."""

    db.init_db(db_path)
    with db.connect(db_path) as connection:
        existing = connection.execute(
            """
            SELECT id, purchase_request_id, proof_id, unlock_status
            FROM intake_unlocks
            WHERE purchase_request_id = ?
            ORDER BY id
            LIMIT 1
            """,
            (request_id,),
        ).fetchone()
        if existing is not None:
            return IntakeUnlock(
                id=int(existing["id"]),
                purchase_request_id=int(existing["purchase_request_id"]),
                proof_id=int(existing["proof_id"]),
                unlock_status=existing["unlock_status"],
            )

    decision = can_unlock_intake(request_id, db_path)
    if not decision.can_unlock or decision.proof_id is None:
        raise ValueError(decision.reason or "intake_unlock_blocked")

    with db.connect(db_path) as connection:
        row_id = connection.execute(
            """
            INSERT INTO intake_unlocks (
                purchase_request_id,
                proof_id,
                unlock_status,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (request_id, decision.proof_id, decision.unlock_status, _now()),
        ).lastrowid
        connection.execute(
            """
            UPDATE purchase_requests
            SET request_status = 'intake_unlocked'
            WHERE id = ?
            """,
            (request_id,),
        )

    return IntakeUnlock(
        id=int(row_id),
        purchase_request_id=request_id,
        proof_id=decision.proof_id,
        unlock_status=decision.unlock_status or "flagged",
    )


def build_purchase_report(
    db_path: str | Path = db.DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Build deterministic purchase request counts grouped by status."""

    db.init_db(db_path)
    with db.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT request_status, COUNT(*) AS count
            FROM purchase_requests
            GROUP BY request_status
            ORDER BY request_status
            """
        ).fetchall()
        total = connection.execute(
            "SELECT COUNT(*) AS count FROM purchase_requests"
        ).fetchone()["count"]

    by_status = {status: 0 for status in sorted(REQUEST_STATUSES)}
    by_status.update({row["request_status"]: int(row["count"]) for row in rows})
    return {"total": int(total), "by_status": by_status}


def _require_purchase_request(connection, request_id: int) -> None:
    row = connection.execute(
        "SELECT id FROM purchase_requests WHERE id = ?",
        (request_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"purchase request not found: {request_id}")


def _require_purchase_option(connection, option_id: int) -> int:
    row = connection.execute(
        "SELECT purchase_request_id FROM purchase_options WHERE id = ?",
        (option_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"purchase option not found: {option_id}")
    return int(row["purchase_request_id"])


def _validate_provider(value: str) -> str:
    provider = _required_text(value, "provider_name")
    if provider not in PROVIDER_NAMES:
        raise ValueError(f"Unsupported provider_name: {provider}")
    return provider


def _validate_purchase_type(value: str) -> str:
    purchase_type = _required_text(value, "purchase_type")
    if purchase_type not in PURCHASE_TYPES:
        raise ValueError(f"Unsupported purchase_type: {purchase_type}")
    return purchase_type


def _validate_proof_status(value: str) -> str:
    proof_status = _required_text(value, "proof_status")
    if proof_status not in PROOF_STATUSES:
        raise ValueError(f"Unsupported proof_status: {proof_status}")
    return proof_status


def _validate_url(value: str) -> str:
    url = _required_text(value, "provider_url")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid provider_url: {url}")
    return url


def _required_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} is required")
    return cleaned


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _now() -> str:
    return datetime.now(UTC).isoformat()
