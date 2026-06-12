"""Worker command executor — outcomes must land in the logs table so the
dashboard Logs tab reflects what the worker did (especially failures, which
previously only surfaced on the transient command result)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from opensocial.core.commands import process_commands
from opensocial.core.db import Base, Command, Log, enqueue_command, make_engine


@pytest.fixture()
def session_factory(tmp_path):
    engine = make_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _logs(session_factory, level):
    with session_factory() as s:
        return [l.message for l in s.query(Log).filter_by(level=level).all()]


def test_failed_command_logs_error(session_factory):
    # post_now with a bogus id fails inside the executor — the error must be
    # written to the logs table, not just the command result.
    with session_factory() as s:
        enqueue_command(s, "post_now", {"generated_post_id": "nope"})
        s.commit()
    process_commands(session_factory, config_dir="config/niches")

    errors = _logs(session_factory, "error")
    assert any("post_now failed" in m and "post not found" in m for m in errors)
    with session_factory() as s:
        assert s.query(Command).one().status == "failed"


def test_successful_command_logs_info(session_factory):
    # A generate for an unknown niche resolves to no work but still succeeds —
    # it should log an info line summarizing the (empty) outcome.
    with session_factory() as s:
        enqueue_command(s, "generate_posts", {"niche": "doesnotexist"})
        s.commit()
    process_commands(session_factory, config_dir="config/niches")

    infos = _logs(session_factory, "info")
    assert any("generate_posts [doesnotexist] done" in m for m in infos)
    with session_factory() as s:
        assert s.query(Command).one().status == "done"
