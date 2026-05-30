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


def test_track_title_hyphen_pattern():
    observation = parse_filename("01 - Papercut.mp3")

    assert observation.possible_artist is None
    assert observation.possible_title == "Papercut"
    assert observation.possible_track_number == "01"
    assert observation.filename_pattern == "track_title"


def test_track_title_dot_pattern():
    observation = parse_filename("1. Papercut.mp3")

    assert observation.possible_artist is None
    assert observation.possible_title == "Papercut"
    assert observation.possible_track_number == "1"
    assert observation.filename_pattern == "track_title"


def test_track_word_title_pattern():
    observation = parse_filename("Track 01 - Papercut.mp3")

    assert observation.possible_artist is None
    assert observation.possible_title == "Papercut"
    assert observation.possible_track_number == "01"
    assert observation.filename_pattern == "track_title"


def test_duplicated_space_track_prefix_strips_from_title():
    observation = parse_filename("01 01 Wake.flac")

    assert observation.possible_artist is None
    assert observation.possible_title == "Wake"
    assert observation.possible_track_number == "01"
    assert observation.filename_pattern == "track_title"


def test_duplicated_dot_track_prefix_strips_from_title():
    observation = parse_filename("01 01. Like A Shadow.flac")

    assert observation.possible_artist is None
    assert observation.possible_title == "Like A Shadow"
    assert observation.possible_track_number == "01"
    assert observation.filename_pattern == "track_title"


def test_duplicated_dash_track_prefix_strips_from_title():
    observation = parse_filename("01 - 01 Wake.flac")

    assert observation.possible_artist is None
    assert observation.possible_title == "Wake"
    assert observation.possible_track_number == "01"
    assert observation.filename_pattern == "track_title"


def test_duplicated_track_word_prefix_strips_from_title():
    observation = parse_filename("Track 01 - 01 Wake.flac")

    assert observation.possible_artist is None
    assert observation.possible_title == "Wake"
    assert observation.possible_track_number == "01"
    assert observation.filename_pattern == "track_title"


def test_double_digit_duplicated_track_prefix_strips_from_title():
    observation = parse_filename("10 10 In Between.flac")

    assert observation.possible_artist is None
    assert observation.possible_title == "In Between"
    assert observation.possible_track_number == "10"
    assert observation.filename_pattern == "track_title"


def test_normal_numbered_title_remains_correct():
    observation = parse_filename("01 Papercut.flac")

    assert observation.possible_artist is None
    assert observation.possible_title == "Papercut"
    assert observation.possible_track_number == "01"
    assert observation.filename_pattern == "track_title"


def test_artist_title_beginning_with_number_is_preserved():
    observation = parse_filename("10 Years - Wasteland.flac")

    assert observation.possible_artist == "10 Years"
    assert observation.possible_title == "Wasteland"
    assert observation.possible_track_number is None
    assert observation.filename_pattern == "artist_title"


def test_artist_title_remix_pattern():
    observation = parse_filename("Artist - Title (Remix).mp3")

    assert observation.possible_artist == "Artist"
    assert observation.possible_title == "Title"
    assert observation.possible_mix == "Remix"
    assert observation.filename_pattern == "artist_title_with_mix"


def test_parenthetical_subtitle_is_preserved_as_title_text():
    observation = parse_filename("01 My Own Summer (Shove It).flac")

    assert observation.possible_artist is None
    assert observation.possible_title == "My Own Summer (Shove It)"
    assert observation.possible_mix is None
    assert observation.possible_track_number == "01"
    assert observation.filename_pattern == "track_title"


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
