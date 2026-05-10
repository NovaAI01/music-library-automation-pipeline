import sqlite3

import pytest

from app import db
from app.main import main
from app.purchase_gateway import (
    add_purchase_option,
    attach_purchase_proof,
    build_purchase_report,
    can_unlock_intake,
    create_purchase_request,
    unlock_intake,
    validate_artist_in_seed_list,
)


def test_baseline_artist_purchase_request_accepted(tmp_path):
    request = create_purchase_request(
        artist="SOAD",
        title="Chop Suey!",
        db_path=tmp_path / "ledger.sqlite3",
    )

    assert request.artist == "System of a Down"
    assert request.title == "Chop Suey!"
    assert request.request_status == "requested"


def test_non_baseline_artist_rejected():
    with pytest.raises(ValueError, match="not in baseline seed list"):
        validate_artist_in_seed_list("Some New Artist")


def test_purchase_option_can_be_added_to_request(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    request = create_purchase_request(
        artist="Deftones",
        title="Change",
        db_path=db_path,
    )

    option = add_purchase_option(
        request_id=request.id,
        provider_name="Bandcamp",
        provider_url="https://example.com/deftones-change",
        purchase_type="digital_download",
        price=1.29,
        currency="GBP",
        usage_scope="private DJ use",
        db_path=db_path,
    )

    assert option.purchase_request_id == request.id
    assert option.provider_name == "Bandcamp"
    assert option.provider_url == "https://example.com/deftones-change"
    assert _request_status(db_path, request.id) == "option_found"


def test_purchase_proof_can_be_attached(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    option = _request_with_option(db_path)

    proof = attach_purchase_proof(
        option_id=option.id,
        proof_path="~/Receipts/deftones-change.pdf",
        proof_status="user_declared",
        db_path=db_path,
    )

    assert proof.purchase_option_id == option.id
    assert proof.proof_path.endswith("Receipts/deftones-change.pdf")
    assert proof.proof_status == "user_declared"
    assert _request_status(db_path, option.purchase_request_id) == "purchased"


def test_missing_proof_blocks_unlock(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    request = create_purchase_request(
        artist="Deftones",
        title="Change",
        db_path=db_path,
    )

    decision = can_unlock_intake(request.id, db_path)

    assert not decision.can_unlock
    assert decision.reason == "proof_missing"
    with pytest.raises(ValueError, match="proof_missing"):
        unlock_intake(request.id, db_path)


def test_rejected_proof_blocks_unlock(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    option = _request_with_option(db_path)
    attach_purchase_proof(
        option_id=option.id,
        proof_path="/tmp/rejected.pdf",
        proof_status="rejected",
        db_path=db_path,
    )

    decision = can_unlock_intake(option.purchase_request_id, db_path)

    assert not decision.can_unlock
    assert decision.reason == "proof_rejected"


def test_user_declared_proof_unlocks_with_flagged_status(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    option = _request_with_option(db_path)
    proof = attach_purchase_proof(
        option_id=option.id,
        proof_path="/tmp/user-declared.pdf",
        proof_status="user_declared",
        db_path=db_path,
    )

    unlock = unlock_intake(option.purchase_request_id, db_path)

    assert unlock.proof_id == proof.id
    assert unlock.unlock_status == "flagged"
    assert _request_status(db_path, option.purchase_request_id) == "intake_unlocked"


def test_verified_proof_unlocks_with_clean_status(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    option = _request_with_option(db_path)
    proof = attach_purchase_proof(
        option_id=option.id,
        proof_path="/tmp/verified.pdf",
        proof_status="verified",
        db_path=db_path,
    )

    unlock = unlock_intake(option.purchase_request_id, db_path)

    assert unlock.proof_id == proof.id
    assert unlock.unlock_status == "clean"


def test_purchase_report_groups_by_status(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    create_purchase_request(artist="Deftones", title="Change", db_path=db_path)
    _request_with_option(db_path)

    report = build_purchase_report(db_path)

    assert report["total"] == 2
    assert report["by_status"]["requested"] == 1
    assert report["by_status"]["option_found"] == 1


def test_repeated_unlock_does_not_duplicate_intake_unlock_rows(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    option = _request_with_option(db_path)
    attach_purchase_proof(
        option_id=option.id,
        proof_path="/tmp/verified.pdf",
        proof_status="verified",
        db_path=db_path,
    )

    first = unlock_intake(option.purchase_request_id, db_path)
    second = unlock_intake(option.purchase_request_id, db_path)

    assert first.id == second.id
    rows = _fetch_all(db_path, "SELECT * FROM intake_unlocks")
    assert len(rows) == 1


def test_cli_purchase_flow(tmp_path, capsys):
    db_path = tmp_path / "ledger.sqlite3"

    assert (
        main(
            [
                "--db",
                str(db_path),
                "purchase-request",
                "--artist",
                "Deftones",
                "--title",
                "Change",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--db",
                str(db_path),
                "purchase-option-add",
                "--request-id",
                "1",
                "--provider",
                "Bandcamp",
                "--url",
                "https://example.com",
                "--type",
                "digital_download",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--db",
                str(db_path),
                "purchase-proof-add",
                "--option-id",
                "1",
                "--proof",
                "/tmp/receipt.pdf",
                "--status",
                "user_declared",
            ]
        )
        == 0
    )
    assert (
        main(["--db", str(db_path), "purchase-unlock", "--request-id", "1"])
        == 0
    )
    assert main(["--db", str(db_path), "purchase-report"]) == 0

    output = capsys.readouterr().out
    assert "request_id=1" in output
    assert "option_id=1" in output
    assert "proof_id=1" in output
    assert "unlock_status=flagged" in output
    assert "intake_unlocked=1" in output


def _request_with_option(db_path):
    request = create_purchase_request(
        artist="Deftones",
        title="Change",
        db_path=db_path,
    )
    return add_purchase_option(
        request_id=request.id,
        provider_name="Bandcamp",
        provider_url="https://example.com/deftones-change",
        purchase_type="digital_download",
        db_path=db_path,
    )


def _request_status(db_path, request_id):
    return _fetch_all(
        db_path,
        f"SELECT request_status FROM purchase_requests WHERE id = {request_id}",
    )[0]["request_status"]


def _fetch_all(db_path, sql):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()
