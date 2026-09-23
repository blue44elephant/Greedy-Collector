"""Bounded public code mentions. No database access or secondary URL fetching."""
from ..chains import get_chain_adapter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import math
import os
import re
from urllib.parse import urlsplit

import httpx

from .domain import canonical_subject, clean, public_url, DiscoveryError
from .executors import ExecutionSignal
from .schemas import Batch

API_VERSION = '2026-03-10'
SEARCH_URL = 'https://api.github.com/search/code'
MAX_RESULTS = 30
MAX_BYTES = 1048576
EXCERPT_CHARS = 1000


def quota_headers(headers):
    """Keep only typed quota data, never raw headers or authentication data."""
    quota = {}
    for header, field in [('x-ratelimit-remaining', 'remaining'), ('x-ratelimit-limit', 'limit')]:
        value = headers.get(header, '')
        if re.fullmatch(r'[0-9]{1,9}', value):
            quota[field] = int(value)
    resource = headers.get('x-ratelimit-resource')
    if resource in ('code_search', 'search', 'core'):
        quota['resource'] = resource
    try:
        value = headers.get('x-ratelimit-reset', '')
        if re.fullmatch(r'[0-9]{1,11}', value):
            quota['reset_at'] = datetime.fromtimestamp(int(value), timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    value = headers.get('retry-after', '')
    try:
        if re.fullmatch(r'[0-9]{1,8}', value):
            quota['retry_after_at'] = datetime.now(timezone.utc) + timedelta(seconds=int(value))
        elif value:
            quota['retry_after_at'] = parsedate_to_datetime(value).astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        pass
    if quota.get('remaining') == 0 and 'reset_at' in quota:
        quota['retry_after_at'] = max(quota.get('retry_after_at', quota['reset_at']), quota['reset_at'])
    return quota


def github_url(value, prefix):
    value = public_url(value)
    parts = urlsplit(value)
    if parts.scheme != 'https' or parts.netloc != 'github.com' or parts.query or parts.fragment:
        raise DiscoveryError('Unsupported GitHub citation')
    if not parts.path.startswith(prefix):
        raise DiscoveryError('Inconsistent GitHub citation')
    return value


def exact_fragment(item, subject):
    address = subject['canonical_value']
    flags = re.IGNORECASE if get_chain_adapter(subject['namespace']).address_case_insensitive(address) else 0
    # Case folding is ASCII-only inside the address; surrounding boundaries
    # remain Unicode-aware so adjoining identifiers cannot become false hits.
    pattern = re.compile(r'(?<![\w])(?a:' + re.escape(address) + r')(?![\w])', flags)
    matches = item.get('text_matches', [])
    if not isinstance(matches, list):
        return None
    for match in matches:
        if not isinstance(match, dict) or match.get('property') != 'content':
            continue
        fragment = match.get('fragment')
        if not isinstance(fragment, str):
            continue
        found = pattern.search(fragment)
        if not found:
            continue
        start = max(0, found.start() - (EXCERPT_CHARS - len(address)) // 2)
        excerpt = fragment[start:start + EXCERPT_CHARS]
        # Drop obvious credential assignments/tokens incidentally present in a
        # fragment. Never inspect other files or harvest credentials.
        excerpt = re.sub(r'(?i)\b(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*[\"\']?[^\s\"\';,]+', '[redacted]', excerpt)
        excerpt = re.sub(r'\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)\b', '[redacted]', excerpt)
        excerpt = clean(excerpt)
        safe_match = pattern.search(excerpt)
        if safe_match:
            return excerpt, {'property': 'content', 'matched_wallet': address,
                'matched_text': safe_match.group(), 'excerpt_start': safe_match.start(),
                'excerpt_end': safe_match.end(), 'provider_fragment_match_start': found.start(),
                'provider_fragment_match_end': found.end()}
    return None


def candidate(item, subject, incomplete, retrieved):
    if not isinstance(item, dict):
        raise ExecutionSignal('invalid_provider_response')
    repo = item.get('repository')
    # Fail closed BEFORE reading fragments: false is required, not truthiness.
    if not isinstance(repo, dict) or repo.get('private') is not False or repo.get('visibility', 'public') != 'public':
        return None
    rid, name, path = repo.get('id'), repo.get('full_name'), item.get('path')
    if type(rid) is not int or not 0 < rid < 10**20 or not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', name):
        return None
    if not isinstance(path, str) or not path or len(path) > 480 or any(ord(c) < 32 for c in path):
        return None
    try:
        repo_url = github_url(repo.get('html_url'), '/' + name)
        if urlsplit(repo_url).path.rstrip('/') != '/' + name:
            return None
        file_url = github_url(item.get('html_url'), '/' + name + '/blob/')
        # Reject altered identifiers rather than silently changing location identity.
        if clean(name) != name or clean(path) != path:
            return None
        context = exact_fragment(item, subject)
    except DiscoveryError:
        return None
    if not context:
        return None
    excerpt, match = context
    snapshot = {'schema_version': 1, 'public': True, 'repository_id': rid,
        'repository_full_name': name, 'repository_url': repo_url, 'file_path': path,
        'file_html_url': file_url, 'incomplete_results': incomplete, 'api_version': API_VERSION}
    if isinstance(item.get('name'), str):
        snapshot['file_name'] = clean(item['name'][:255])
    if isinstance(item.get('sha'), str) and re.fullmatch(r'[0-9a-fA-F]{40,64}', item['sha']):
        snapshot['blob_sha'] = item['sha']
    if type(repo.get('fork')) is bool:
        snapshot['fork'] = repo['fork']
    score = item.get('score')
    if type(score) in (int, float) and math.isfinite(score):
        snapshot['github_search_score'] = score
    return {'kind': 'candidate_relationship', 'predicate': 'repository_contains',
        'from': {'kind': 'repository', 'namespace': 'github', 'value': str(rid)},
        'to': {'kind': 'blockchain_address', 'namespace': subject['namespace'], 'value': subject['canonical_value']},
        'fact_key': {'path': path}, 'observation': {
            'kind': 'code_search_result', 'source_record_key': str(rid) + ':' + path,
            'source_url': file_url, 'title': name[:255],
            'summary': 'Full wallet identifier in a returned public code fragment. A mention does not establish wallet ownership or control.',
            'excerpt': excerpt, 'excerpt_complete': False, 'verification': 'exact_in_excerpt',
            'match_context': match, 'source_class': 'public_code', 'retrieved_at': retrieved,
            'source_snapshot': snapshot}}


async def api_json(context, url, *, params=None, max_bytes=MAX_BYTES, accept='application/vnd.github+json'):
    """Shared charged GitHub API transport. Callers own fixed endpoint allowlists."""
    if not url.startswith('https://api.github.com/'):
        raise ExecutionSignal('invalid_provider_response')
    token = os.getenv('DISCOVERY_GITHUB_TOKEN', '').strip()
    if not token:raise ExecutionSignal('configuration_unavailable')
    async def request():
        headers = {'Accept': accept,
            'X-GitHub-Api-Version': API_VERSION, 'Authorization': 'Bearer ' + token,
            'User-Agent': 'Greedy-Collector'}
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
            async with client.stream('GET', url, params=params, headers=headers) as response:
                quota = quota_headers(response.headers)
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    context.checkpoint()
                    if len(body) + len(chunk) > max_bytes:
                        raise ExecutionSignal('invalid_provider_response', quota)
                    body.extend(chunk)
                status = response.status_code
                # Error text is used only for classifying documented secondary
                # limits; never saved, logged or returned to the client.
                secondary = False
                if status == 403:
                    try:
                        error = json.loads(body)
                        message = error.get('message', '') if isinstance(error, dict) else ''
                        secondary = isinstance(message, str) and 'rate limit' in message.lower()
                    except (ValueError, UnicodeError):
                        pass
                if status == 429 or status == 403 and (quota.get('remaining') == 0 or 'retry_after_at' in quota or secondary):
                    quota.setdefault('retry_after_at', datetime.now(timezone.utc) + timedelta(minutes=1))
                    raise ExecutionSignal('rate_limited', quota)
                if status != 200:
                    category = 'configuration_unavailable' if status == 401 else 'entitlement_unavailable' if status == 403 else 'transport_failed' if status >= 500 else 'invalid_provider_response'
                    raise ExecutionSignal(category, quota)
                try:
                    data = json.loads(body)
                except (ValueError, UnicodeError):
                    raise ExecutionSignal('invalid_provider_response', quota) from None
                return data, quota

    try:
        return await context.request(request)
    except httpx.TimeoutException:
        raise ExecutionSignal('timeout') from None
    except httpx.HTTPError:
        raise ExecutionSignal('transport_failed') from None


class GitHubCodeExecutor:
    async def execute(self, context):
        subject = canonical_subject('blockchain_address', context.subject['namespace'], context.subject['canonical_value'])
        maximum = context.parameters['max_results']
        if type(maximum) is not int or not 1 <= maximum <= MAX_RESULTS:
            raise ExecutionSignal('invalid_provider_response')
        token = os.getenv('DISCOVERY_GITHUB_TOKEN', '').strip()
        if not token:
            raise ExecutionSignal('configuration_unavailable')

        params = {'q': '"' + subject['canonical_value'] + '" in:file', 'per_page': maximum, 'page': 1}
        data, quota = await api_json(context, SEARCH_URL, params=params, accept='application/vnd.github.text-match+json')
        if not isinstance(data, dict) or type(data.get('total_count')) is not int or data['total_count'] < 0 or type(data.get('incomplete_results')) is not bool or not isinstance(data.get('items'), list) or len(data['items']) > maximum or data['total_count'] < len(data['items']):
            raise ExecutionSignal('invalid_provider_response', quota)
        records, seen = [], set()
        retrieved = datetime.now(timezone.utc)
        for item in data['items']:
            context.checkpoint()
            record = candidate(item, subject, data['incomplete_results'], retrieved)
            if record:
                key = (record['from']['value'], record['fact_key']['path'])
                if key not in seen:
                    seen.add(key)
                    records.append(record)
        coverage = 'provider_incomplete' if data['incomplete_results'] else 'limit_reached' if data['total_count'] > len(data['items']) else 'bounded'
        return Batch.model_validate({'records': records, 'coverage': coverage, 'provider_total': data['total_count'], 'quota': quota}).model_dump(mode='json', by_alias=True)
