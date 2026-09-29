"""Documented Tavily Basic Search only; fixed host, one request, no URL fetches."""
import asyncio
import json
import os
import httpx
from ..executors import ExecutionSignal


def access_mode():
    if os.getenv('TAVILY_API_KEY', '').strip():
        return 'api_key'
    if os.getenv('TAVILY_KEYLESS_ENABLED', 'true').strip().lower() in ('1', 'true', 'yes'):
        return 'keyless'
    return None


def configured():
    return access_mode() is not None


def failure(diagnostic):
    category = {
        'missing_api_key': 'configuration_unavailable',
        'authentication_failed': 'configuration_unavailable',
        'quota_exhausted': 'budget_exhausted',
        'keyless_allowance_exhausted': 'rate_limited',
        'rate_limited': 'rate_limited', 'provider_timeout': 'timeout',
        'provider_error': 'transport_failed', 'invalid_response': 'invalid_provider_response',
    }[diagnostic]
    return ExecutionSignal(category, {'diagnostic': diagnostic})


class TavilyProvider:
    id = 'tavily_search'

    async def search(self, query, context):
        from .providers import DiscoveryExecutionResult, DiscoveryObservation
        mode = access_mode()
        if mode is None:
            raise failure('missing_api_key')
        limit = min(query.limit, 20)
        headers = {'Accept': 'application/json'}
        if mode == 'api_key':
            headers['Authorization'] = 'Bearer ' + os.environ['TAVILY_API_KEY'].strip()
        else:
            headers['X-Tavily-Access-Mode'] = 'keyless'
        payload = dict(query=query.text, topic='general', search_depth='basic',
                       auto_parameters=False, exact_match=True, max_results=limit,
                       include_answer=False, include_raw_content=False,
                       include_images=False, include_image_descriptions=False,
                       include_favicon=False)

        async def request():
            async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
                async with client.stream('POST', 'https://api.tavily.com/search',
                                         json=payload, headers=headers) as response:
                    status = response.status_code
                    # Never retain upstream error messages, which may echo credentials.
                    if mode == 'keyless' and status in (429, 432, 433):
                        raise failure('keyless_allowance_exhausted')
                    if status in (401, 403):
                        raise failure('authentication_failed')
                    if status in (432, 433):
                        raise failure('quota_exhausted')
                    if status == 429:
                        raise failure('rate_limited')
                    if status != 200:
                        raise failure('provider_error')
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        context.checkpoint()
                        body.extend(chunk)
                        if len(body) > 1048576:
                            raise failure('invalid_response')
                    try:
                        data = json.loads(body)
                    except (ValueError, RecursionError):
                        raise failure('invalid_response') from None
                    if not isinstance(data, dict) or not isinstance(data.get('results'), list):
                        raise failure('invalid_response')
                    return data
        try:
            data = await context.request(request)
        except (httpx.TimeoutException, asyncio.TimeoutError):
            raise failure('provider_timeout') from None
        except httpx.HTTPError:
            raise failure('provider_error') from None
        rows = data['results']
        result = DiscoveryExecutionResult(metadata={'access_mode': mode, 'search_depth': 'basic',
            'request_limit': 1, 'provider_result_limit': 20, 'retained_content': 'bounded search metadata only'})
        for rank, row in enumerate(rows[:limit], 1):
            if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ('url', 'title', 'content')):
                raise failure('invalid_response')
            result.observations.append(DiscoveryObservation(row['url'], row['title'], row['content'], rank))
        # Search does not advertise a total or a continuation cursor. Hitting the
        # requested cap is bounded/incomplete coverage, never exhaustive results.
        result.truncated = len(rows) >= limit
        result.reason = 'result_cap' if result.truncated else None
        return result
