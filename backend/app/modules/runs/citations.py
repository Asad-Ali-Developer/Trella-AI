"""Citation validator and enricher for LLM insights.

Grounds all generated claims by verifying that cited source IDs exist
in the workspace context graph, and enriches citations with real titles and URLs.
"""

from typing import Any

from app.modules.context.schemas import WorkspaceContextResponse
from app.modules.skills.schemas import CitedSource, ClientNeedsReport


def build_context_source_index(
    context: WorkspaceContextResponse,
) -> dict[str, dict[str, Any]]:
    """Build a lookup index mapping lowercase ID strings to source metadata."""
    index: dict[str, dict[str, Any]] = {}

    # Index sources/boards/repositories
    for source in context.sources:
        source_meta: dict[str, Any] = {
            "title": source.name,
            "url": source.url,
            "source_type": "project" if source.provider == "trello" else "source",
        }
        index[str(source.id).strip().lower()] = source_meta

    # Index context items across all chunks
    for chunk in context.chunks:
        for item in chunk.items:
            item_meta: dict[str, Any] = {
                "title": item.title or (item.text[:60] if item.text else None),
                "url": item.url,
                "source_type": item.item_type,
            }
            if item.external_id:
                index[item.external_id.strip().lower()] = item_meta
            if item.card_id:
                index[str(item.card_id).strip().lower()] = item_meta
            if item.source_id:
                source_key = str(item.source_id).strip().lower()
                if source_key not in index:
                    index[source_key] = item_meta

    return index


def validate_and_enrich_citations(
    report: ClientNeedsReport,
    context: WorkspaceContextResponse,
) -> tuple[ClientNeedsReport, bool]:
    """Validate and enrich citations across all sections of a ClientNeedsReport.

    For the 4 core sections (needs, patterns, stakeholders, risks), items with
    zero valid citations are stripped from the report.

    Returns:
        tuple[ClientNeedsReport, bool]: The enriched report and a boolean indicating
        whether ALL cited sources were valid and grounded in the input context.
    """
    index = build_context_source_index(context)
    all_citations_valid = True

    def _process_sources(sources: list[CitedSource]) -> list[CitedSource]:
        nonlocal all_citations_valid
        enriched: list[CitedSource] = []
        for src in sources:
            key = src.source_id.strip().lower()
            if key in index:
                meta = index[key]
                enriched.append(
                    CitedSource(
                        source_id=src.source_id,
                        source_type=src.source_type or meta.get("source_type", "card"),
                        title=meta.get("title") or src.title,
                        url=meta.get("url") or src.url,
                        valid=True,
                    )
                )
            else:
                all_citations_valid = False
        return enriched

    def _filter_section(items: list[Any]) -> list[Any]:
        nonlocal all_citations_valid
        kept: list[Any] = []
        for item in items:
            if not item.sources:
                all_citations_valid = False
                continue
            valid_sources = _process_sources(item.sources)
            if not valid_sources:
                all_citations_valid = False
                continue
            item.sources = valid_sources
            kept.append(item)
        return kept

    report.needs = _filter_section(report.needs)
    report.patterns = _filter_section(report.patterns)
    report.stakeholders = _filter_section(report.stakeholders)
    report.risks = _filter_section(report.risks)

    return report, all_citations_valid
