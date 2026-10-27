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
    """Build a lookup index mapping ID strings to source metadata."""
    index: dict[str, dict[str, Any]] = {}

    # Index sources/boards/repositories
    for source in context.sources:
        source_meta: dict[str, Any] = {
            "title": source.name,
            "url": source.url,
            "source_type": "project" if source.provider == "trello" else "source",
        }
        index[str(source.id).lower()] = source_meta

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
                index[str(item.card_id).lower()] = item_meta
            if item.source_id:
                # If not already present
                if str(item.source_id).lower() not in index:
                    index[str(item.source_id).lower()] = item_meta

    return index


def validate_and_enrich_citations(
    report: ClientNeedsReport,
    context: WorkspaceContextResponse,
) -> tuple[ClientNeedsReport, bool]:
    """Validate and enrich citations across all sections of a ClientNeedsReport.

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
                enriched.append(
                    CitedSource(
                        source_id=src.source_id,
                        source_type=src.source_type,
                        title=src.title,
                        url=src.url,
                        valid=False,
                    )
                )
        return enriched

    for need in report.needs:
        if not need.sources:
            # An insight without any sources is ungrounded
            all_citations_valid = False
        need.sources = _process_sources(need.sources)

    for pattern in report.patterns:
        if not pattern.sources:
            all_citations_valid = False
        pattern.sources = _process_sources(pattern.sources)

    for stakeholder in report.stakeholders:
        if stakeholder.sources:
            stakeholder.sources = _process_sources(stakeholder.sources)

    for risk in report.risks:
        if not risk.sources:
            all_citations_valid = False
        risk.sources = _process_sources(risk.sources)

    return report, all_citations_valid
