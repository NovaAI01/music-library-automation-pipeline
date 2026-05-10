from app.artist_seeds import (
    classify_by_artist,
    list_seed_artists,
    match_seed_artist,
    normalize_artist_name,
)
from app.taxonomy import ENERGY_LEVELS, MOODS, PRIMARY_GENRES, SUBGENRES, VOCAL_STYLES


def test_exact_artist_match():
    result = classify_by_artist("Deftones")

    assert result is not None
    assert result.artist == "Deftones"
    assert result.primary_genre == "Alternative Metal"
    assert result.subgenre == "Shoegaze Metal"
    assert result.energy_level == "high"
    assert result.vocal_style == "mixed"
    assert result.mood == ["dark", "atmospheric", "melodic"]
    assert result.confidence == 0.95
    assert result.evidence == ["artist_seed_match"]


def test_lowercase_match():
    result = match_seed_artist("system of a down")

    assert result is not None
    assert result.artist == "System of a Down"


def test_punctuation_insensitive_match():
    assert normalize_artist_name("P.O.D.") == normalize_artist_name("pod")

    result = match_seed_artist("P O D")

    assert result is not None
    assert result.artist == "P.O.D."


def test_alias_match():
    assert match_seed_artist("SOAD").artist == "System of a Down"
    assert match_seed_artist("NIN").artist == "Nine Inch Nails"
    assert match_seed_artist("BMTH").artist == "Bring Me the Horizon"
    assert match_seed_artist("RATM").artist == "Rage Against the Machine"
    assert match_seed_artist("APC").artist == "A Perfect Circle"


def test_unknown_artist_returns_none():
    assert match_seed_artist("Unknown Artist") is None
    assert classify_by_artist("Unknown Artist") is None


def test_every_seed_artist_has_complete_classification_fields():
    seeds = list_seed_artists()

    assert len(seeds) == 50
    assert len({seed.artist for seed in seeds}) == len(seeds)

    for seed in seeds:
        assert seed.artist
        assert seed.primary_genre in PRIMARY_GENRES
        assert seed.subgenre in SUBGENRES
        assert seed.energy_level in ENERGY_LEVELS
        assert seed.vocal_style in VOCAL_STYLES
        assert seed.mood
        assert all(mood in MOODS for mood in seed.mood)

        result = classify_by_artist(seed.artist)
        assert result is not None
        assert result.artist == seed.artist
        assert result.primary_genre == seed.primary_genre
        assert result.subgenre == seed.subgenre
        assert result.energy_level == seed.energy_level
        assert result.vocal_style == seed.vocal_style
        assert result.mood == seed.mood
        assert result.confidence == 0.95
        assert result.evidence == ["artist_seed_match"]
