import asyncio
import aiohttp
import rauth
import json
import hashlib
import random
import urllib.parse
from .types import User
from .errors import (OAuth2StepError, OAuth2BadData)
from ..log import logger


def get_github_oauth_service(config):
    client_id = config['github_login']['client_id']
    client_secret = config['github_login']['client_secret']
    github_service = rauth.OAuth2Service(
        client_id=client_id,
        client_secret=client_secret,
        name='github',
        authorize_url='https://github.com/login/oauth/authorize',
        access_token_url='https://github.com/login/oauth/access_token',
        base_url='https://api.github.com/')
    return github_service


@asyncio.coroutine
def access_github_api(method, api_url, params, access_token):
    oauth_headers = {
        'Authorization': 'token ' + access_token
    }
    client_res = yield from aiohttp.request(method, api_url,
                                            params=params,
                                            headers=oauth_headers,
                                            allow_redirects=True)
    rjson = json.loads((yield from client_res.read()).decode('utf8'))
    client_res.close()
    return rjson


@asyncio.coroutine
def get_user_from_github(platform_key, config):
    user_json = yield from access_github_api(
        'GET', 'https://api.github.com/user',
        {}, platform_key)

    logger.debug('user_json = %r', user_json)

    display_name = user_json.get('name', None)
    if display_name is None:
        display_name = user_json['login']
    user = User('n/a', display_name,
                user_json['avatar_url'],
                user_json['avatar_url'],
                'github', platform_key)
    return user


@asyncio.coroutine
def oauth2_to_github_1(config, redis):
    github_service = get_github_oauth_service(config)

    redirect_uri = config['github_login']['redirect_uri']
    params = {
        'scope': '',
        'redirect_uri': redirect_uri,
        'state':
            hashlib.sha1(str(random.random()).encode('ascii')).hexdigest(),
    }

    url = github_service.get_authorize_url(**params)

    f = asyncio.Future()
    f.set_result(url)
    return f


@asyncio.coroutine
def oauth2_to_github_2(code_data, config, redis):
    if 'code' in code_data:
        code = code_data['code']

        github_service = get_github_oauth_service(config)
        redirect_uri = config['github_login']['redirect_uri']

        loop = asyncio.get_event_loop()
        req_data = {
            'code': code,
            'redirect_uri': redirect_uri,
        }

        def github_token_decoder(data):
            parsed = urllib.parse.parse_qs(
                data.decode('utf8'), keep_blank_values=True)
            for k, v in parsed.items():
                parsed[k] = v[0]
            return parsed

        session = yield from loop.run_in_executor(
            None, lambda: github_service.get_auth_session(
                data=req_data, decoder=github_token_decoder))

        user = yield from get_user_from_github(session.access_token, config)

        return user
    elif 'error' in code_data:
        logger.debug('oauth2_to_github_2 error, code_data = %r', code_data)
        raise OAuth2StepError(code_data)
    else:
        logger.debug('oauth2_to_github_2 bad data, code_data = %r', code_data)
        raise OAuth2BadData(code_data)
