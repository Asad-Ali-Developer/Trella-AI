"""Pure conversion from Atlassian Document Format (ADF) to plain text."""

from typing import Any


def adf_to_text(node: Any) -> str:
    """Recursively convert an Atlassian Document Format (ADF) node or string to plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float, bool)):
        return str(node)
    if isinstance(node, list):
        parts = [adf_to_text(item) for item in node]
        return "".join(p for p in parts if p).strip()
    if not isinstance(node, dict):
        return ""

    return _render_node(node).strip()


def _render_node(node: dict[str, Any], *, list_prefix: str = "") -> str:
    node_type = node.get("type")
    content = node.get("content")
    attrs = node.get("attrs")
    attrs_dict = attrs if isinstance(attrs, dict) else {}

    if node_type == "text":
        text_val = node.get("text")
        return text_val if isinstance(text_val, str) else ""

    if node_type in ("hardBreak", "rule"):
        return "\n"

    if node_type == "mention":
        mention_text = attrs_dict.get("text") or attrs_dict.get("id") or ""
        return str(mention_text)

    if node_type == "emoji":
        emoji_text = attrs_dict.get("text") or attrs_dict.get("shortName") or ""
        return str(emoji_text)

    if node_type in ("inlineCard", "blockCard", "embedCard"):
        url = attrs_dict.get("url")
        if isinstance(url, str) and url:
            return url
        data = attrs_dict.get("data")
        if isinstance(data, dict) and isinstance(data.get("url"), str):
            return str(data["url"])
        return ""

    if node_type == "status":
        status_text = attrs_dict.get("text")
        return f"[{status_text}]" if isinstance(status_text, str) and status_text else ""

    if node_type == "date":
        timestamp = attrs_dict.get("timestamp")
        return str(timestamp) if timestamp is not None else ""

    children = content if isinstance(content, list) else []

    if node_type == "doc":
        blocks = [_render_node(child) for child in children if isinstance(child, dict)]
        return "\n\n".join(b.strip("\n") for b in blocks if b.strip())

    if node_type in ("paragraph", "heading"):
        inline_text = "".join(
            _render_node(child) for child in children if isinstance(child, dict)
        )
        return f"{list_prefix}{inline_text}\n"

    if node_type == "codeBlock":
        code_text = "".join(
            _render_node(child) for child in children if isinstance(child, dict)
        )
        return f"{code_text}\n"

    if node_type in ("blockquote", "panel", "expand", "nestedExpand"):
        title = attrs_dict.get("title")
        inner_blocks = [
            _render_node(child).strip("\n")
            for child in children
            if isinstance(child, dict)
        ]
        body = "\n".join(b for b in inner_blocks if b)
        if isinstance(title, str) and title.strip():
            return f"{title.strip()}\n{body}\n" if body else f"{title.strip()}\n"
        return f"{body}\n"

    if node_type == "bulletList":
        items: list[str] = []
        for child in children:
            if isinstance(child, dict):
                rendered = _render_list_item(child, prefix="- ")
                if rendered:
                    items.append(rendered)
        return "\n".join(items) + ("\n" if items else "")

    if node_type == "orderedList":
        order_start = attrs_dict.get("order", 1)
        start_idx = order_start if isinstance(order_start, int) else 1
        ord_items: list[str] = []
        for offset, child in enumerate(children):
            if isinstance(child, dict):
                rendered = _render_list_item(child, prefix=f"{start_idx + offset}. ")
                if rendered:
                    ord_items.append(rendered)
        return "\n".join(ord_items) + ("\n" if ord_items else "")

    if node_type == "listItem":
        return _render_list_item(node, prefix=list_prefix or "- ")

    if node_type == "table":
        rows: list[str] = []
        for child in children:
            if isinstance(child, dict):
                row_text = _render_node(child).strip()
                if row_text:
                    rows.append(row_text)
        return "\n".join(rows) + ("\n" if rows else "")

    if node_type == "tableRow":
        cells: list[str] = []
        for child in children:
            if isinstance(child, dict):
                cell_text = _render_node(child).strip()
                cells.append(cell_text)
        return " | ".join(cells) + "\n"

    if node_type in ("tableHeader", "tableCell"):
        parts = [
            _render_node(child).strip()
            for child in children
            if isinstance(child, dict)
        ]
        return " ".join(p for p in parts if p)

    if children:
        fallback_parts = [
            _render_node(child) for child in children if isinstance(child, dict)
        ]
        return "".join(fallback_parts)

    text_fallback = node.get("text")
    return text_fallback if isinstance(text_fallback, str) else ""


def _render_list_item(node: dict[str, Any], *, prefix: str) -> str:
    content = node.get("content")
    children = content if isinstance(content, list) else []
    lines: list[str] = []
    first = True
    for child in children:
        if not isinstance(child, dict):
            continue
        child_type = child.get("type")
        if first and child_type in ("paragraph", "heading"):
            rendered = _render_node(child, list_prefix=prefix).strip("\n")
            if rendered:
                lines.append(rendered)
                first = False
        else:
            rendered = _render_node(child).strip("\n")
            if rendered:
                if first:
                    lines.append(f"{prefix}{rendered}")
                    first = False
                else:
                    lines.append(rendered)
    return "\n".join(lines)

