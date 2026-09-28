from .fund_flow.reporting import flow_lines
from .clustering.reporting import cluster_lines
from html import escape
from io import BytesIO
import json
from .attribution.reporting import attribution_lines, DISCLAIMER as ATTRIBUTION_DISCLAIMER
from .attribution.handoff import safe_snapshot


DISCLAIMER = (
    "This tool identifies public blockchain risk indicators for analyst review. "
    "It does not prove criminal activity or identify real-world ownership."
)


def chain_limitations(entities: list[dict]) -> list[str]:
    from .chains import Capability, get_chain
    chains = set()
    for entity in entities:
        metadata = entity.get("metadata_json") or entity.get("metadata") or {}
        if isinstance(metadata, dict) and isinstance(metadata.get("chain"), str):
            chains.add(metadata["chain"])
    limitations = []
    for chain in sorted(chains):
        try:
            definition = get_chain(chain)
        except ValueError:
            continue
        if Capability.TRANSACTION_HISTORY not in definition.capabilities:
            limitations.append(
                f"{definition.display_name}: Public address-level transaction reconstruction unavailable. "
                "This limitation does not indicate inactivity."
            )
    return limitations


def case_markdown(case: dict, entities: list[dict], alerts: list[dict], notes: list[dict], attribution: dict | None = None) -> str:
    lines = [
        f"# {case['title']}",
        "",
        f"Status: {case['status']}",
        "",
        case.get("description", ""),
        "",
        "## Entities",
        "",
    ]
    lines.extend(
        f"- {item['entity_type']}: `{item['entity_ref']}`" for item in entities
    )
    limitations = chain_limitations(entities)
    if limitations:
        lines.extend(["", "## Chain capability limitations", ""])
        lines.extend(f"- {item}" for item in limitations)
    lines.extend(["", "## Alerts", ""])
    lines.extend(
        f"- [{item['severity']}] {item['trigger_type']}: {item['explanation']}"
        for item in alerts
    )
    lines.extend(["", "## Analyst Notes", ""])
    lines.extend(f"- {item['body']}" for item in notes)
    from .discovery.broad.service import report_lines
    lines.extend(report_lines(entities))
    lines.extend(flow_lines(entities))
    lines.extend(cluster_lines(entities))
    lines.extend(attribution_lines(attribution))
    lines.extend(["", "## Disclaimer", "", DISCLAIMER])
    return "\n".join(lines)


def case_html(case: dict, entities: list[dict], alerts: list[dict], notes: list[dict], attribution: dict | None = None) -> str:
    markdown = case_markdown(case, entities, alerts, notes, attribution)
    body = "\n".join(
        f"<p>{escape(line)}</p>" if line else "<br>" for line in markdown.splitlines()
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Greedy Collector Case Report</title>"
        "<style>body{font:14px Arial;max-width:900px;margin:40px auto}"
        "p{margin:.35rem 0} .disclaimer{border:1px solid #555;padding:12px}</style>"
        f"</head><body>{body}</body></html>"
    )


def case_json(case: dict, entities: list[dict], alerts: list[dict], notes: list[dict], attribution: dict | None = None) -> str:
    return json.dumps(
        {
            "case": case,
            "entities": entities,
            "alerts": alerts,
            "notes": notes,
            "limitations": chain_limitations(entities),
            "disclaimer": DISCLAIMER,
            **({"attribution": {**safe_snapshot(attribution), "disclaimer": ATTRIBUTION_DISCLAIMER}} if attribution is not None else {}),
        },
        default=str,
        indent=2,
    )


def case_pdf(case: dict, entities: list[dict], alerts: list[dict], notes: list[dict], attribution: dict | None = None) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=case["title"],
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(escape(case["title"]), styles["Title"]),
        Paragraph(f"Status: {escape(case['status'])}", styles["Normal"]),
        Spacer(1, 8),
        Paragraph(escape(case.get("description", "")), styles["BodyText"]),
        Paragraph("Entities", styles["Heading2"]),
    ]
    story.extend(
        Paragraph(
            f"{escape(item['entity_type'])}: {escape(item['entity_ref'])}",
            styles["BodyText"],
        )
        for item in entities
    )
    limitations = chain_limitations(entities)
    if limitations:
        story.append(Paragraph("Chain capability limitations", styles["Heading2"]))
        story.extend(Paragraph(escape(item), styles["BodyText"]) for item in limitations)
    story.append(Paragraph("Alerts", styles["Heading2"]))
    story.extend(
        Paragraph(
            f"[{escape(item['severity'])}] {escape(item['trigger_type'])}: "
            f"{escape(item['explanation'])}",
            styles["BodyText"],
        )
        for item in alerts
    )
    story.append(Paragraph("Analyst Notes", styles["Heading2"]))
    story.extend(
        Paragraph(escape(item["body"]), styles["BodyText"]) for item in notes
    )
    for line in flow_lines(entities) + cluster_lines(entities) + attribution_lines(attribution):
        story.append(Paragraph(escape(line), styles["BodyText"]) if line else Spacer(1,6))
    story.extend(
        [
            Spacer(1, 12),
            Paragraph("Disclaimer", styles["Heading2"]),
            Paragraph(DISCLAIMER, styles["BodyText"]),
        ]
    )
    document.build(story)
    return buffer.getvalue()
