"""Export TradingAgents reports to a Notion database."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingagents.export.report_metadata import (
    format_llm_summary,
    load_report_metadata,
)

NOTION_BLOCK_TEXT_LIMIT = 2000


class NotionExportError(Exception):
    """Raised when Notion export cannot proceed."""


@dataclass
class NotionExportConfig:
    api_key: str
    database_id: str
    prop_title: str
    prop_date: str | None
    prop_llm: str | None
    prop_data: str | None
    prop_research_depth: str | None
    prop_rating: str | None

    @classmethod
    def from_env(cls) -> NotionExportConfig:
        api_key = os.environ.get("NOTION_API_KEY", "").strip()
        database_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
        if not api_key or not database_id:
            raise NotionExportError(
                "NOTION_API_KEY and NOTION_DATABASE_ID must be set in the environment."
            )
        return cls(
            api_key=api_key,
            database_id=_normalize_notion_id(database_id),
            prop_title=os.environ.get("NOTION_PROP_TITLE", "Name").strip() or "Name",
            prop_date=_optional_env("NOTION_PROP_DATE"),
            prop_llm=_optional_env("NOTION_PROP_LLM"),
            prop_data=_optional_env("NOTION_PROP_DATA"),
            prop_research_depth=_optional_env("NOTION_PROP_RESEARCH_DEPTH"),
            prop_rating=_optional_env("NOTION_PROP_RATING"),
        )


def _optional_env(name: str) -> str | None:
    val = os.environ.get(name, "").strip()
    return val or None


def _normalize_notion_id(raw: str) -> str:
    """Accept UUID with or without hyphens."""
    s = raw.replace("-", "")
    if len(s) == 32 and re.fullmatch(r"[0-9a-fA-F]{32}", s):
        return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"
    return raw


def notion_configured() -> bool:
    return bool(os.environ.get("NOTION_API_KEY", "").strip()) and bool(
        os.environ.get("NOTION_DATABASE_ID", "").strip()
    )


def _rich_text(content: str) -> dict[str, Any]:
    return {"rich_text": [{"type": "text", "text": {"content": content[:NOTION_BLOCK_TEXT_LIMIT]}}]}


def _title_prop(content: str) -> dict[str, Any]:
    return {"title": [{"type": "text", "text": {"content": content[:NOTION_BLOCK_TEXT_LIMIT]}}]}


def _date_prop(iso_date: str) -> dict[str, Any]:
    return {"date": {"start": iso_date}}


def _select_prop(name: str) -> dict[str, Any]:
    return {"select": {"name": name[:NOTION_BLOCK_TEXT_LIMIT]}}


def _property_value(prop_type: str, value: str) -> dict[str, Any]:
    if prop_type == "title":
        return _title_prop(value)
    if prop_type == "rich_text":
        return _rich_text(value)
    if prop_type == "select":
        return _select_prop(value)
    if prop_type == "multi_select":
        names = [p.strip()[:100] for p in re.split(r"[,|]", value) if p.strip()]
        if not names:
            names = [value[:100]]
        return {"multi_select": [{"name": n} for n in names[:10]]}
    if prop_type == "date":
        return _date_prop(value)
    if prop_type == "url":
        return {"url": value}
    if prop_type == "number":
        try:
            return {"number": float(value)}
        except ValueError:
            return _rich_text(value)
    raise NotionExportError(
        f"Unsupported Notion property type '{prop_type}' for value '{value[:40]}...'. "
        "Use rich_text or select in your database, or skip this property."
    )


def _fetch_database_schema(client: Any, database_id: str) -> dict[str, str]:
    db = client.databases.retrieve(database_id=database_id)
    props = db.get("properties") or {}
    # Notion API 2025+: column schema lives on the linked data source, not the database object.
    if not props and db.get("data_sources"):
        ds_id = db["data_sources"][0]["id"]
        ds = client.data_sources.retrieve(data_source_id=ds_id)
        props = ds.get("properties") or {}
    return {name: info.get("type", "") for name, info in props.items()}


def build_page_properties(
    meta: dict[str, Any],
    schema: dict[str, str],
    cfg: NotionExportConfig,
) -> dict[str, Any]:
    title = meta.get("notion_title") or meta.get("ticker", "Report")
    if cfg.prop_title not in schema:
        raise NotionExportError(
            f"Title property '{cfg.prop_title}' not found in database. "
            f"Available: {', '.join(sorted(schema))}"
        )
    properties: dict[str, Any] = {
        cfg.prop_title: _property_value(schema[cfg.prop_title], title),
    }

    mapping = [
        (cfg.prop_date, meta.get("analysis_date"), "date"),
        (cfg.prop_llm, format_llm_summary(meta), None),
        (cfg.prop_data, meta.get("data_summary"), None),
        (cfg.prop_research_depth, meta.get("research_depth_label"), None),
        (cfg.prop_rating, meta.get("decision_rating"), None),
    ]
    for prop_name, value, preferred_type in mapping:
        if not prop_name or not value:
            continue
        if prop_name not in schema:
            raise NotionExportError(
                f"Property '{prop_name}' not found in database. "
                f"Available: {', '.join(sorted(schema))}"
            )
        prop_type = schema[prop_name]
        if preferred_type and prop_type != preferred_type:
            # Allow rich_text/select as fallback for date-like fields misconfigured
            if not (preferred_type == "date" and prop_type in ("rich_text", "select")):
                pass
        properties[prop_name] = _property_value(prop_type, str(value))

    return properties


def build_summary_markdown(meta: dict[str, Any]) -> str:
    lines = []
    if meta.get("decision_rating"):
        lines.append(f"**Rating:** {meta['decision_rating']}")
    if meta.get("decision_price_target"):
        lines.append(f"**Price Target:** {meta['decision_price_target']}")
    if meta.get("decision_time_horizon"):
        lines.append(f"**Time Horizon:** {meta['decision_time_horizon']}")
    if not lines:
        return ""
    return "> " + " | ".join(lines)


def build_page_markdown(report_dir: Path, meta: dict[str, Any]) -> str:
    complete = report_dir / "complete_report.md"
    if not complete.is_file():
        raise NotionExportError(f"Missing {complete}")
    body = complete.read_text(encoding="utf-8")
    summary = build_summary_markdown(meta)
    parts = []
    if summary:
        parts.append(summary)
        parts.append("\n---\n")
    parts.append(body)
    return "\n".join(parts)


def _chunk_paragraph_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    while text:
        chunk = text[:NOTION_BLOCK_TEXT_LIMIT]
        text = text[NOTION_BLOCK_TEXT_LIMIT:]
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]},
            }
        )
    return blocks or [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": []},
        }
    ]


def _append_markdown_content(client: Any, page_id: str, markdown: str) -> None:
    """Append page body via block children (chunked paragraphs)."""
    # Split on double newlines to preserve some structure; oversized sections chunk further.
    sections = re.split(r"\n\n+", markdown)
    children: list[dict[str, Any]] = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if section.startswith("> "):
            children.append(
                {
                    "object": "block",
                    "type": "callout",
                    "callout": {
                        "rich_text": [{"type": "text", "text": {"content": section[2:][:NOTION_BLOCK_TEXT_LIMIT]}}],
                        "icon": {"emoji": "📊"},
                    },
                }
            )
            continue
        if section == "---":
            children.append({"object": "block", "type": "divider", "divider": {}})
            continue
        if section.startswith("# "):
            children.append(
                {
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {
                        "rich_text": [{"type": "text", "text": {"content": section[2:][:NOTION_BLOCK_TEXT_LIMIT]}}]
                    },
                }
            )
            continue
        if section.startswith("## "):
            children.append(
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"type": "text", "text": {"content": section[3:][:NOTION_BLOCK_TEXT_LIMIT]}}]
                    },
                }
            )
            continue
        if section.startswith("### "):
            children.append(
                {
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [{"type": "text", "text": {"content": section[4:][:NOTION_BLOCK_TEXT_LIMIT]}}]
                    },
                }
            )
            continue
        children.extend(_chunk_paragraph_blocks(section))

    batch_size = 100
    for i in range(0, len(children), batch_size):
        client.blocks.children.append(block_id=page_id, children=children[i : i + batch_size])


def _try_create_with_markdown(client: Any, parent: dict, properties: dict, markdown: str) -> Any | None:
    """Attempt Notion markdown API if supported by the installed client."""
    try:
        return client.pages.create(
            parent=parent,
            properties=properties,
            markdown=markdown,
        )
    except TypeError:
        return None
    except Exception:
        return None


def export_report_to_notion(report_dir: Path, *, cfg: NotionExportConfig | None = None) -> str:
    """
    Create a Notion database page for the report.

    Returns the public Notion page URL.
    """
    from notion_client import Client
    from notion_client.errors import APIResponseError

    report_dir = report_dir.resolve()
    cfg = cfg or NotionExportConfig.from_env()
    meta = load_report_metadata(report_dir)
    if not meta.get("notion_title") and meta.get("ticker") and meta.get("analysis_date"):
        from tradingagents.export.report_metadata import build_notion_title

        meta["notion_title"] = build_notion_title(meta["ticker"], meta["analysis_date"])

    markdown_body = build_page_markdown(report_dir, meta)
    client = Client(auth=cfg.api_key)
    schema = _fetch_database_schema(client, cfg.database_id)
    properties = build_page_properties(meta, schema, cfg)
    parent = {"database_id": cfg.database_id}

    page = _try_create_with_markdown(client, parent, properties, markdown_body)
    if page is None:
        page = client.pages.create(parent=parent, properties=properties)
        page_id = page["id"]
        _append_markdown_content(client, page_id, markdown_body)
    else:
        page_id = page["id"]

    url = page.get("url") if isinstance(page, dict) else None
    if not url:
        url = f"https://www.notion.so/{page_id.replace('-', '')}"
    return url


def print_notion_schema() -> None:
    """Print database properties for manual .env mapping."""
    from notion_client import Client
    from rich.console import Console
    from rich.table import Table

    cfg = NotionExportConfig.from_env()
    client = Client(auth=cfg.api_key)
    schema = _fetch_database_schema(client, cfg.database_id)

    console = Console()
    table = Table(title="Notion database properties")
    table.add_column("Property name", style="cyan")
    table.add_column("Type")
    table.add_column("Suggested env var")

    suggestions = {
        "title": "NOTION_PROP_TITLE",
        "date": "NOTION_PROP_DATE",
    }
    for name, ptype in sorted(schema.items()):
        env = suggestions.get(ptype, "")
        if ptype == "rich_text" and "llm" in name.lower():
            env = "NOTION_PROP_LLM"
        elif ptype in ("rich_text", "select") and "data" in name.lower():
            env = "NOTION_PROP_DATA"
        elif ptype in ("rich_text", "select") and "research" in name.lower():
            env = "NOTION_PROP_RESEARCH_DEPTH"
        elif ptype in ("rich_text", "select") and "rating" in name.lower():
            env = "NOTION_PROP_RATING"
        table.add_row(name, ptype, env)

    console.print(table)
    console.print(f"\n[dim]Database ID:[/dim] {cfg.database_id}")
    console.print("[dim]Copy property names into .env (see .env.example).[/dim]")
