from tagger.filename_parser import parse_filename


def test_simple_artist_title():
    p = parse_filename("Daft Punk - One More Time.mp3")
    assert p.artist == "Daft Punk"
    assert p.title == "One More Time"


def test_leading_track_number():
    p = parse_filename("01 - Daft Punk - One More Time.flac")
    assert p.artist == "Daft Punk"
    assert p.title == "One More Time"


def test_bracketed_remix_info_extracted():
    p = parse_filename("Fisher - Losing It (Original Mix).mp3")
    assert p.artist == "Fisher"
    assert p.title == "Losing It"
    assert p.extra_info == ["Original Mix"]


def test_underscore_separators():
    p = parse_filename("Bicep_-_Glue.wav")
    assert p.artist == "Bicep"
    assert p.title == "Glue"


def test_no_artist_falls_back_to_title_only():
    p = parse_filename("Untitled Track.mp3")
    assert p.artist is None
    assert p.title == "Untitled Track"


def test_multiple_bracketed_suffixes():
    p = parse_filename("Artist - Title (feat. Someone) [Radio Edit].mp3")
    assert p.artist == "Artist"
    assert p.title == "Title"
    assert p.extra_info == ["feat. Someone", "Radio Edit"]
