"""One human-readable attribution representation shared by report formats."""
from .handoff import safe_snapshot

DISCLAIMER='Attribution assessments are evidence-backed analytic judgments and do not by themselves establish legal ownership or identity.'


def provenance_lines(capture):
    metadata=capture.get('metadata_json') or {}
    lines=[f"Evidence SHA-256: {capture['content_sha256']}"]
    for field,title in [('origin_label_id','Original Label'),('origin_match_id','Original Research match'),
                        ('origin_discovery_observation_id','Original Discovery observation')]:
        if capture.get(field):lines.append(f"{title}: {capture[field]}")
    if metadata.get('source_subsystem'):lines.append(f"Source subsystem: {metadata['source_subsystem']}")
    if metadata.get('discovery_result_id'):
        lines.extend([f"Discovery result: {metadata['discovery_result_id']}",
            f"Observation fingerprint: {metadata.get('observation_fingerprint')}",
            f"Review note: {metadata.get('analyst_review_note') or 'Not supplied'}"])
    source_capture=metadata.get('capture')
    if isinstance(source_capture,dict):
        for key,title in [('id','Public capture ID'),('requested_url','Requested URL'),('final_url','Final URL'),
                          ('retrieved_at','Source capture time'),('body_sha256','Source body SHA-256'),
                          ('wallet_present_in_capture','Wallet literal present')]:
            lines.append(f"{title}: {source_capture.get(key)}")
        review=metadata.get('review') or {}
        lines.append(f"Capture review: {review.get('status')} / version {review.get('sequence')}; {review.get('note') or ''}")
        origin=source_capture.get('origin') or {}
        lines.append(f"Source search origin: observation {origin.get('observation_id')}; result {origin.get('result_id')}; run {origin.get('run_id')}; provider {origin.get('provider')}")
    snapshot=(metadata.get('observation') or {}).get('source_snapshot') or {}
    if snapshot.get('source_id')=='ofac_sdn':
        entity=snapshot.get('entity') or {};identifier=snapshot.get('identifier') or {}
        lines.extend([f"OFAC snapshot: {snapshot.get('snapshot_id')}; SHA-256: {snapshot.get('snapshot_sha256')}",
            f"OFAC source entity: {entity.get('source_entity_id')}; {entity.get('name')}; programs: {', '.join(entity.get('programs') or [])}",
            f"Raw digital-currency identifier: {identifier.get('raw_value')}; source field: {identifier.get('source_field')}",
            f"Source association at observation: {snapshot.get('listing_state')} / {snapshot.get('match_type')}",
            "OFAC association is source evidence; no automatic ownership or control conclusion."])
    cluster=metadata.get('technical_cluster')
    if isinstance(cluster,dict):
        lines.append(f"Analyst contextual cluster reference: {cluster.get('cluster_id')}; version {cluster.get('version')}. Technical grouping does not establish a common owner.")
    return lines


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
                lines+=provenance_lines(capture)
                if now_link and (now_link['stance']!=link['stance'] or now_link['directness']!=link['directness']):
                    lines+=[f"Current relevance changed: {now_link['stance']} / {now_link['directness']}; historical role retained above."]
    return lines
