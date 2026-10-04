from dataclasses import FrozenInstanceError

import pytest

from golded_ftn import ReaderIssue, ReaderOptions


def test_archive_mode_requires_reporter() -> None:
    with pytest.raises(ValueError, match="on_issue"):
        ReaderOptions(archive_mode=True)


def test_archive_issue_is_immutable_and_callback_receives_it() -> None:
    issues: list[ReaderIssue] = []
    options = ReaderOptions(archive_mode=True, on_issue=issues.append)
    issue = ReaderIssue(
        source_type="jam",
        source_path="fictional.JHR",
        source_id="4",
        source_offset=1024,
        action="skipped",
        code="record_parse_error",
        detail="Invalid signature",
    )
    assert options.on_issue is not None
    options.on_issue(issue)
    assert issues == [issue]
    with pytest.raises(FrozenInstanceError):
        issue.code = "other"  # type: ignore[misc]


def test_strict_default_has_no_reporter() -> None:
    assert not ReaderOptions().archive_mode
    assert ReaderOptions().on_issue is None
