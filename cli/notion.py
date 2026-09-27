"""Notion export prompts and CLI helpers."""

from __future__ import annotations

from pathlib import Path

from cli.display import console


def prompt_export_to_notion(report_dir: Path) -> None:
    from tradingagents.export.notion_exporter import (
        NotionExportError,
        export_report_to_notion,
        notion_configured,
    )

    if not notion_configured():
        console.print(
            "[yellow]Notion export skipped:[/yellow] set NOTION_API_KEY and NOTION_DATABASE_ID in .env, "
            "then run [bold]tradingagents notion-schema[/bold] to map property names."
        )
        return
    try:
        url = export_report_to_notion(report_dir)
        console.print(f"[green]✓ Exported to Notion:[/green] {url}")
    except NotionExportError as e:
        console.print(f"[red]Notion export failed:[/red] {e}")
    except Exception as e:
        console.print(f"[red]Notion export failed:[/red] {e}")
