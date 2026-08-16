import csv
from pathlib import Path

from tagger.folder_recommend import (
    VERDICT_COPY,
    VERDICT_FLAG_REBUY,
    VERDICT_REVIEW_INDIVIDUALLY,
    VERDICT_SKIP,
    Track,
    generate_copy_script,
    individual_reviews,
    load_and_join,
    recommend_folders,
)


def _track(folder, artist, popularity=None, danceability=None, low_bitrate=False, filename=None):
    filename = filename or f"{artist}.mp3"
    return Track(
        filename=filename,
        playlist=folder.split("/")[-1],
        artist=artist,
        genre="",
        format="MPEG Audio",
        low_bitrate=low_bitrate,
        full_path=f"{folder}/{filename}",
        popularity=popularity,
        danceability=danceability,
    )


def test_low_popularity_folder_is_skipped():
    tracks = [
        _track("N:/Noir Desir", "Noir Desir", popularity=20, danceability=10),
        _track("N:/Noir Desir", "Noir Desir", popularity=15, danceability=5),
    ]
    results = recommend_folders(tracks, min_popularity=40, min_danceability=40)
    assert len(results) == 1
    assert results[0].verdict == VERDICT_SKIP


def test_popular_good_quality_folder_is_copy():
    tracks = [
        _track("N:/Macklemore", "Macklemore", popularity=70, danceability=60, low_bitrate=False),
        _track("N:/Macklemore", "Macklemore", popularity=65, danceability=55, low_bitrate=False),
    ]
    results = recommend_folders(tracks, min_popularity=40, min_danceability=40)
    assert results[0].verdict == VERDICT_COPY


def test_popular_but_low_bitrate_folder_is_flagged_for_rebuy():
    tracks = [
        _track("N:/NRJ Music Awards 2012", "Various", popularity=80, low_bitrate=True),
        _track("N:/NRJ Music Awards 2012", "Various", popularity=75, low_bitrate=True),
    ]
    results = recommend_folders(tracks, min_popularity=40, min_danceability=40)
    assert results[0].verdict == VERDICT_FLAG_REBUY


def test_mixed_dump_folder_falls_back_to_individual_review():
    tracks = [
        _track("N:/2011.04", "Artist A", popularity=80, low_bitrate=False, filename="a.mp3"),
        _track("N:/2011.04", "Artist B", popularity=10, low_bitrate=False, filename="b.mp3"),
        _track("N:/2011.04", "Artist C", popularity=90, low_bitrate=True, filename="c.mp3"),
    ]
    results = recommend_folders(tracks, min_popularity=40, min_danceability=40)
    assert results[0].verdict == VERDICT_REVIEW_INDIVIDUALLY
    assert results[0].coherent is False

    reviews = individual_reviews(results, min_popularity=40, min_danceability=40)
    by_filename = {r["filename"]: r["verdict"] for r in reviews}
    assert by_filename["a.mp3"] == VERDICT_COPY
    assert by_filename["b.mp3"] == VERDICT_SKIP
    assert by_filename["c.mp3"] == VERDICT_FLAG_REBUY


def test_dominant_artist_share_makes_folder_coherent_despite_one_outlier():
    tracks = [_track("N:/Daft Punk", "Daft Punk", popularity=90) for _ in range(4)]
    tracks.append(_track("N:/Daft Punk", "Someone Else", popularity=90, filename="x.mp3"))
    results = recommend_folders(tracks, min_popularity=40, min_danceability=40, coherence_threshold=0.5)
    assert results[0].coherent is True
    assert results[0].verdict == VERDICT_COPY


def test_load_and_join_matches_on_filename_and_playlist(tmp_path: Path):
    inv_path = tmp_path / "nas_only.csv"
    scored_path = tmp_path / "scored.csv"

    with inv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "artist", "title", "playlist", "genre", "format",
                                                 "extension", "bitrate_kbps", "duration_min", "filesize_mb",
                                                 "low_bitrate", "full_path"])
        writer.writeheader()
        writer.writerow({"filename": "Fisher - Losing It.mp3", "artist": "Fisher", "title": "Losing It",
                          "playlist": "Wedding Sets", "genre": "", "format": "MPEG Audio", "extension": "mp3",
                          "bitrate_kbps": "320", "duration_min": "3.5", "filesize_mb": "8", "low_bitrate": "False",
                          "full_path": "N:/Wedding Sets/Fisher - Losing It.mp3"})

    with scored_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["raw_filename", "playlist", "matched", "source", "matched_artist",
                                                 "matched_title", "match_confidence", "popularity",
                                                 "estimated_energy", "estimated_danceability", "genre_tags",
                                                 "worth_score"])
        writer.writeheader()
        writer.writerow({"raw_filename": "Fisher - Losing It.mp3", "playlist": "Wedding Sets", "matched": "True",
                          "source": "deezer", "matched_artist": "FISHER", "matched_title": "Losing It",
                          "match_confidence": "100.0", "popularity": "97", "estimated_energy": "",
                          "estimated_danceability": "85", "genre_tags": "", "worth_score": "97.0"})

    tracks = load_and_join(str(inv_path), str(scored_path))
    assert len(tracks) == 1
    assert tracks[0].popularity == 97.0
    assert tracks[0].danceability == 85.0


def test_generate_copy_script_contains_robocopy_and_copyitem():
    folders = recommend_folders(
        [
            _track("N:/Music/Macklemore", "Macklemore", popularity=70, low_bitrate=False),
            _track("N:/Music/Macklemore", "Macklemore", popularity=70, low_bitrate=False),
        ],
        min_popularity=40,
        min_danceability=40,
    )
    individual_rows = [
        {"folder": "N:/Music/2011.04", "filename": "a.mp3", "artist": "A", "popularity": 80, "danceability": "",
         "low_bitrate": False, "verdict": VERDICT_COPY, "full_path": "N:/Music/2011.04/a.mp3"},
    ]

    script = generate_copy_script(folders, individual_rows, nas_root="N:/Music", usb_root="D:/DJ")

    assert "robocopy" in script
    assert "D:\\DJ\\Macklemore" in script
    assert "Copy-Item" in script
    assert "D:\\DJ\\2011.04\\a.mp3" in script


def test_generate_copy_script_escapes_quotes_in_paths():
    folders = recommend_folders(
        [_track('N:/Music/Weird "Folder"', "Artist", popularity=80)],
        min_popularity=40,
        min_danceability=40,
    )
    script = generate_copy_script(folders, [], nas_root="N:/Music", usb_root="D:/DJ")
    assert '`"Folder`"' in script
