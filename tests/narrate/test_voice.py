from spikecast.narrate.voice import _words


def test_word_timings_follow_the_character_timings():
    text = "The fly feeds."
    chars = list(text)
    starts = [i * 0.1 for i in range(len(chars))]
    ends = [s + 0.1 for s in starts]
    words = _words(
        text,
        {
            "characters": chars,
            "character_start_times_seconds": starts,
            "character_end_times_seconds": ends,
        },
    )
    assert [w["text"] for w in words] == ["The", "fly", "feeds."]
    assert words[0]["start_s"] == 0.0 and words[1]["start_s"] == 0.4
    assert words[2]["end_s"] == round(ends[-1], 3)
