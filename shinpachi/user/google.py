import asyncio
import aiohttp
import rauth
import json
import hashlib
import random
from .types import User
from .errors import (OAuth2StepError, OAuth2BadData)
from ..log import logger


def get_google_oauth_service(config):
    client_id = config['google_login']['client_id']
    client_secret = config['google_login']['client_secret']
    google_service = rauth.OAuth2Service(
        client_id=client_id,
        client_secret=client_secret,
        name='google',
        authorize_url='https://accounts.google.com/o/oauth2/auth',
        access_token_url='https://accounts.google.com/o/oauth2/token',
        base_url='https://www.googleapis.com/plus/v1/')
    return google_service


@asyncio.coroutine
def access_google_api(method, api_url, params, access_token):
    oauth_headers = {
        'Authorization': 'Bearer ' + access_token
    }
    client_res = yield from aiohttp.request(method, api_url,
                                            params=params,
                                            headers=oauth_headers,
                                            allow_redirects=True)
    rjson = json.loads((yield from client_res.read()).decode('utf8'))
    client_res.close()
    return rjson


@asyncio.coroutine
def get_user_from_google(platform_key, config):
    user_json = yield from access_google_api(
        'GET', 'https://www.googleapis.com/plus/v1/people/me',
        {}, platform_key)

    logger.debug('user_json = %r', user_json)

    user = User('n/a', user_json['displayName'],
                user_json['image']['url'],
                user_json['image']['url'],
                'google', platform_key)
    return user


@asyncio.coroutine
def oauth2_to_google_1(config, redis):
    google_service = get_google_oauth_service(config)

    redirect_uri = config['google_login']['redirect_uri']
    params = {
        'scope': 'openid profile',
        'response_type': 'code',
        'state':
            hashlib.sha1(str(random.random()).encode('ascii')).hexdigest(),
        'redirect_uri': redirect_uri
    }

    url = google_service.get_authorize_url(**params)

    f = asyncio.Future()
    f.set_result(url)
    return f


@asyncio.coroutine
def oauth2_to_google_2(code_data, config, redis):
    if 'code' in code_data:
        code = code_data['code']

        google_service = get_google_oauth_service(config)
        redirect_uri = config['google_login']['redirect_uri']

        loop = asyncio.get_event_loop()
        req_data = {
            'code': code,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }

        def google_token_decoder(data):
            return json.loads(data.decode('utf8'))

        session = yield from loop.run_in_executor(
            None, lambda: google_service.get_auth_session(
                data=req_data, decoder=google_token_decoder))

        user = yield from get_user_from_google(session.access_token, config)

        return user
    elif 'error' in code_data:
        logger.debug('oauth2_to_google_2 error, code_data = %r', code_data)
        raise OAuth2StepError(code_data)
    else:
        logger.debug('oauth2_to_google_2 bad data, code_data = %r', code_data)
        raise OAuth2BadData(code_data)
