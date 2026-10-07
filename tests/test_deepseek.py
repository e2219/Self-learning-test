import asyncio
import httpx
import pytest
from backend import deepseek, db
from tests.test_api import client, setup  # noqa: F401


@pytest.mark.parametrize('scheme', ['http', 'https', 'socks5', 'socks5h'])
def test_supported_proxy_client_constructs_without_network(scheme):
    async def construct():
        async with deepseek.create_client(proxy=f'{scheme}://127.0.0.1:9'):
            pass
    asyncio.run(construct())


def test_invalid_proxy_scheme_is_safe_and_actionable():
    with pytest.raises(deepseek.ClientSetupError, match='DEEPSEEK_PROXY_CONFIG') as error:
        deepseek.create_client(proxy='socks://private-user:private-pass@127.0.0.1:9')
    assert 'private' not in str(error.value)


def test_connection_check_does_not_generate_or_send_text(client, setup, monkeypatch):
    original = httpx.AsyncClient
    def handler(request):
        assert request.method == 'GET' and str(request.url) == 'https://api.deepseek.com/models'
        assert not request.content
        assert request.headers['authorization'] == 'Bearer test-key-never-send'
        return httpx.Response(200, json={'data': [{'id': 'deepseek-flash'}]})
    monkeypatch.setattr(deepseek.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    result = client.post('/api/settings/test-connection')
    assert result.status_code == 200 and result.json()['ocr_model_available'] is True
    assert 'test-key-never-send' not in result.text


@pytest.mark.parametrize('key', ['中文密钥', 'sk-key\nsecret', 'Bearer sk-test'])
def test_invalid_key_fails_before_request(client, setup, key):
    db.set_setting('api_key', key)
    response = client.post('/api/settings/test-connection')
    assert response.status_code == 422 and 'DEEPSEEK_KEY_FORMAT' in response.text
    assert key not in response.text


def test_connection_check_respects_auth_and_hides_error_body(client, setup, monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(deepseek.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(lambda _: httpx.Response(401, text='PRIVATE')), **kw))
    response = client.post('/api/settings/test-connection')
    assert response.status_code == 422 and 'HTTP 401' in response.text and 'PRIVATE' not in response.text
    client.post('/api/logout')
    assert client.post('/api/settings/test-connection').status_code == 401
