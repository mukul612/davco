from pathlib import Path

import pytest

from app.services import security


def test_new_job_id_is_valid():
    jid = security.new_job_id()
    assert security.is_valid_job_id(jid)
    assert len(jid) == 32


@pytest.mark.parametrize("bad", ["", "../../etc/passwd", "abc", "not-hex-!!", "a" * 31, "a" * 33])
def test_invalid_job_ids_rejected(bad):
    assert not security.is_valid_job_id(bad)


@pytest.mark.parametrize(
    "raw,expected_ok",
    [
        ("drawing.pdf", "drawing.pdf"),
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system32\\config.pdf", "config.pdf"),
        ("C:\\evil\\path.pdf", "path.pdf"),
        ('weird"name<>|.pdf', "weird_name___.pdf"),
        ("", "drawing"),
        ("   ", "drawing"),
    ],
)
def test_sanitize_filename_strips_paths_and_unsafe_chars(raw, expected_ok):
    result = security.sanitize_filename(raw, fallback="drawing")
    assert result == expected_ok
    assert "/" not in result and "\\" not in result


def test_sanitize_filename_truncates_long_names():
    long_name = ("x" * 300) + ".pdf"
    result = security.sanitize_filename(long_name)
    assert len(result) <= 105
    assert result.endswith(".pdf")


def test_safe_job_path_rejects_bad_ids(tmp_path):
    with pytest.raises(ValueError):
        security.safe_job_path(tmp_path, "../../escape")
    with pytest.raises(ValueError):
        security.safe_job_path(tmp_path, "not-a-uuid")


def test_safe_job_path_accepts_valid_id(tmp_path):
    jid = security.new_job_id()
    p = security.safe_job_path(tmp_path, jid)
    assert p == (tmp_path / jid).resolve()


def test_safe_download_path_blocks_traversal(tmp_path):
    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "output.pdf").write_bytes(b"x")
    # legitimate file
    assert security.safe_download_path(job_dir, "output.pdf").is_file()
    # traversal attempts must be rejected
    with pytest.raises(ValueError):
        security.safe_download_path(job_dir, "../secret.txt")
    with pytest.raises(ValueError):
        security.safe_download_path(job_dir, "../../windows/win.ini")
