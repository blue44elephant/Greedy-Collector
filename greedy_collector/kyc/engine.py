import asyncio
from difflib import SequenceMatcher
import logging
from urllib.parse import quote_plus

import httpx

from ..config import get_settings
from ..schemas import KycQuery
from .sources import SOURCE_CATALOG

logger = logging.getLogger("GreedyCollector.KYC")


class KycScreeningEngine:
    def __init__(self):
        self.settings = get_settings()

    async def screen(self, query: KycQuery) -> dict:
        source_ids = ["opensanctions", "interpol", "sec_edgar", "gdelt"]
        tasks = [
            self._opensanctions(query),
            self._interpol(query),
            self._sec_edgar(query),
            self._gdelt(query),
        ]
        if query.domain:
            source_ids.extend(["crtsh", "urlscan", "virustotal"])
            tasks.extend(
                [
                    self._crtsh(query.domain),
                    self._urlscan(query.domain),
                    self._virustotal(query.domain),
                ]
            )
        batches = await asyncio.gather(*tasks, return_exceptions=True)
        matches, checked, unavailable = [], [], []
        for source_id, batch in zip(source_ids, batches):
            if isinstance(batch, Exception):
                logger.warning("KYC source failed: %s", source_id)
                batch = self._unavailable(source_id, "Source unavailable")
            matches.extend(batch.get("matches", []))
            target = checked if batch.get("checked") else unavailable
            target.append(
                {
                    "id": batch["source"],
                    "reason": batch.get("reason", ""),
                }
            )

        manual = []
        if query.include_manual_sources:
            manual = [
                self._manual_source(source, query)
                for source in SOURCE_CATALOG
                if source.mode == "manual"
            ]
        return {
            "query": query.model_dump() if hasattr(query, "model_dump") else query.dict(),
            "matches": sorted(matches, key=lambda item: item["match_score"], reverse=True),
            "checked_sources": checked,
            "unavailable_sources": unavailable,
            "manual_sources": manual,
            "disclaimer": (
                "Results are possible public-record matches for analyst review. A name "
                "match does not establish identity, wrongdoing, or wallet ownership."
            ),
        }

    async def _request(self, url: str, *, params=None, headers=None, auth=None):
        merged_headers = {"User-Agent": "Greedy-Collector/0.1 research"}
        merged_headers.update(headers or {})
        async with httpx.AsyncClient(
            timeout=self.settings.request_timeout, follow_redirects=True
        ) as client:
            response = await client.get(
                url, params=params, headers=merged_headers, auth=auth
            )
            response.raise_for_status()
            return response.json()

    async def _opensanctions(self, query: KycQuery) -> dict:
        source = "opensanctions"
        if not self.settings.opensanctions_api_key:
            return self._unavailable(source, "OPENSANCTIONS_API_KEY is not configured")
        try:
            data = await self._request(
                "https://api.opensanctions.org/search/default",
                params={"q": query.name, "limit": 20},
                headers={"Authorization": f"ApiKey {self.settings.opensanctions_api_key}"},
            )
            rows = data.get("results", [])
            return self._checked(
                source,
                [
                    self._match(
                        source,
                        row.get("caption", ""),
                        query.name,
                        f"OpenSanctions search returned entity schema {row.get('schema', 'unknown')}.",
                        f"https://www.opensanctions.org/entities/{row.get('id', '')}/",
                        row.get("datasets", []),
                        row,
                    )
                    for row in rows
                ],
            )
        except Exception as exc:
            return self._unavailable(source, str(exc))

    async def _interpol(self, query: KycQuery) -> dict:
        source = "interpol"
        parts = query.name.rsplit(" ", 1)
        params = {"resultPerPage": 20}
        if len(parts) == 2:
            params.update({"forename": parts[0], "name": parts[1]})
        else:
            params["name"] = query.name
        try:
            data = await self._request(
                "https://ws-public.interpol.int/notices/v1/red", params=params
            )
            rows = data.get("_embedded", {}).get("notices", [])
            matches = []
            for row in rows:
                subject = " ".join(
                    part for part in [row.get("forename"), row.get("name")] if part
                )
                matches.append(
                    self._match(
                        source,
                        subject,
                        query.name,
                        "INTERPOL public Red Notice name result; verify notice details and identifiers.",
                        row.get("_links", {}).get("self", {}).get("href", ""),
                        ["public_notice"],
                        row,
                    )
                )
            return self._checked(source, matches)
        except Exception as exc:
            return self._unavailable(source, str(exc))

    async def _sec_edgar(self, query: KycQuery) -> dict:
        source = "sec_edgar"
        try:
            data = await self._request(
                "https://www.sec.gov/files/company_tickers.json",
                headers={"User-Agent": self.settings.sec_user_agent},
            )
            matches = []
            for row in data.values():
                title = row.get("title", "")
                score = self._similarity(title, query.name)
                if score >= 0.7:
                    cik = str(row.get("cik_str", "")).zfill(10)
                    matches.append(
                        self._match(
                            source,
                            title,
                            query.name,
                            "SEC registrant name is similar to the submitted name.",
                            f"https://www.sec.gov/edgar/browse/?CIK={cik}",
                            ["sec_registrant"],
                            row,
                        )
                    )
            return self._checked(source, matches[:20])
        except Exception as exc:
            return self._unavailable(source, str(exc))

    async def _gdelt(self, query: KycQuery) -> dict:
        source = "gdelt"
        try:
            data = await self._request(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params={
                    "query": f'"{query.name}"',
                    "mode": "artlist",
                    "format": "json",
                    "maxrecords": 20,
                },
            )
            matches = [
                self._match(
                    source,
                    row.get("title", query.name),
                    query.name,
                    "GDELT indexed an article containing the submitted name.",
                    row.get("url", ""),
                    ["news_mention"],
                    row,
                )
                for row in data.get("articles", [])
            ]
            return self._checked(source, matches)
        except Exception as exc:
            return self._unavailable(source, str(exc))

    async def _crtsh(self, domain: str) -> dict:
        source = "crtsh"
        try:
            rows = await self._request(
                "https://crt.sh/", params={"q": f"%.{domain}", "output": "json"}
            )
            unique = {}
            for row in rows:
                name = row.get("name_value", "")
                unique[name] = self._match(
                    source,
                    name,
                    domain,
                    "Certificate Transparency contains a certificate name for the domain.",
                    f"https://crt.sh/?id={row.get('id', '')}",
                    ["certificate"],
                    row,
                )
            return self._checked(source, list(unique.values())[:50])
        except Exception as exc:
            return self._unavailable(source, str(exc))

    async def _urlscan(self, domain: str) -> dict:
        source = "urlscan"
        try:
            headers = (
                {"api-key": self.settings.urlscan_api_key}
                if self.settings.urlscan_api_key
                else {}
            )
            data = await self._request(
                "https://urlscan.io/api/v1/search/",
                params={"q": f"domain:{domain}", "size": 20},
                headers=headers,
            )
            return self._checked(
                source,
                [
                    self._match(
                        source,
                        row.get("page", {}).get("domain", domain),
                        domain,
                        "urlscan.io has a public scan associated with this domain.",
                        row.get("result", ""),
                        ["domain_scan"],
                        row,
                    )
                    for row in data.get("results", [])
                ],
            )
        except Exception as exc:
            return self._unavailable(source, str(exc))

    async def _virustotal(self, domain: str) -> dict:
        source = "virustotal"
        if not self.settings.virustotal_api_key:
            return self._unavailable(source, "VIRUSTOTAL_API_KEY is not configured")
        try:
            data = await self._request(
                f"https://www.virustotal.com/api/v3/domains/{quote_plus(domain)}",
                headers={"x-apikey": self.settings.virustotal_api_key},
            )
            attributes = data.get("data", {}).get("attributes", {})
            return self._checked(
                source,
                [
                    self._match(
                        source,
                        domain,
                        domain,
                        "VirusTotal returned public domain reputation metadata.",
                        f"https://www.virustotal.com/gui/domain/{quote_plus(domain)}",
                        ["domain_reputation"],
                        attributes,
                    )
                ],
            )
        except Exception as exc:
            return self._unavailable(source, str(exc))

    def _manual_source(self, source, query: KycQuery) -> dict:
        term = query.domain if source.category in {"domain", "network"} and query.domain else query.name
        return {
            "id": source.id,
            "name": source.name,
            "category": source.category,
            "url": source.search_url.format(query=quote_plus(term)),
            "note": source.note or "Open the official source and document analyst review.",
        }

    def _match(
        self,
        source: str,
        subject: str,
        query: str,
        rationale: str,
        url: str,
        categories: list,
        data: dict,
    ) -> dict:
        return {
            "source": source,
            "subject_name": subject,
            "match_score": self._similarity(subject, query),
            "match_rationale": rationale,
            "source_url": url,
            "categories": categories,
            "source_data": data,
            "review_status": "Unreviewed",
        }

    @staticmethod
    def _similarity(left: str, right: str) -> float:
        return round(SequenceMatcher(None, left.casefold(), right.casefold()).ratio(), 3)

    @staticmethod
    def _checked(source: str, matches: list) -> dict:
        return {"source": source, "checked": True, "matches": matches}

    @staticmethod
    def _unavailable(source: str, reason: str) -> dict:
        safe_reason = "Optional API_KEY is not configured" if "API_KEY is not configured" in reason else "Source unavailable. Check server configuration or try again later."
        return {"source": source, "checked": False, "reason": safe_reason, "matches": []}
