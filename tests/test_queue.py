"""Tests for shorts_generator.queue.load_urls — list/file resolution (no network)."""
from shorts_generator.queue import load_urls


def test_load_urls_from_args():
    assert load_urls(["https://youtu.be/a", "https://youtu.be/b"]) == [
        "https://youtu.be/a",
        "https://youtu.be/b",
    ]


def test_load_urls_from_txt_file(tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text(
        "# a comment\n"
        "https://youtu.be/first\n"
        "\n"
        "  https://youtu.be/second  \n"
        "https://youtu.be/third\n",
        encoding="utf-8",
    )
    out = load_urls([str(f)])
    assert out == ["https://youtu.be/first", "https://youtu.be/second", "https://youtu.be/third"]


def test_load_urls_single_non_txt_arg_is_args():
    assert load_urls(["https://youtu.be/only"]) == ["https://youtu.be/only"]


def test_load_urls_single_txt_missing_file_returns_arg(tmp_path):
    # non-existent .txt is treated as a literal arg (not a file)
    out = load_urls(["does-not-exist.txt"])
    assert out == ["does-not-exist.txt"]
