import asyncio
import os
os.environ.setdefault('SENTINEL_API_KEY', 'unit-tests-only-not-a-real-api-key-000000')
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sentinel.app import create_app
from sentinel.classifier import rule_priority
from sentinel.config import Settings

KEY = 'unit-tests-only-not-a-real-api-key-000000'
HEADERS = {'X-API-Key': KEY}


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(api_key=KEY, db_path=tmp_path / 'test.db',
                              audio_dir=tmp_path / 'audio'), start_worker=False)
    with TestClient(app) as c:
        yield c


def test_auth_protects_api(client):
    assert client.get('/').status_code == 200
    assert client.get('/api/events').status_code == 401
    assert client.post('/api/events', json={'source':'codex','title':'done'}).status_code == 401
    assert client.get('/health').json()['status'] == 'ok'


def test_create_and_dedup(client):
    body = {'source':'whop','event_id':'job-42','title':'Instagram failed',
            'message':'needs approval'}
    first = client.post('/api/events', json=body, headers=HEADERS)
    second = client.post('/api/events', json=body, headers=HEADERS)
    assert first.status_code == 201 and first.json()['created'] is True
    assert second.status_code == 201 and second.json()['created'] is False
    assert first.json()['id'] == second.json()['id']
    assert client.get('/api/events', headers=HEADERS).json()['stats']['total'] == 1


def test_classification():
    assert rule_priority('service down', 'critical outage', 'auto') == 'critical'
    assert rule_priority('Build finished', 'all tests passed', 'auto') == 'important'
    assert rule_priority('worker', '0 errors and tests passed', 'auto') == 'important'
    assert rule_priority('received item', '3 events', 'auto') == 'normal'
    assert rule_priority('fatal', 'outage', 'silent') == 'silent'


def test_worker_and_demo(client):
    demo = client.post('/api/demo', headers=HEADERS).json()
    engine = client.app.state.engine
    asyncio.run(engine.run_once())
    rows = client.get('/api/events', headers=HEADERS).json()['events']
    assert rows[0]['id'] == demo['id']
    assert rows[0]['status'] == 'ready'
    assert 'работают' in rows[0]['speech']
    assert client.get('/api/events/1/audio', headers=HEADERS).status_code == 404
    assert client.get('/api/events/1/audio').status_code == 401


def test_digest_and_silent(client):
    for name,level in [('one','normal'),('two','silent')]:
        r = client.post('/api/events', json={'source':'system','title':name,'level':level}, headers=HEADERS)
        assert r.status_code == 201
    result = client.post('/api/digest', headers=HEADERS)
    assert result.json()['digested'] == 1
    data = client.get('/api/events', headers=HEADERS).json()['events']
    assert {x['status'] for x in data} == {'silent','digested','ready'}
    assert next(x for x in data if x['source'] == 'Sentinel')['title'] == 'Дайджест событий'


def test_input_validation_and_xss(client):
    assert client.post('/api/events',json={'source':'../bad','title':'x'},headers=HEADERS).status_code == 422
    assert client.post('/api/events',json={'source':'x','title':'','message':'a'},headers=HEADERS).status_code == 422
    assert client.post('/api/events',json={'source':'x','title':'x','level':'root'},headers=HEADERS).status_code == 422
    title = '<img src=x onerror=alert(1)>'
    r = client.post('/api/events',json={'source':'x','title':title},headers=HEADERS)
    assert r.status_code == 201
    assert client.get('/api/events',headers=HEADERS).json()['events'][0]['title'] == title
    assert 'textContent' in (Path(__file__).parents[1]/'static/app.js').read_text()


def test_no_env_secret_in_page(client):
    html = client.get('/').text
    assert KEY not in html
    assert 'VOICE SENTINEL' in html


def test_audio_route_ignores_db_filename(client, tmp_path):
    r = client.post('/api/demo', headers=HEADERS).json()
    eid = r['id']
    c = client.app.state.store
    c.update(eid, audio_file='../../secret.txt')
    file = c.path.parent / 'audio' / f'{eid}.wav'
    file.write_bytes(b'RIFFfake')
    got = client.get(f'/api/events/{eid}/audio', headers=HEADERS)
    assert got.status_code == 200 and got.content == b'RIFFfake'


def test_processing_event_is_recovered_on_restart(tmp_path):
    from sentinel.store import Store
    db = tmp_path / 'database.sqlite3'
    a = Store(db)
    event, _ = a.insert('worker', 'id1', 'Complete', 'All done', 'important', 'important', 'done')
    a.update(event['id'], status='processing')
    b = Store(db)
    b.recover()
    assert b.get(event['id'])['status'] == 'queued'


def test_qwen_provider_and_telegram_are_attempted(client, monkeypatch, tmp_path):
    import sentinel.engine as engine_module
    from sentinel.config import Settings
    call_log = []
    async def fake_synth(settings, text, path):
        call_log.append(('tts', text))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'RIFFtest')
        return True
    async def fake_telegram(settings, text, priority, wav=None):
        call_log.append(('telegram', priority, bool(wav)))
        return True
    monkeypatch.setattr(engine_module, 'synthesize', fake_synth)
    monkeypatch.setattr(engine_module, 'telegram_send', fake_telegram)
    app = create_app(Settings(api_key=KEY, db_path=tmp_path / 'qwen.sqlite3',
                      audio_dir=tmp_path / 'sounds', tts_provider='qwen'), start_worker=False)
    with TestClient(app) as c:
        row = c.post('/api/demo', headers=HEADERS).json()
        asyncio.run(c.app.state.engine.run_once())
        stored = c.app.state.store.get(row['id'])
        assert stored['audio_file'] == f"{row['id']}.wav"
        assert c.get(f"/api/events/{row['id']}/audio", headers=HEADERS).status_code == 200
    assert call_log[0][0] == 'tts'
    assert call_log[1] == ('telegram', 'important', True)


def test_failed_tts_does_not_drop_notification(tmp_path, monkeypatch):
    import sentinel.engine as engine_module
    async def broken(*args, **kwargs):
        raise RuntimeError('Model is offline')
    async def fake_telegram(*args):
        return True
    monkeypatch.setattr(engine_module, 'synthesize', broken)
    monkeypatch.setattr(engine_module, 'telegram_send', fake_telegram)
    app = create_app(Settings(api_key=KEY, db_path=tmp_path / 'error.sqlite3',
            audio_dir=tmp_path / 'audio', tts_provider='qwen'), start_worker=False)
    with TestClient(app) as c:
        row = c.post('/api/demo', headers=HEADERS).json()
        asyncio.run(c.app.state.engine.run_once())
        saved = c.app.state.store.get(row['id'])
        assert saved['status'] == 'ready'
        assert saved['audio_file'] is None
        assert 'Model is offline' in saved['error']
