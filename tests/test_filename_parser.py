from app.filename_parser import parse_filename


def test_artist_title_pattern():
    observation = parse_filename("Deftones - Change.mp3")

    assert observation.cleaned_filename == "Deftones - Change"
    assert observation.possible_artist == "Deftones"
    assert observation.possible_title == "Change"
    assert observation.possible_mix is None
    assert observation.possible_track_number is None
    assert observation.filename_pattern == "artist_title"


def test_track_artist_title_pattern():
    observation = parse_filename("01 - Deftones - Change.mp3")

    assert observation.possible_artist == "Deftones"
    assert observation.possible_title == "Change"
    assert observation.possible_track_number == "01"
    assert observation.filename_pattern == "track_artist_title"


def test_track_title_pattern():
    observation = parse_filename("01 Change.mp3")

    assert observation.possible_artist is None
    assert observation.possible_title == "Change"
    assert observation.possible_track_number == "01"
    assert observation.filename_pattern == "track_title"


def test_artist_title_remix_pattern():
    observation = parse_filename("Artist - Title (Remix).mp3")

    assert observation.possible_artist == "Artist"
    assert observation.possible_title == "Title"
    assert observation.possible_mix == "Remix"
    assert observation.filename_pattern == "artist_title_with_mix"


def test_hyphenated_artist_title_pattern_preserves_artist_name():
    observation = parse_filename("Static-X - Push It [ubimQkYukxc].flac")

    assert observation.possible_artist == "Static-X"
    assert observation.possible_title == "Push It [ubimQkYukxc]"
    assert observation.filename_pattern == "artist_title"


def test_hyphenated_artist_title_pattern_without_video_id():
    observation = parse_filename("Static-X - Push It.flac")

    assert observation.possible_artist == "Static-X"
    assert observation.possible_title == "Push It"
    assert observation.filename_pattern == "artist_title"


def test_track_hyphenated_artist_title_pattern_preserves_artist_name():
    observation = parse_filename("01 - Static-X - Push It.flac")

    assert observation.possible_track_number == "01"
    assert observation.possible_artist == "Static-X"
    assert observation.possible_title == "Push It"
    assert observation.filename_pattern == "track_artist_title"


def test_artist_title_without_separator_spacing_is_unknown():
    observation = parse_filename("Artist-Title.flac")

    assert observation.possible_artist is None
    assert observation.possible_title == "Artist-Title"
    assert observation.filename_pattern == "unknown"


def test_unknown_pattern():
    observation = parse_filename("Unstructured Filename.mp3")

    assert observation.possible_artist is None
    assert observation.possible_title == "Unstructured Filename"
    assert observation.filename_pattern == "unknown"
    assert observation.parser_confidence == 0.2
