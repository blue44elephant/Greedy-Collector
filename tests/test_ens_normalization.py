"""ED-8A1: real local dependency, blocked networks, isolated storage only."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from time import monotonic

import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from greedy_collector.discovery import ens_normalization as ens
from greedy_collector.discovery.domain import canonical_ens_subject, canonical_subject, result_identity, DiscoveryError
from greedy_collector.discovery.registry import REGISTRY
from greedy_collector.discovery.service import DiscoveryService
from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.models import Base, DiscoverySubject

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / 'tests' / 'ens_no_network.mjs'
CORPUS = json.loads((ROOT / 'tests/fixtures/ens_normalization_vectors.json').read_text(encoding='utf-8'))
VECTORS = CORPUS['vectors']


@pytest.fixture(autouse=True)
def isolated_network(monkeypatch):
    original_resolver = ens._node_executable
    def blocked(*args, **kwargs):
        raise AssertionError('ENS normalizer attempted network')
    for target in ('httpx.HTTPTransport.handle_request', 'httpx.AsyncHTTPTransport.handle_async_request',
                   'requests.Session.request', 'socket.create_connection', 'socket.getaddrinfo'):
        monkeypatch.setattr(target, blocked)
    original_connect = socket.socket.connect
    def connect(sock, address):
        # Windows asyncio socketpair uses loopback internally for TestClient.
        if isinstance(address, tuple) and address[0] in ('127.0.0.1', '::1'):
            return original_connect(sock, address)
        return blocked()
    monkeypatch.setattr(socket.socket, 'connect', connect)
    monkeypatch.setattr(ens, '_NODE_FLAGS', (*ens._NODE_FLAGS, '--import', GUARD.as_uri()))
    ens._probe.cache_clear()
    yield
    ens._probe.cache_clear()
    original_resolver.cache_clear()


def failure(call, category):
    with pytest.raises(ens.EnsNormalizationError) as caught:
        call()
    error = caught.value
    assert error.error_type == category
    assert str(error) == ens._MESSAGES[category]
    assert str(ROOT) not in str(error) and 'node_modules' not in str(error)
    return error


@pytest.mark.parametrize('vector', VECTORS, ids=lambda v: str(v['index']) + '-' + v.get('comment', 'emoji'))
def test_official_vectors_through_real_bridge(vector):
    if vector.get('error') or not vector['name']:
        failure(lambda: ens.normalize_ens_name(vector['name']), 'invalid_ens_name')
    else:
        assert ens.normalize_ens_name(vector['name']) == vector.get('norm', vector['name'])


def test_cross_check_direct_library_without_python_unicode_mutation():
    # Fixed test code, names through stdin. Direct local library, not the helper.
    code = """
import {ens_normalize} from './node_modules/@adraffy/ens-normalize/dist/index.mjs';
let data = ''; for await (const chunk of process.stdin) data += chunk;
console.log(JSON.stringify(JSON.parse(data).map(name => {
  try { return {normalized:ens_normalize(name)}; } catch { return {error:true}; }
})));
"""
    result = subprocess.run([ens._node_executable(), '--import', GUARD.as_uri(), '--input-type=module', '-e', code],
        cwd=ROOT, env=ens._environment(), input=json.dumps([v['name'] for v in VECTORS]),
        encoding='utf-8', capture_output=True, timeout=5, shell=False)
    assert result.returncode == 0 and result.stderr == ''
    actual = json.loads(result.stdout)
    for vector, direct in zip(VECTORS, actual, strict=True):
        if not vector['name']:  # Explicit GC endpoint restriction, not an ENS rule.
            assert direct == {'normalized': ''}
        elif direct.get('error'):
            failure(lambda: ens.normalize_ens_name(vector['name']), 'invalid_ens_name')
        else:
            assert ens.normalize_ens_name(vector['name']) == direct['normalized']
    # casefold() would corrupt these already canonical reference outputs.
    assert ens.normalize_ens_name('\u00df') == '\u00df'
    assert ens.normalize_ens_name('\u03c2') == '\u03c2'


def test_official_docs_example_and_concurrent_determinism():
    raw = 'RaFFY\U0001f6b4\u200d\u2642\ufe0f.eTh'
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(ens.normalize_ens_name, [raw] * 8)) == ['raffy\U0001f6b4\u200d\u2642.eth'] * 8
    assert ens.normalize_ens_name('NaMe.EtH') == 'name.eth'


@pytest.mark.parametrize('value', [None, 4, '', 'a' * 2049, '\U0001f980' * 513, '\ud800'])
def test_rejected_before_spawn(monkeypatch, value):
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid or over-limit input spawned Node')
    monkeypatch.setattr(ens.subprocess, 'Popen', forbidden)
    failure(lambda: ens.normalize_ens_name(value), 'invalid_ens_name')


@pytest.mark.parametrize('value', ['x\x00.eth', 'x\n.eth', 'x\r.eth', 'x\t.eth',
                                  '$(echo pwned).eth', '`echo pwned`.eth', '";whoami;&.eth'])
def test_control_and_shell_text_are_input_only(monkeypatch, value):
    popen = subprocess.Popen
    seen = []
    def capture(argv, **kwargs):
        assert value not in argv
        assert kwargs['shell'] is False
        assert Path(argv[0]).is_absolute() and argv[-1] == str(ens._HELPER)
        assert kwargs['stdin'] == kwargs['stdout'] == kwargs['stderr'] == subprocess.PIPE
        seen.append(argv)
        return popen(argv, **kwargs)
    monkeypatch.setattr(ens.subprocess, 'Popen', capture)
    failure(lambda: ens.normalize_ens_name(value), 'invalid_ens_name')
    assert len(seen) == 1


def test_no_temp_file_or_inherited_secrets(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Normalization attempted a temporary file')
    for key in ('ALCHEMY_API_KEY', 'ETHERSCAN_API_KEY', 'DISCOVERY_GITHUB_TOKEN',
                'OPENSANCTIONS_API_KEY', 'NODE_OPTIONS', 'NODE_PATH', 'HOME', 'NPM_CONFIG_CACHE'):
        monkeypatch.setenv(key, 'private-test-sentinel')
    for target in ('tempfile.TemporaryFile', 'tempfile.NamedTemporaryFile', 'tempfile.mkstemp'):
        monkeypatch.setattr(target, forbidden)
    popen = subprocess.Popen
    def capture(argv, **kwargs):
        assert set(kwargs['env']) <= {'SystemRoot', 'WINDIR'}
        assert 'private-test-sentinel' not in json.dumps(kwargs['env'])
        return popen(argv, **kwargs)
    monkeypatch.setattr(ens.subprocess, 'Popen', capture)
    assert ens.normalize_ens_name('NAME.eth') == 'name.eth'


def test_missing_node_is_safe_and_probe_cached(monkeypatch):
    ens._node_executable.cache_clear()
    monkeypatch.setattr(os, 'get_exec_path', lambda: [])
    failure(lambda: ens.normalize_ens_name('name.eth'), 'normalizer_unavailable')
    cap = ens.probe_ens_normalizer()
    assert not cap.usable and cap.error_type == 'normalizer_unavailable'
    assert cap == ens.probe_ens_normalizer()
    assert str(ROOT) not in json.dumps(asdict(cap))


def test_probe_once_and_explicit_refresh(monkeypatch):
    run = ens._run
    calls = []
    def count(payload):
        calls.append(payload)
        return run(payload)
    monkeypatch.setattr(ens, '_run', count)
    assert ens.probe_ens_normalizer().usable
    assert ens.probe_ens_normalizer().version == '1.11.1'
    assert len(calls) == 1
    assert ens.probe_ens_normalizer(refresh=True).usable
    assert len(calls) == 2


@pytest.fixture
def isolated_helper(tmp_path, monkeypatch):
    root = tmp_path / 'application'
    (root / 'scripts').mkdir(parents=True)
    helper = root / 'scripts' / 'ens_normalize.mjs'
    shutil.copyfile(ens._HELPER, helper)
    monkeypatch.setattr(ens, '_ROOT', root)
    monkeypatch.setattr(ens, '_HELPER', helper)
    return root, helper


def test_local_dependency_missing_does_not_search_parent(isolated_helper):
    root, _ = isolated_helper
    # Real dependency in a parent location, where bare-import resolution would find it.
    parent_package = root.parent / 'node_modules' / '@adraffy' / 'ens-normalize'
    shutil.copytree(ROOT / 'node_modules/@adraffy/ens-normalize', parent_package)
    failure(lambda: ens.normalize_ens_name('name.eth'), 'normalizer_unavailable')
    cap = ens.probe_ens_normalizer()
    assert not cap.installed and not cap.usable


@pytest.mark.parametrize('tamper', ['installed', 'manifest', 'lock', 'runtime_dependency'])
def test_version_and_local_manifest_mismatch(isolated_helper, tamper):
    root, _ = isolated_helper
    package = root / 'node_modules/@adraffy/ens-normalize'
    shutil.copytree(ROOT / 'node_modules/@adraffy/ens-normalize', package)
    for filename in ('package.json', 'package-lock.json'):
        shutil.copyfile(ROOT / filename, root / filename)
    filename = package / 'package.json' if tamper in ('installed', 'runtime_dependency') else root / ('package.json' if tamper == 'manifest' else 'package-lock.json')
    data = json.loads(filename.read_text())
    if tamper == 'installed': data['version'] = '0.0.0'
    elif tamper == 'runtime_dependency': data['dependencies'] = {'unexpected': '1.0.0'}
    elif tamper == 'manifest': data['dependencies']['@adraffy/ens-normalize'] = '^1.11.1'
    else: data['packages']['node_modules/@adraffy/ens-normalize']['version'] = '0.0.0'
    filename.write_text(json.dumps(data), encoding='utf-8')
    cap = ens.probe_ens_normalizer()
    assert cap.installed and not cap.usable and cap.error_type == 'normalizer_unavailable'


@pytest.mark.parametrize('output', [b'not-json', b'{}', b'[]', b'{"ok":1}',
    b'{"ok":true,"normalized":"a","extra":2}', b'{"ok":true,"normalized":""}',
    b'{"ok":true,"normalized":"a","normalized":"b"}', b'{"ok":false,"error_type":[]}',
    b'{"ok":false,"error_type":"C:/secret/path"}', b'{"ok":true,"normalized":"\\ud800"}', b'\xff'])
def test_malformed_helper_protocol(monkeypatch, output):
    monkeypatch.setattr(ens, '_run', lambda payload: output)
    failure(lambda: ens.normalize_ens_name('name.eth'), 'normalizer_protocol_error')


@pytest.mark.parametrize('script,category', [
    ('process.stdin.resume(); setInterval(() => {}, 1000);', 'normalizer_timeout'),
    ('process.stdout.write("x".repeat(100000));', 'normalizer_protocol_error'),
    ('process.stderr.write("x".repeat(100000));', 'normalizer_protocol_error'),
    ('process.stderr.write("C:/secret/helper/stack"); process.exit(7);', 'normalizer_protocol_error'),
    ('process.exit(7);', 'normalizer_protocol_error'),
    ('process.stdout.write("not json");', 'normalizer_protocol_error'),
])
def test_real_subprocess_failures_bounded_and_reaped(isolated_helper, monkeypatch, script, category):
    _, helper = isolated_helper
    helper.write_text(script, encoding='utf-8')
    monkeypatch.setattr(ens, 'TIMEOUT_SECONDS', 0.75)
    created = []
    popen = subprocess.Popen
    def record(*args, **kwargs):
        process = popen(*args, **kwargs)
        created.append(process)
        return process
    monkeypatch.setattr(ens.subprocess, 'Popen', record)
    started = monotonic()
    failure(lambda: ens.normalize_ens_name('name.eth'), category)
    assert monotonic() - started < 3
    assert all(process.poll() is not None for process in created)


def test_normalized_typed_storage_without_any_result_or_side_effect():
    engine = create_fk_enabled_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    names = ['NaMe.EtH', 'RaFFY\U0001f6b4\u200d\u2642\ufe0f.eTh',
             '\U0001f3f4\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f', '\U0001faea']
    try:
        with Session(engine) as db:
            service = DiscoveryService(db, metadata_only=True)
            def counts():
                return {table.name: db.scalar(select(func.count()).select_from(table))
                        for table in Base.metadata.tables.values() if table.name != DiscoverySubject.__table__.name}
            before = counts()
            for raw in names:
                normalized = ens.normalize_ens_subject(raw)
                assert normalized['kind'] == 'ens_name' and normalized['namespace'] == 'ethereum'
                assert normalized['canonical_value'] == ens.normalize_ens_name(raw)
                row = service.get_or_create_subject('ens_name', 'ethereum', normalized['canonical_value'])
                with pytest.raises(DiscoveryError, match='Only wallet'):
                    service.create_run(row['id'], [], idempotency_key=row['id'])
            assert counts() == before  # Includes runs, results, attribution, cases, labels and risk.
            assert set(REGISTRY.transforms) == {'wallet.local_labels','wallet.manual_exact_web','wallet.public_code_mentions'}
    finally:
        engine.dispose()


def test_raw_subject_path_cannot_bypass_normalizer(monkeypatch):
    def unavailable(value):
        raise ens.EnsNormalizationError('normalizer_unavailable')
    monkeypatch.setattr(ens, 'normalize_ens_name', unavailable)
    failure(lambda: ens.normalize_ens_subject('MiXeD.eth'), 'normalizer_unavailable')
    with pytest.raises(DiscoveryError):
        canonical_ens_subject('ethereum', '\U0001f6b4\u200d\u2642.eth')


def test_nonreading_child_cannot_block_large_stdin(isolated_helper, monkeypatch):
    _, helper = isolated_helper
    helper.write_text('process.stdin.pause(); setInterval(() => {}, 1000);', encoding='utf-8')
    monkeypatch.setattr(ens, 'TIMEOUT_SECONDS', 0.75)
    started = monotonic()
    failure(lambda: ens.normalize_ens_name('\x00' * 2048), 'normalizer_timeout')
    assert monotonic() - started < 3


def test_relationship_direction_and_namespace_unchanged():
    name = ens.normalize_ens_subject('NAME.eth')
    wallet = canonical_subject('blockchain_address', 'ethereum', '0x' + '1' * 40)
    result_identity(wallet, 'candidate_relationship', 'resolves_to', name, wallet, {})
    with pytest.raises(DiscoveryError):
        result_identity(wallet, 'candidate_relationship', 'resolves_to', wallet, name, {})
    bitcoin = canonical_subject('blockchain_address', 'bitcoin', '1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa')
    with pytest.raises(DiscoveryError):
        result_identity(wallet, 'candidate_relationship', 'resolves_to', name, bitcoin, {})


def test_app_startup_without_node_uses_only_isolated_db(monkeypatch, tmp_path):
    import main
    import greedy_collector.database as database
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    engine = create_fk_enabled_engine('sqlite:///' + str(tmp_path / 'startup.sqlite'))
    monkeypatch.setattr(database, 'SessionLocal', sessionmaker(bind=engine))
    monkeypatch.setattr(main, 'start_monitoring', lambda: None)
    monkeypatch.setattr(main, 'stop_monitoring', lambda: None)
    monkeypatch.setattr(ens, '_node_executable', lambda: (_ for _ in ()).throw(ens.EnsNormalizationError('normalizer_unavailable')))
    try:
        with TestClient(main.app) as client:
            assert client.get('/health').status_code == 200
            assert client.get('/').status_code == 200
            assert not ens.probe_ens_normalizer().usable
    finally:
        engine.dispose()
