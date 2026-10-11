"""OFAC SDN XML adapter. No download happens during import or wallet screening."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit
import requests
from ..chains import get_chain_adapter

SOURCE_ID = 'ofac_sdn'
SOURCE_URL = 'https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML'
NAMESPACE = 'https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/XML'
PARSER_VERSION = 'sdn-xml-2024-v1'
MAX_BYTES = 80 * 1024 * 1024
OFAC_BUCKET = 'wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com'
ALLOWED_HOSTS = frozenset({'sanctionslistservice.ofac.treas.gov', 'sanctionslist.ofac.treas.gov', 'ofac.treasury.gov', OFAC_BUCKET})
FIELD = re.compile(r'^Digital Currency Address - ([A-Za-z0-9_. -]{1,60})$')
EXPLICIT = {'XBT':'bitcoin','BTC':'bitcoin','ETH':'ethereum','LTC':'litecoin',
            'TRX':'tron','SOL':'solana','XMR':'monero',
            'BASE':'base','ARB':'arbitrum','ARBITRUM':'arbitrum','BSC':'bsc','POL':'polygon'}
AMBIGUOUS = {'USDT','USDC','DAI','WETH','TOKEN'}

class SanctionsError(ValueError):
    def __init__(self, category):
        self.category = category
        super().__init__(category)

@dataclass(frozen=True)
class ParsedSource:
    entities: tuple[dict, ...]
    identifiers: tuple[dict, ...]
    published_at: str | None
    sha256: str


def text_key(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r'0x[0-9a-fA-F]{40}', value) or value.lower().startswith('bc1'):
        return value.lower()
    return value


def map_identifier(asset: str, value: str) -> tuple[str | None, str | None, str]:
    chain = EXPLICIT.get(asset.upper())
    if chain is None:
        return None, None, 'ambiguous_asset' if asset.upper() in AMBIGUOUS else 'unsupported_asset'
    try:
        canonical = get_chain_adapter(chain).normalize_address(value)
    except (ValueError, TypeError):
        return chain, None, 'invalid_address'
    return chain, canonical, 'mapped'


def _text(node, path: str) -> str:
    child = node.find(path)
    return ''.join(child.itertext()).strip() if child is not None else ''


def parse_sdn_xml(data: bytes, *, minimum_entities: int = 5000) -> ParsedSource:
    if not data or len(data) > MAX_BYTES:
        raise SanctionsError('validation_failed')
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise SanctionsError('unsupported_schema')
    ns = '{' + NAMESPACE + '}'
    try:
        root = ET.parse(BytesIO(data)).getroot()
    except (ET.ParseError, UnicodeError, ValueError):
        raise SanctionsError('parse_error') from None
    if root.tag != ns + 'sdnList' or root.find(ns+'sdnEntry') is None:
        raise SanctionsError('unsupported_schema')
    publish = (_text(root, ns+'publshInformation/'+ns+'publishDate') or
               _text(root, ns+'publishInformation/'+ns+'publishDate')) or None
    entities, identifiers, seen = [], [], set()
    for entry in root.findall(ns+'sdnEntry'):
        uid = _text(entry, ns+'uid')
        name = ' '.join(part for part in (_text(entry, ns+'firstName'), _text(entry, ns+'lastName')) if part)
        if not uid or not name or uid in seen:
            raise SanctionsError('validation_failed')
        seen.add(uid)
        programs = sorted(set(filter(None, (_text(n,'.') for n in entry.findall(ns+'programList/'+ns+'program')))))
        aliases=[]
        for aka in entry.findall(ns+'akaList/'+ns+'aka'):
            alias=' '.join(part for part in (_text(aka,ns+'firstName'),_text(aka,ns+'lastName')) if part)
            if alias: aliases.append({'name':alias,'type':_text(aka,ns+'type')})
        entities.append({'source_entity_id':uid,'name':name,'entity_type':_text(entry,ns+'sdnType') or None,
                         'programs':programs,'aliases':aliases,'remarks':_text(entry,ns+'remarks') or None})
        for item in entry.findall(ns+'idList/'+ns+'id'):
            field, raw = _text(item,ns+'idType'), _text(item,ns+'idNumber')
            match = FIELD.fullmatch(field)
            if not match: continue
            if not raw or len(raw)>512: raise SanctionsError('validation_failed')
            asset=match.group(1).strip()
            chain, canonical, status = map_identifier(asset,raw)
            identifiers.append({'source_entity_id':uid,'source_field':field,'source_asset':asset,
                                'raw_value':raw,'text_key':text_key(raw),'chain':chain,
                                'canonical_address':canonical,'mapping_status':status})
    if len(entities) < minimum_entities or not identifiers:
        raise SanctionsError('validation_failed')
    if len({(i['source_entity_id'],i['source_field'],i['raw_value']) for i in identifiers}) != len(identifiers):
        raise SanctionsError('validation_failed')
    return ParsedSource(tuple(entities),tuple(identifiers),publish,sha256(data).hexdigest())


class OfacSdnSource:
    source_id = SOURCE_ID
    url = SOURCE_URL
    parser_version = PARSER_VERSION

    def fetch(self) -> tuple[bytes, str | None]:
        """Bounded HTTPS fetch; redirects stay on reviewed Treasury/OFAC hosts."""
        url=self.url
        try:
            with requests.Session() as client:
                for _ in range(3):
                    parsed=urlsplit(url)
                    if parsed.scheme!='https' or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password:
                        raise SanctionsError('source_unavailable')
                    if parsed.hostname==OFAC_BUCKET and (not parsed.path.startswith('/Published/') or not parsed.path.lower().endswith('/sdn.xml')):
                        raise SanctionsError('source_unavailable')
                    with client.get(url,stream=True,timeout=(10,40),allow_redirects=False,
                                    headers={'User-Agent':'Greedy-Collector/1.0 (OFAC SDN sync)','Accept-Encoding':'identity'}) as response:
                        if response.status_code in (301,302,303,307,308):
                            location=response.headers.get('Location')
                            if not location: raise SanctionsError('source_unavailable')
                            url=urljoin(url,location)
                            continue
                        if response.status_code!=200: raise SanctionsError('http_error')
                        chunks=bytearray()
                        for part in response.iter_content(65536):
                            chunks.extend(part)
                            if len(chunks)>MAX_BYTES: raise SanctionsError('validation_failed')
                        length=response.headers.get('Content-Length')
                        if length and int(length)!=len(chunks): raise SanctionsError('validation_failed')
                        return bytes(chunks), None
        except requests.Timeout:
            raise SanctionsError('timeout') from None
        except requests.RequestException:
            raise SanctionsError('network_error') from None
        raise SanctionsError('source_unavailable')

    def parse(self, data: bytes) -> ParsedSource:
        return parse_sdn_xml(data)
