"""One human-readable attribution representation shared by report formats."""
from .handoff import safe_snapshot

DISCLAIMER='Attribution assessments are evidence-backed analytic judgments and do not by themselves establish legal ownership or identity.'


def attribution_lines(material):
    if material is None:return []
    material=safe_snapshot(material)
    lines=['','## Attribution Assessment','',DISCLAIMER,'',f"Report generated: {material['generated_at']}"]
    if material['status']!='ready':return lines+['Attribution storage is not initialized for this database.']
    if not material['references']:return lines+['No attribution references were explicitly added to this case.']
    for item in material['references']:
        pin=item['pinned'];claim=pin['claim'];entity=pin['entity'];current=item['current']
        lines+=['',f"### {'Claim' if claim else 'Entity reference'}: {pin['target_id']}",f"Pinned at: {pin['captured_at']}",
                f"Entity descriptor: {entity['canonical_name']} ({entity['entity_type']}); version {entity['version']}; {'Archived' if entity['archived_at'] else 'Active'}"]
        if not claim:
            lines+=['Entity relevance to this case does not assert control of case wallets.',f"Current entity changed: {current['changed']}"]
            if current['entity']:lines+=[f"Current entity: {current['entity']['canonical_name']}; version {current['entity']['version']}; {'Archived' if current['entity']['archived_at'] else 'Active'}"]
            continue
        lines+=[f"Subject: {claim['chain']} {claim['subject_ref']}",f"Claimed relationship: {claim['relationship']}",
                f"Pinned assessment: {claim['assessment']}; claim version {claim['version']}",f"Pinned review required: {claim['needs_review']}",
                f"Pinned claim state: {'Archived' if claim['archived_at'] else 'Active'}",f"Scope: {claim['scope_note']}",
                f"Valid from: {claim['valid_from'] or 'Unknown'}; valid to: {claim['valid_to'] or 'Unknown'}",
                f"Assessment rationale: {claim['assessment_rationale'] or 'Unassessed'}",
                f"Assessed: {claim['assessed_at'] or 'Not assessed'}; actor: {claim['assessed_by'] or 'Not assessed'}"]
        now=current['claim']
        lines+=[f"Current state changed since pin: {current['changed']}"]
        lines+=['Evidence below is the historical inventory at pin time. Inspect current Attribution for material added afterwards.']
        if now:lines+=[f"Current assessment: {now['assessment']}; version {now['version']}; review required: {now['needs_review']}; {'Archived' if now['archived_at'] else 'Active'}"]
        else:lines+=['Current claim unavailable. Historical pin retained.']
        if current['entity']:lines+=[f"Current entity: {current['entity']['canonical_name']}; {'Archived' if current['entity']['archived_at'] else 'Active'}"]
        for stance,title in [('supports','Supporting evidence'),('contradicts','Contradicting evidence'),('context','Contextual evidence')]:
            lines+=['',f'#### {title}']
            evidence=[row for row in item['evidence'] if row['pinned_link']['stance']==stance]
            if not evidence:lines+=['None in the pinned claim.']
            for row in evidence:
                link=row['pinned_link'];capture=row['capture'];now_link=row['current_link']
                lines+=[f"Evidence: {capture['title']} ({capture['id']})",
                        f"Pinned link state: {'Withdrawn / historical' if link['withdrawn_at'] else 'Active at pin'}",
                        f"Current link state: {'Unavailable' if not now_link else 'Withdrawn / historical' if now_link['withdrawn_at'] else 'Active'}",
                        f"Source: {capture['source_name']}; origin: {capture['origin']}; method: {capture['collection_method']}",
                        f"Source URL: {capture['source_url'] or 'Not supplied'}; locator: {capture['source_locator'] or 'Not supplied'}",
                        f"Summary: {capture['summary']}",f"Excerpt: {capture['excerpt'] or 'Not supplied'}",
                        f"Published: {capture['published_on'] or 'Unknown'}; observed: {capture['observed_on'] or 'Unknown'}; captured: {capture['captured_at']}",
                        f"Pinned directness: {link['directness']}; rationale: {link['rationale']}",
                        f"Source reliability: {capture['source_reliability']}; {capture['reliability_rationale']}"]
                if now_link and (now_link['stance']!=link['stance'] or now_link['directness']!=link['directness']):
                    lines+=[f"Current relevance changed: {now_link['stance']} / {now_link['directness']}; historical role retained above."]
    return lines
