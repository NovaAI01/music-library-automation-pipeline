from app.alias_equivalence import deterministic_artist_alias_equivalence, normalized_alnum_casefold


def test_normalized_alnum_casefold_removes_safe_surface_differences():
    assert normalized_alnum_casefold("System of a Down") == normalized_alnum_casefold("System Of A Down")
    assert normalized_alnum_casefold("Shallow Bay: The Best Of Breaking Benjamin") == normalized_alnum_casefold(
        "Shallow Bay The Best Of Breaking Benjamin"
    )


def test_deterministic_artist_alias_equivalence_known_safe_cases():
    for source, target in (
        ("Tool", "TOOL"),
        ("Red", "RED"),
        ("System of a Down", "System Of A Down"),
        ("Bring Me the Horizon", "Bring Me The Horizon"),
    ):
        decision = _decision(source, target)

        assert decision.safe_to_merge_candidate, decision.reason


def test_deterministic_artist_alias_equivalence_requires_unblocked_lifecycle():
    assert (
        _decision("Bring Me the Horizon", "Bring Me The Horizon", lifecycle_state="blocked").safe_to_merge_candidate
        is False
    )
    assert (
        _decision("Bring Me the Horizon", "Bring Me The Horizon", lifecycle_state="conflicted").safe_to_merge_candidate
        is False
    )


def test_deterministic_artist_alias_equivalence_rejects_suffixes_collaborations_and_wrong_types():
    unsafe_cases = (
        ("Heavy Is the Crown", "Heavy Is the Crown (Official Audio)", "alias_collision", "artist"),
        ("Tom Morello BEARTOOTHband", "Tom Morello, BEARTOOTHband", "alias_collision", "artist"),
        (
            "Shallow Bay The Best Of Breaking Benjamin",
            "Shallow Bay: The Best Of Breaking Benjamin",
            "album_membership_conflict",
            "artist",
        ),
        ("Tool", "TOOL", "role_collision", "artist"),
        ("Tool", "TOOL", "alias_collision", "ambiguous"),
    )

    for source, target, conflict_type, role in unsafe_cases:
        decision = _decision(source, target, conflict_type=conflict_type, entity_role=role)

        assert decision.safe_to_merge_candidate is False, (source, target, decision.reason)


def _decision(
    source: str,
    target: str,
    *,
    conflict_type: str = "alias_collision",
    entity_role: str = "artist",
    lifecycle_state: str = "probationary",
):
    return deterministic_artist_alias_equivalence(
        conflict_type=conflict_type,
        entity_role=entity_role,
        source_entity=source,
        target_entity=target,
        positive_evidence_types={"repeated_artist_metadata"},
        negative_evidence_types=set(),
        confidence_tier="medium",
        lifecycle_state=lifecycle_state,
        artifact_dominates=False,
    )
