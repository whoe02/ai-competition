"""Settings, read the way an operator actually writes them into a .env file."""

from __future__ import annotations

import pytest

from kira.config import Settings


class TestCorsOrigins:
    def test_a_single_origin_needs_no_ceremony(self):
        assert Settings(cors_origins="http://localhost:5173").cors_origins == [
            "http://localhost:5173"
        ]

    def test_several_are_separated_by_commas(self):
        settings = Settings(cors_origins="http://localhost:5173, https://kira.app")
        assert settings.cors_origins == ["http://localhost:5173", "https://kira.app"]

    def test_a_json_list_still_works_for_anyone_already_writing_one(self):
        assert Settings(cors_origins='["https://kira.app"]').cors_origins == ["https://kira.app"]

    def test_a_real_list_is_left_alone(self):
        assert Settings(cors_origins=["https://kira.app"]).cors_origins == ["https://kira.app"]

    def test_an_empty_setting_means_no_origins(self):
        assert Settings(cors_origins="").cors_origins == []


class TestCheckpointerDsn:
    @pytest.mark.parametrize(
        "url",
        [
            "postgresql+asyncpg://kira:kira@localhost:5432/kira",
            "postgresql+psycopg://kira:kira@localhost:5432/kira",
        ],
    )
    def test_it_strips_the_dialect_langgraph_cannot_use(self, url):
        assert (
            Settings(database_url=url).checkpointer_dsn
            == "postgresql://kira:kira@localhost:5432/kira"
        )
