"""Bounded public GraphSense address annotations, never wallet clustering."""
import base64
import binascii
from datetime import date, datetime, timedelta, timezone
import hashlib
import re
from urllib.parse import unquote, urlsplit

import yaml
from sqlalchemy import inspect

from ..attribution.domain import fingerprint, canonical_json
from ..migration_state import supports_revision
from .domain import canonical_subject, clean, DiscoveryError, SchemaUnavailable
from .executors import ExecutionSignal
from . import github
from .manual_source import safe_text, safe_url
from .schemas import Batch

TRANSFORM_ID = 'wallet.graphsense_public_tags'
REPOSITORY = 'graphsense/graphsense-tagpacks'
MAX_FILES = 9  # One search + nine blobs shares ED-4B's ten attempts/minute.
FILE_BYTES = 256 * 1024
TOTAL_BYTES = 1024 * 1024
RESULT_BYTES = 900 * 1024  # Leave room for validated observation defaults/envelope.
NOTE = ('GraphSense published this third-party public annotation for the wallet. '
        'It does not establish current control, legal ownership or common ownership. '
        'Actor, confidence and cluster-definer values are source metadata only.')


def require_schema(db, metadata_only=False):
    checks = {c['name']: c['sqltext'] for c in inspect(db.connection()).get_check_constraints('discovery_results')}
    from ..models import DiscoveryResult
    required = next(str(c.sqltext) for c in DiscoveryResult.__table__.constraints if c.name == 'ck_discovery_results_2')
    norm = lambda value: ' '.join(value.split()).lower()
    if norm(checks.get('ck_discovery_results_2', '')) != norm(required) or (not metadata_only and not supports_revision(db.connection(), '20260922_02')):
        raise SchemaUnavailable('GraphSense public annotation storage requires revision 20260922_02.')


class BoundedSafeLoader(yaml.SafeLoader):
    """Safe YAML with finite composition work; no aliases/includes/custom tags."""
    def __init__(self, value):
        super().__init__(value)
        self.depth = 0
        self.nodes = 0

    def compose_node(self, parent, index):
        self.nodes += 1
        if self.check_event(yaml.AliasEvent) or self.depth >= 12 or self.nodes > 20000:
            raise ValueError('Unsupported or excessive YAML structure')
        self.depth += 1
        try:
            return super().compose_node(parent, index)
        finally:
            self.depth -= 1

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError('Non-text or duplicate YAML key')
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def text_field(value, maximum=255):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError('Unsupported tag metadata')
    value = value.strip()
    safe_text(value)
    return value


def parse_pack(content, subject):
    """Only selected exact-address fields survive this boundary; no raw YAML."""
    loader = BoundedSafeLoader(content.decode('utf-8-sig'))
    try:
        pack = loader.get_single_data()
    finally:
        loader.dispose()
    if not isinstance(pack, dict) or not isinstance(pack.get('tags'), list) or 'header' in pack:
        raise ValueError('Unsupported TagPack format')
    if pack.get('is_public') is False:
        raise ValueError('Nonpublic pack')
    title, creator = text_field(pack.get('title')), text_field(pack.get('creator'))
    records = []
    incomplete = False
    currency = {'bitcoin': 'BTC', 'ethereum': 'ETH'}[subject['namespace']]
    for tag in pack['tags']:
        if not isinstance(tag, dict):
            incomplete = True
            continue
        # Address-level entries only; never infer tags from prose or tx hashes.
        address = tag.get('address', pack.get('address'))
        if not isinstance(address, str) or 'tx_hash' in tag or 'tx_hash' in pack:
            continue
        try:
            found = canonical_subject('blockchain_address', subject['namespace'], address)
        except DiscoveryError:
            continue
        if found['canonical_value'] != subject['canonical_value']:
            continue
        values = {**pack, **tag}
        # Upstream defaults a missing network to currency on each header/tag.
        # An explicit tag currency also supplies its missing network override.
        network = tag.get('network', tag.get('currency', pack.get('network', pack.get('currency'))))
        if values.get('currency') != currency or network != currency:
            continue
        try:
            record = {'label': text_field(values.get('label')), 'title': title, 'creator': creator,
                      'currency': currency, 'network': network}
            canonical_subject('annotation', 'graphsense', record['label'])
            source = text_field(values.get('source'), 2048)
            # Upstream permits textual source pointers as well as URLs.
            if re.match(r'(?i)^https?://', source):
                record['source_url'] = safe_url(source)
            record['source'] = source
            for key in ('category', 'confidence', 'actor', 'abuse', 'tag_type'):
                if key in values:
                    record[key] = text_field(values[key])
            if 'concepts' in values:
                if not isinstance(values['concepts'], list) or len(values['concepts']) > 20:
                    raise ValueError('Unsupported concepts')
                record['concepts'] = sorted({text_field(v) for v in values['concepts']})
            if 'is_cluster_definer' in values:
                if type(values['is_cluster_definer']) is not bool:
                    raise ValueError('Unsupported cluster metadata')
                record['is_cluster_definer'] = values['is_cluster_definer']
            if 'lastmod' in values:
                value = values['lastmod']
                if isinstance(value, (date, datetime)):
                    value = value.isoformat()
                record['lastmod'] = text_field(value, 64)
            records.append(clean(record))
        except (ValueError, TypeError):
            incomplete = True
    return records, incomplete


def file_candidate(item):
    if not isinstance(item, dict):return None
    repo = item.get('repository')
    if not isinstance(repo, dict) or repo.get('private') is not False or repo.get('visibility', 'public') != 'public' or repo.get('full_name') != REPOSITORY:
        return None
    path, sha = item.get('path'), item.get('sha')
    if not isinstance(path, str) or not path.startswith('packs/') or len(path) > 400 or '\\' in path or '%' in path or any(part in ('', '.', '..') for part in path.split('/')) or not path.endswith(('.yaml', '.yml')):
        return None
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha):return None
    try:
        text_field(path, 400)
        url = github.github_url(item.get('html_url'), '/' + REPOSITORY + '/blob/')
        location = unquote(urlsplit(url).path)
        prefix = '/' + REPOSITORY + '/blob/'
        if not location.endswith('/' + path):return None
        ref = location[len(prefix):-(len(path) + 1)]
        if not re.fullmatch(r'[a-zA-Z0-9._/-]{1,100}', ref) or any(p in ('', '.', '..') for p in ref.split('/')):return None
    except (DiscoveryError, ValueError):
        return None
    return {'file_path': path, 'blob_sha': sha, 'file_html_url': url, 'ref': ref}


def observation(record, location, subject, retrieved):
    fact = {'provider': 'GraphSense', 'repository': REPOSITORY,
            'path': location['file_path'], 'label': record['label'], 'source': record['source']}
    snapshot = clean({'schema_version': 1, 'provider': 'GraphSense', 'public': True,
        'repository': REPOSITORY, **location, 'wallet': subject['canonical_value'],
        'chain': subject['namespace'], 'tag': record, 'license': 'MIT',
        'verification_method': 'exact_tag_address', 'scope_note': NOTE})
    return {'kind': 'candidate_relationship', 'predicate': 'publicly_labeled_as',
        'from': {'kind': 'blockchain_address', 'namespace': subject['namespace'], 'value': subject['canonical_value']},
        'to': {'kind': 'annotation', 'namespace': 'graphsense', 'value': record['label']},
        'fact_key': fact, 'observation': {'kind': 'verified_page_observation',
            'source_record_key': fingerprint(fact), 'source_url': location['file_html_url'],
            'title': record['label'], 'summary': NOTE, 'verification': 'exact_in_document',
            'match_context': {'matched_wallet': subject['canonical_value'], 'chain': subject['namespace'],
                              'field': 'tags.address', 'verification_method': 'exact_tag_address'},
            'source_class': 'public_annotation', 'retrieved_at': retrieved, 'source_snapshot': snapshot}}


class GraphSenseExecutor:
    async def execute(self, context):
        subject = canonical_subject('blockchain_address', context.subject['namespace'], context.subject['canonical_value'])
        maximum = context.parameters['max_results']
        if type(maximum) is not int or not 1 <= maximum <= 100:
            raise ExecutionSignal('invalid_provider_response')
        data, quota = await github.api_json(context, github.SEARCH_URL, params={
            'q': '"' + subject['canonical_value'] + '" repo:' + REPOSITORY + ' path:packs in:file',
            'per_page': MAX_FILES, 'page': 1})
        if not isinstance(data, dict) or type(data.get('total_count')) is not int or type(data.get('incomplete_results')) is not bool or not isinstance(data.get('items'), list) or len(data['items']) > MAX_FILES or data['total_count'] < len(data['items']):
            raise ExecutionSignal('invalid_provider_response', quota)
        resources = {}
        def retain_quota(value):
            if value.get('remaining') == 0 and not value.get('retry_after_at'):
                value = {**value, 'retry_after_at': datetime.now(timezone.utc) + timedelta(minutes=1)}
            resource = value.get('resource')
            if resource:
                resources[resource] = {k: v for k, v in value.items() if k in ('limit', 'remaining', 'reset_at', 'retry_after_at')}
            return {**value, 'github_resources': dict(resources)}
        quota = retain_quota(quota)
        incomplete = data['incomplete_results']
        limited = data['total_count'] > len(data['items'])
        records, seen_files, seen_material = [], set(), set()
        consumed = result_bytes = 0
        for item in data['items']:
            context.checkpoint()
            if len(records) >= maximum:
                limited = True
                break
            if quota.get('retry_after_at') or quota.get('remaining') == 0:
                incomplete = True
                break
            location = file_candidate(item)
            if not location:
                incomplete = True
                continue
            if location['file_path'] in seen_files:continue
            seen_files.add(location['file_path'])
            try:
                blob, next_quota = await github.api_json(context,
                    'https://api.github.com/repos/' + REPOSITORY + '/git/blobs/' + location['blob_sha'],
                    max_bytes=FILE_BYTES * 4 // 3 + 16384)
                quota = retain_quota(next_quota)
                if not isinstance(blob, dict) or blob.get('sha') != location['blob_sha'] or blob.get('encoding') != 'base64' or type(blob.get('size')) is not int or not 0 <= blob['size'] <= FILE_BYTES or not isinstance(blob.get('content'), str):
                    raise ValueError('Unsupported blob')
                if consumed + blob['size'] > TOTAL_BYTES:
                    limited = True
                    break
                content = base64.b64decode(''.join(blob['content'].split()), validate=True)
                if len(content) != blob['size']:raise ValueError('Inconsistent blob size')
                digest = hashlib.sha1(b'blob ' + str(len(content)).encode('ascii') + b'\0' + content).hexdigest()
                if digest != location['blob_sha']:raise ValueError('Inconsistent blob hash')
                consumed += len(content)
                tags, partial = parse_pack(content, subject)
                incomplete |= partial
                for tag in tags:
                    record = observation(tag, location, subject, datetime.now(timezone.utc))
                    clean(record['observation'])  # Enforce storage bounds before batching.
                    key = fingerprint({'fact': record['fact_key'], 'snapshot': record['observation']['source_snapshot']})
                    if key in seen_material:continue
                    seen_material.add(key)
                    # Inherited metadata can expand a small pack substantially.
                    # Account for the actual validated representation, not YAML size.
                    rendered = Batch(records=[record]).model_dump(mode='json', by_alias=True)['records'][0]
                    size = len(canonical_json(rendered).encode('utf-8')) + 1
                    if len(records) >= maximum or result_bytes + size > RESULT_BYTES:
                        limited = True
                        break
                    result_bytes += size
                    records.append(record)
            except ExecutionSignal as exc:
                # Already obtained observations survive a failed secondary fetch.
                if exc.category in ('configuration_unavailable', 'entitlement_unavailable') and not records:raise
                quota = retain_quota({**quota, **exc.quota.model_dump(exclude_none=True)})
                incomplete = True
                if exc.category != 'invalid_provider_response':break
            except (ValueError, TypeError, UnicodeError, binascii.Error, yaml.YAMLError):
                incomplete = True
            if limited and result_bytes > RESULT_BYTES - 16384:
                break
        coverage = 'provider_incomplete' if incomplete else 'limit_reached' if limited else 'bounded'
        return Batch(records=records, coverage=coverage, provider_total=data['total_count'], quota=quota)


def public_material(result, observation, source, wallet, endpoint):
    """Shared read-only graph/promotion gate for this shipped source contract."""
    s = observation.source_snapshot
    return bool(endpoint and (source.transform_id, source.source_id, source.transform_version, source.source_version) == (TRANSFORM_ID, 'github', 1, 1)
        and (result.kind, result.predicate, observation.kind, observation.verification) == ('candidate_relationship', 'publicly_labeled_as', 'verified_page_observation', 'exact_in_document')
        and (endpoint.kind, endpoint.namespace) == ('annotation', 'graphsense')
        and result.from_subject_id == wallet.id and result.to_subject_id == endpoint.id
        and s.get('provider') == 'GraphSense' and s.get('public') is True and s.get('repository') == REPOSITORY
        and s.get('wallet') == wallet.canonical_value and s.get('chain') == wallet.namespace
        and s.get('tag', {}).get('label') == endpoint.canonical_value
        and s.get('verification_method') == 'exact_tag_address'
        and observation.match_context.get('matched_wallet') == wallet.canonical_value
        and observation.match_context.get('verification_method') == 'exact_tag_address')
