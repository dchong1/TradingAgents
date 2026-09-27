"""Build and load report metadata for Notion export."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESEARCH_DEPTH_LABELS = {
    1: "Shallow",
    3: "Medium",
    5: "Deep",
}

_FOLDER_RE = re.compile(
    r"^(?P<ticker>[A-Za-z0-9.^\-]+)_(?P<date>\d{8})_(?P<time>\d{6})$"
)
_HEADER_TICKER_RE = re.compile(
    r"^#\s+Trading Analysis Report:\s*(?P<ticker>.+?)\s*$", re.MULTILINE
)
_RATING_RE = re.compile(r"\*\*Rating\*\*:\s*(.+)", re.IGNORECASE)
_PRICE_TARGET_RE = re.compile(r"\*\*Price Target\*\*:\s*(.+)", re.IGNORECASE)
_TIME_HORIZON_RE = re.compile(r"\*\*Time Horizon\*\*:\s*(.+)", re.IGNORECASE)


def research_depth_label(depth: int) -> str:
    return RESEARCH_DEPTH_LABELS.get(depth, str(depth))


def build_data_summary(data_vendors: dict[str, str]) -> str:
    if not data_vendors:
        return ""
    parts = [f"{k.replace('_', ' ')}={v}" for k, v in sorted(data_vendors.items())]
    vendors = sorted({v for v in data_vendors.values()})
    vendor_str = vendors[0] if len(vendors) == 1 else ", ".join(vendors)
    return f"{vendor_str} ({', '.join(parts)})"


def build_notion_title(ticker: str, analysis_date: str) -> str:
    return f"{ticker} — {analysis_date}"


def parse_decision_fields(decision_text: str | None) -> dict[str, str]:
    if not decision_text:
        return {}
    fields: dict[str, str] = {}
    if m := _RATING_RE.search(decision_text):
        fields["rating"] = m.group(1).strip()
    if m := _PRICE_TARGET_RE.search(decision_text):
        fields["price_target"] = m.group(1).strip()
    if m := _TIME_HORIZON_RE.search(decision_text):
        fields["time_horizon"] = m.group(1).strip()
    return fields


def parse_folder_name(folder_name: str) -> dict[str, str]:
    m = _FOLDER_RE.match(folder_name)
    if not m:
        return {}
    ymd = m.group("date")
    try:
        analysis_date = datetime.strptime(ymd, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        analysis_date = ""
    return {
        "ticker": m.group("ticker").upper(),
        "analysis_date": analysis_date,
        "folder_name": folder_name,
    }


def parse_report_header(complete_report_path: Path) -> dict[str, str]:
    if not complete_report_path.is_file():
        return {}
    text = complete_report_path.read_text(encoding="utf-8", errors="replace")[:4096]
    out: dict[str, str] = {}
    if m := _HEADER_TICKER_RE.search(text):
        out["ticker"] = m.group("ticker").strip().upper()
    return out


def build_run_metadata(
    *,
    selections: dict[str, Any],
    config: dict[str, Any],
    save_path: Path,
    decision_rating: str | None = None,
) -> dict[str, Any]:
    ticker = selections["ticker"]
    analysis_date = selections["analysis_date"]
    depth = int(selections["research_depth"])
    analysts = [a.value if hasattr(a, "value") else str(a) for a in selections["analysts"]]
    decision_path = save_path / "5_portfolio" / "decision.md"
    decision_fields = parse_decision_fields(
        decision_path.read_text(encoding="utf-8") if decision_path.is_file() else None
    )
    rating = decision_rating or decision_fields.get("rating")

    return {
        "ticker": ticker,
        "analysis_date": analysis_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "llm_provider": selections.get("llm_provider") or config.get("llm_provider", ""),
        "deep_think_llm": (
            selections.get("deep_think_llm")
            or selections.get("deep_thinker")
            or config.get("deep_think_llm", "")
        ),
        "quick_think_llm": (
            selections.get("quick_think_llm")
            or selections.get("shallow_thinker")
            or config.get("quick_think_llm", "")
        ),
        "research_depth": depth,
        "research_depth_label": research_depth_label(depth),
        "data_summary": build_data_summary(config.get("data_vendors") or {}),
        "analysts": analysts,
        "decision_rating": rating,
        "decision_price_target": decision_fields.get("price_target"),
        "decision_time_horizon": decision_fields.get("time_horizon"),
        "local_path": str(save_path.resolve()),
        "folder_name": save_path.name,
        "notion_title": build_notion_title(ticker, analysis_date),
    }


def write_report_metadata(save_path: Path, metadata: dict[str, Any]) -> Path:
    path = save_path / "report_meta.json"
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_report_metadata(report_dir: Path) -> dict[str, Any]:
    report_dir = report_dir.resolve()
    meta_path = report_dir / "report_meta.json"
    if meta_path.is_file():
        return json.loads(meta_path.read_text(encoding="utf-8"))

    meta: dict[str, Any] = parse_folder_name(report_dir.name)
    complete = report_dir / "complete_report.md"
    meta.update(parse_report_header(complete))
    if meta.get("ticker") and meta.get("analysis_date"):
        meta["notion_title"] = build_notion_title(meta["ticker"], meta["analysis_date"])
    decision_path = report_dir / "5_portfolio" / "decision.md"
    if decision_path.is_file():
        fields = parse_decision_fields(decision_path.read_text(encoding="utf-8"))
        meta.update(
            {
                "decision_rating": fields.get("rating"),
                "decision_price_target": fields.get("price_target"),
                "decision_time_horizon": fields.get("time_horizon"),
            }
        )
    meta["local_path"] = str(report_dir)
    meta["folder_name"] = report_dir.name
    return meta


def format_llm_summary(meta: dict[str, Any]) -> str:
    provider = meta.get("llm_provider") or ""
    deep = meta.get("deep_think_llm") or ""
    quick = meta.get("quick_think_llm") or ""
    if not provider and not deep and not quick:
        return ""
    return f"{provider} | deep: {deep} | quick: {quick}".strip(" |")
