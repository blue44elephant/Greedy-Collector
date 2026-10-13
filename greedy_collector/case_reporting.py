"""Four export formats rendered from one sanitized, historical Case snapshot."""
from html import escape
from io import BytesIO
import json
from pathlib import Path
from .reporting import DISCLAIMER, chain_limitations, risk_snapshot_lines
from .attribution.reporting import attribution_lines
from .clustering.reporting import cluster_lines
from .fund_flow.reporting import flow_lines

def pretty(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)

def methodology_limitations(state):
    entities = state["entities"]
    kinds = {r["entity_type"] for r in entities}
    result = chain_limitations(entities)
    if kinds & {"wallet", "transaction", "graph_snapshot"}:
        result.append("Transaction history is bounded by collection and provider coverage. References do not imply complete lifetime history.")
    if any(r["metadata_json"].get("chain") in ("bitcoin", "litecoin") for r in entities):
        result.append("UTXO input/output relationships do not determine individual input-to-output allocations.")
    if any(r["metadata_json"].get("risk_assessment") for r in entities):
        result.append("Risk scores are deterministic indicators, not probabilities or proof of wrongdoing.")
    if "technical_cluster" in kinds:
        result.append("Technical clusters do not establish common ownership.")
    if kinds & {"broad_discovery", "discovery_run", "discovery_observation", "public_source_capture"}:
        result.append("Discovery results and source statements are observations, not verified identity or control.")
    if state["sanctions_pins"]:
        result.append("OFAC screening state is historical as observed in the pinned snapshot, not a current rescreen or ownership conclusion.")
    if state["attribution"].get("references"):
        result.append("Attribution assessments are scoped analytic judgments, not established legal ownership or identity.")
    return result

def sections(state, metadata):
    case, entities = state["case"], state["entities"]
    result = [("Case details", [
        case["title"], f"Case ID: {case['id']}; revision: {case['version']}; status: {case['status']}",
        f"Created: {case['created_at']}; updated: {case['updated_at']}; archived: {case['archived_at']}",
        case.get("description") or "",
    ])]
    summary = case.get("summary") or {}
    if summary:
        result.append(("Analyst-authored summary", [f"{k.replace('_', ' ').title()}: {v}" for k, v in summary.items() if v]))
    def group(title, kinds):
        rows = [row for row in entities if row["entity_type"] in kinds]
        if rows:
            result.append((title, [f"{'PINNED HISTORICAL SNAPSHOT' if any(k.endswith('_pin') or k.endswith('_snapshot') or k == 'risk_assessment' for k in row['metadata_json']) else 'LIVE REFERENCE'}: {row['entity_type']} / {row['entity_ref']}; added: {row.get('added_at') or 'Not recorded before CASE-2'}\n" + pretty(row["metadata_json"]) for row in rows]))
        return rows
    wallets = group("Wallet references", ("wallet",))
    risk_entities = [dict(row, entity_type="wallet") for row in entities if row["entity_type"] in ("wallet", "risk_assessment")]
    risk = risk_snapshot_lines(risk_entities)
    if risk:
        result.append(("Pinned risk assessments", risk + [
            "Risk scores are deterministic indicators, not probabilities or proof of wrongdoing.",
            pretty([r["metadata_json"]["risk_assessment"] for r in risk_entities if "risk_assessment" in r["metadata_json"]])]))
    if state["sanctions_pins"]:
        result.append(("Pinned sanctions screening", [
            "The listing and match state below is historical, as observed at pin time. It is not a current rescreen or an ownership conclusion.",
            pretty(state["sanctions_pins"])]))
    group("Transaction and graph references", ("transaction", "graph_snapshot"))
    group("Pinned label assertions", ("label",))
    if any(row["entity_type"] == "technical_cluster" for row in entities):
        result.append(("Technical clustering", cluster_lines(entities) +
            ["Technical cluster != owner.", pretty([r for r in entities if r["entity_type"] == "technical_cluster"])]))
    if any(row["entity_type"] == "fund_flow" for row in entities):
        result.append(("Observed Fund Flow", flow_lines(entities)))
    discovery = group("Discovery / OSINT historical material", ("broad_discovery", "discovery_run", "discovery_observation"))
    captures = group("Public Source Captures", ("public_source_capture",))
    if discovery or captures:
        result.append(("Source methodology", [
            "Discovery results and source statements are observations, not verified identity. Provider coverage and cache/truncation states apply to the recorded run.",
            "A webpage capture hash identifies preserved source bytes; wallet text presence does not establish control or ownership."]))
    attribution = dict(state["attribution"], generated_at=metadata["generated_at"])
    if attribution.get("references"):
        # Adapt the existing prose renderer without including live comparisons.
        from copy import deepcopy
        historical = deepcopy(attribution)
        for item in historical["references"]:
            item["current"] = {"claim": None, "entity": None, "changed": False}
            for evidence in item["evidence"]:
                evidence["current_link"] = None
        lines = [line for line in attribution_lines(historical) if not line.startswith("Current")]
        result.append(("Pinned Attribution", lines))
    notes = [n for n in state["notes"] if not n["archived_at"]]
    if notes:
        result.append(("Analyst notes / decisions", [
            f"Note {n['id']}; version {n['version']}; author {n['author']}; created {n['created_at']}; updated {n['updated_at']}\n{n['body']}" for n in notes]))
    group("Attachments / integrity", ("attachment",))
    if state["alerts"]:
        result.append(("Associated alerts at report generation", [pretty(state["alerts"])]))
    limitations = methodology_limitations(state)
    if limitations:
        result.append(("Scope / coverage limitations", limitations))
    result.append(("Provenance / report metadata", [pretty(metadata),
        "Exact immutable source IDs, versions, timestamps and fingerprints are included with each historical material section.",
        "The report SHA-256 is recorded in report history and response headers; a report cannot contain its own final byte hash."]))
    result.append(("Disclaimer", [DISCLAIMER]))
    return result

def render(state, metadata, format):
    if format == "json":
        return pretty({**state, "report": metadata, "limitations": methodology_limitations(state),
                       "disclaimer": DISCLAIMER}).encode("utf-8")
    blocks = sections(state, metadata)
    if format == "markdown":
        lines = ["# Greedy Collector investigation report", ""]
        for title, body in blocks:
            lines += ["## " + title, ""]
            for item in body:
                # Indented literal blocks preserve identifiers and source text while
                # preventing HTML, links, fences or headings from becoming active.
                lines += ["    " + line for line in str(item).splitlines()]
                lines.append("")
        return "\n".join(lines).encode("utf-8")
    if format == "html":
        body = "".join("<section><h2>" + escape(title) + "</h2>" +
            "".join("<p>" + escape(str(item)).replace("\n", "<br>") + "</p>" for item in values) + "</section>" for title, values in blocks)
        return ("<!doctype html><html><head><meta charset='utf-8'><title>Case report</title><style>"
                "body{font:15px system-ui;max-width:960px;margin:32px auto;padding:0 20px;line-height:1.5}"
                "p{white-space:pre-wrap;overflow-wrap:anywhere}section{border-bottom:1px solid #ccc;padding:12px 0}"
                "@media print{section{break-inside:auto}h2{break-after:avoid}}</style></head><body>"
                "<h1>Greedy Collector investigation report</h1>" + body + "</body></html>").encode("utf-8")
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import reportlab
    # ReportLab's bundled Bitstream Vera supports Latin, Greek and Cyrillic.
    # Wider installed fonts are preferred; the full UTF-8 JSON/HTML exports are lossless.
    candidates = [Path("C:/Windows/Fonts/arial.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                  Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"]
    font = next((p for p in candidates if p.is_file()), None)
    if font and "CaseUnicode" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("CaseUnicode", str(font)))
    widths = pdfmetrics.getFont("CaseUnicode").face.charWidths if font else {}
    def pdf_text(value):
        # Retain exact unsupported Unicode by explicit code point, rather than
        # silently printing missing-glyph squares. UTF-8 exports retain originals.
        text = "".join(c if ord(c) in widths or ord(c) < 128 else f"[U+{ord(c):04X}]" for c in str(value))
        return escape(text)
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = "CaseUnicode" if font else "Helvetica"
        style.wordWrap = "CJK"  # Break uninterrupted hashes/URLs without clipping.
        style.splitLongWords = True
    styles["BodyText"].fontSize = 9
    styles["BodyText"].leading = 13
    buffer = BytesIO()
    story = [Paragraph("Greedy Collector investigation report", styles["Title"]),
        Paragraph("Unicode glyphs unavailable in the installed report font are written as [U+XXXX]. Original Unicode is retained in JSON, HTML and Markdown exports.", styles["BodyText"])]
    for title, body in blocks:
        story.append(Paragraph(pdf_text(title), styles["Heading2"]))
        for item in body:
            for line in str(item).splitlines():
                # Separate paragraphs allow very large evidence blocks to span pages.
                story.append(Paragraph(pdf_text(line), styles["BodyText"]) if line else Spacer(1, 5))
    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
        topMargin=16*mm, bottomMargin=16*mm, title=state["case"]["title"])
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawString(18*mm, 9*mm, f"Report {metadata['id']} / page {doc.page}")
        canvas.restoreState()
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
