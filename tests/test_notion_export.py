"""Tests for Notion report export metadata and property building."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.export.notion_exporter import (
    NotionExportConfig,
    NotionExportError,
    build_page_properties,
    build_page_markdown,
    build_summary_markdown,
    _normalize_notion_id,
)
from tradingagents.export.report_metadata import (
    build_data_summary,
    build_notion_title,
    build_run_metadata,
    load_report_metadata,
    parse_decision_fields,
    parse_folder_name,
    research_depth_label,
    write_report_metadata,
)


def test_research_depth_labels():
    assert research_depth_label(1) == "Shallow"
    assert research_depth_label(3) == "Medium"
    assert research_depth_label(5) == "Deep"


def test_build_notion_title():
    assert build_notion_title("MU", "2026-05-18") == "MU — 2026-05-18"


def test_parse_folder_name():
    parsed = parse_folder_name("MU_20260518_225110")
    assert parsed["ticker"] == "MU"
    assert parsed["analysis_date"] == "2026-05-18"
    assert parsed["folder_name"] == "MU_20260518_225110"


def test_parse_decision_fields():
    text = "**Rating**: Overweight\n**Price Target**: 900.0\n**Time Horizon**: 3-6 months"
    fields = parse_decision_fields(text)
    assert fields["rating"] == "Overweight"
    assert fields["price_target"] == "900.0"
    assert fields["time_horizon"] == "3-6 months"


def test_build_data_summary():
    summary = build_data_summary(
        {
            "core_stock_apis": "yfinance",
            "news_data": "yfinance",
        }
    )
    assert "yfinance" in summary
    assert "core stock apis" in summary


def test_build_run_metadata(tmp_path):
    selections = {
        "ticker": "PLTR",
        "analysis_date": "2026-05-18",
        "research_depth": 3,
        "llm_provider": "openai",
        "deep_thinker": "gpt-5.4",
        "shallow_thinker": "gpt-5.4-mini",
        "analysts": [],
    }
    config = {
        "data_vendors": {"core_stock_apis": "yfinance", "news_data": "yfinance"},
    }
    meta = build_run_metadata(
        selections=selections,
        config=config,
        save_path=tmp_path,
        decision_rating="Buy",
    )
    assert meta["notion_title"] == "PLTR — 2026-05-18"
    assert meta["research_depth_label"] == "Medium"
    assert meta["decision_rating"] == "Buy"


def test_write_and_load_report_metadata(tmp_path):
    meta = {
        "ticker": "MU",
        "analysis_date": "2026-05-18",
        "notion_title": "MU — 2026-05-18",
    }
    write_report_metadata(tmp_path, meta)
    loaded = load_report_metadata(tmp_path)
    assert loaded["ticker"] == "MU"
    assert loaded["notion_title"] == "MU — 2026-05-18"


def test_load_report_metadata_fallback(tmp_path):
    (tmp_path / "complete_report.md").write_text(
        "# Trading Analysis Report: MU\n\nGenerated: 2026-05-18\n",
        encoding="utf-8",
    )
    folder = tmp_path / "MU_20260518_225110"
    folder.mkdir()
    (folder / "complete_report.md").write_text(
        "# Trading Analysis Report: MU\n\nBody.",
        encoding="utf-8",
    )
    meta = load_report_metadata(folder)
    assert meta["ticker"] == "MU"
    assert meta["analysis_date"] == "2026-05-18"
    assert meta["notion_title"] == "MU — 2026-05-18"


def test_normalize_notion_id():
    raw = "31a06d222d36804a86c2d03216036a79"
    assert _normalize_notion_id(raw) == "31a06d22-2d36-804a-86c2-d03216036a79"


def test_build_page_properties():
    cfg = NotionExportConfig(
        api_key="x",
        database_id="db",
        prop_title="Name",
        prop_date="Date",
        prop_llm="LLM",
        prop_data="Data",
        prop_research_depth="Research Depth",
        prop_rating=None,
    )
    schema = {
        "Name": "title",
        "Date": "date",
        "LLM": "rich_text",
        "Data": "rich_text",
        "Research Depth": "select",
    }
    meta = {
        "notion_title": "MU — 2026-05-18",
        "analysis_date": "2026-05-18",
        "llm_provider": "openai",
        "deep_think_llm": "gpt-5.4",
        "quick_think_llm": "gpt-5.4-mini",
        "data_summary": "yfinance",
        "research_depth_label": "Shallow",
    }
    props = build_page_properties(meta, schema, cfg)
    assert props["Name"]["title"][0]["text"]["content"] == "MU — 2026-05-18"
    assert props["Date"]["date"]["start"] == "2026-05-18"
    assert props["Research Depth"]["select"]["name"] == "Shallow"


def test_build_page_properties_missing_prop_raises():
    cfg = NotionExportConfig(
        api_key="x",
        database_id="db",
        prop_title="Missing",
        prop_date=None,
        prop_llm=None,
        prop_data=None,
        prop_research_depth=None,
        prop_rating=None,
    )
    with pytest.raises(NotionExportError, match="not found"):
        build_page_properties({"notion_title": "X"}, {"Name": "title"}, cfg)


def test_build_summary_and_page_markdown(tmp_path):
    meta = {
        "decision_rating": "Buy",
        "decision_price_target": "100",
        "decision_time_horizon": "6 months",
    }
    summary = build_summary_markdown(meta)
    assert "Rating" in summary
    (tmp_path / "complete_report.md").write_text("# Report\n\nContent.", encoding="utf-8")
    body = build_page_markdown(tmp_path, meta)
    assert "Content." in body
    assert "Rating" in body


@patch("notion_client.Client")
def test_export_report_to_notion(mock_client_cls, tmp_path):
    (tmp_path / "complete_report.md").write_text("# Trading Analysis Report: MU\n", encoding="utf-8")
    write_report_metadata(
        tmp_path,
        {
            "ticker": "MU",
            "analysis_date": "2026-05-18",
            "notion_title": "MU — 2026-05-18",
            "llm_provider": "openai",
            "deep_think_llm": "a",
            "quick_think_llm": "b",
            "data_summary": "yfinance",
            "research_depth_label": "Shallow",
        },
    )

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.databases.retrieve.return_value = {
        "properties": {
            "Name": {"type": "title"},
            "Date": {"type": "date"},
            "LLM": {"type": "rich_text"},
            "Data": {"type": "rich_text"},
            "Research Depth": {"type": "select"},
        }
    }
    mock_client.pages.create.return_value = {
        "id": "page-id",
        "url": "https://www.notion.so/test",
    }

    cfg = NotionExportConfig(
        api_key="secret",
        database_id="31a06d22-2d36-804a-86c2-d03216036a79",
        prop_title="Name",
        prop_date="Date",
        prop_llm="LLM",
        prop_data="Data",
        prop_research_depth="Research Depth",
        prop_rating=None,
    )

    from tradingagents.export.notion_exporter import export_report_to_notion

    url = export_report_to_notion(tmp_path, cfg=cfg)
    assert url == "https://www.notion.so/test"
    mock_client.pages.create.assert_called_once()
