from html import escape
from io import BytesIO
import json


DISCLAIMER = (
    "This tool identifies public blockchain risk indicators for analyst review. "
    "It does not prove criminal activity or identify real-world ownership."
)


def case_markdown(case: dict, entities: list[dict], alerts: list[dict], notes: list[dict]) -> str:
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
    lines.extend(["", "## Alerts", ""])
    lines.extend(
        f"- [{item['severity']}] {item['trigger_type']}: {item['explanation']}"
        for item in alerts
    )
    lines.extend(["", "## Analyst Notes", ""])
    lines.extend(f"- {item['body']}" for item in notes)
    lines.extend(["", "## Disclaimer", "", DISCLAIMER])
    return "\n".join(lines)


def case_html(case: dict, entities: list[dict], alerts: list[dict], notes: list[dict]) -> str:
    markdown = case_markdown(case, entities, alerts, notes)
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


def case_json(case: dict, entities: list[dict], alerts: list[dict], notes: list[dict]) -> str:
    return json.dumps(
        {
            "case": case,
            "entities": entities,
            "alerts": alerts,
            "notes": notes,
            "disclaimer": DISCLAIMER,
        },
        default=str,
        indent=2,
    )


def case_pdf(case: dict, entities: list[dict], alerts: list[dict], notes: list[dict]) -> bytes:
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
    story.extend(
        [
            Spacer(1, 12),
            Paragraph("Disclaimer", styles["Heading2"]),
            Paragraph(DISCLAIMER, styles["BodyText"]),
        ]
    )
    document.build(story)
    return buffer.getvalue()
