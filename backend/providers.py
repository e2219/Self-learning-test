"""User-selected Chat Completions endpoints; credentials never leave their profile."""
import copy
import json
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from typing import Literal
from . import db, security

Role = Literal['text', 'vision']


class ProviderInput(BaseModel):
    enabled: bool = False
    name: str = Field(default='兼容服务', min_length=1, max_length=60)
    base_url: str = Field(default='', max_length=500)
    model: str = Field(default='', max_length=150)
    api_key: str = Field(default='', max_length=500)
    clear_key: bool = False
    json_mode: bool = True
    image_detail: Literal['auto', 'low', 'high', 'original'] = 'high'
    thinking: Literal['provider_default', 'disabled', 'enabled'] = 'provider_default'
    input_price: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    cached_price: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    output_price: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)

    @model_validator(mode='after')
    def valid(self):
        prices = (self.input_price, self.cached_price, self.output_price)
        if any(v is not None for v in prices) and not all(v is not None for v in prices):
            raise ValueError('计价需同时填写输入、缓存命中和输出单价')
        if self.cached_price is not None and self.cached_price > self.input_price:
            raise ValueError('缓存命中单价不能高于普通输入单价')
        self.base_url = self.base_url.strip().rstrip('/')
        self.model = self.model.strip()
        if self.enabled:
            u = urlsplit(self.base_url)
            _ = u.port  # Validate malformed or out-of-range ports before saving.
            local = u.hostname in ('localhost', '127.0.0.1', '::1')
            if not u.hostname or u.username or u.password or u.query or u.fragment or (u.scheme != 'https' and not (local and u.scheme == 'http')):
                raise ValueError('API 地址需为 HTTPS 基地址（本机服务可用 HTTP），不能含密钥、查询参数或片段')
            if self.base_url.endswith(('/chat/completions', '/models')) or not self.model:
                raise ValueError('请填写 API 基地址（通常以 /v1 结尾）和模型 ID')
        if self.api_key and (not self.api_key.isascii() or any(c.isspace() for c in self.api_key.strip())):
            raise ValueError('API Key 格式无效')
        return self


def custom(role):
    return json.loads(db.setting('provider_' + role, '{}'))


def config(role='text'):
    value = custom(role)
    if value.get('enabled'):
        return value
    return dict(name='DeepSeek', base_url='https://api.deepseek.com',
                model='deepseek-flash' if role == 'vision' else db.setting('model', 'deepseek-chat'),
                api_key=security.api_key(), json_mode=True, image_detail='original', builtin=True,
                thinking=db.setting('vision_thinking', 'enabled') if role == 'vision' else ('enabled' if db.setting('model','deepseek-chat') == 'deepseek-reasoner' else 'disabled'))


def identity(role='text'):
    p = config(role)
    identity = {k: p[k] for k in ('base_url', 'model', 'json_mode', 'image_detail')}
    # Preserve old cache keys when the now-explicit policy matches the prior default.
    if (p.get('builtin') and role == 'vision' and p['thinking'] != 'enabled') or (not p.get('builtin') and p.get('thinking','provider_default') != 'provider_default'):
        identity['thinking'] = p['thinking']
    return identity


def has_key(role='text'):
    return bool(config(role).get('api_key'))


def public(role):
    value = custom(role)
    return {**{k:v for k,v in value.items() if k != 'api_key'}, 'has_key':bool(value.get('api_key')),
            'active_name':config(role)['name'], 'active_model':config(role)['model']}


def save(role, payload):
    old = custom(role)
    value = payload.model_dump(exclude={'clear_key'})
    # Never forward a previous endpoint's key to a newly configured host/path.
    if payload.clear_key:
        value['api_key'] = ''
    elif not payload.api_key.strip():
        value['api_key'] = old.get('api_key', '') if old.get('base_url') == payload.base_url else ''
    else:
        value['api_key'] = payload.api_key.strip()
    if payload.enabled and not value['api_key']:
        raise HTTPException(422, '启用服务或更换 API 地址时，请填写该服务的 API Key。')
    db.set_setting('provider_' + role, db.dump(value))
    return public(role)


async def complete(client, body, role='text'):
    from . import deepseek
    p = config(role)
    data = copy.deepcopy(body)
    data['model'] = p['model']
    if p.get('builtin'):
        data.setdefault('thinking', {'type': p['thinking']})
    elif p.get('thinking', 'provider_default') == 'provider_default':
        data.pop('thinking', None)
    else:
        data.setdefault('thinking', {'type': p['thinking']})
    if not p.get('json_mode', True):
        data.pop('response_format', None)
    for message in data.get('messages', []):
        content = message.get('content')
        if isinstance(content, list):
            for item in content:
                if item.get('type') == 'image_url':
                    item['image_url']['detail'] = p['image_detail']
    from . import usage
    usage.describe_current(p, data)
    return await client.post(p['base_url'] + '/chat/completions',
                             headers={'Authorization': 'Bearer ' + deepseek.validate_key(p.get('api_key', ''))}, json=data)
