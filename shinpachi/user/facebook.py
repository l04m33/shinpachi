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


def get_facebook_oauth_service(config):
    client_id = config['facebook_login']['client_id']
    client_secret = config['facebook_login']['client_secret']
    facebook_service = rauth.OAuth2Service(
        client_id=client_id,
        client_secret=client_secret,
        name='facebook',
        authorize_url='https://www.facebook.com/dialog/oauth',
        access_token_url='https://graph.facebook.com/oauth/access_token',
        base_url='https://graph.facebook.com/')
    return facebook_service


@asyncio.coroutine
def access_facebook_api(method, api_url, params, access_token):
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
def get_user_from_facebook(platform_key, config):
    user_json = yield from access_facebook_api(
        'GET', 'https://graph.facebook.com/me',
        {'fields': 'id,name,picture'}, platform_key)

    logger.debug('user_json = %r', user_json)

    user = User('n/a', user_json['name'],
                user_json['picture']['data']['url'],
                user_json['picture']['data']['url'],
                'facebook', platform_key)
    return user


@asyncio.coroutine
def oauth2_to_facebook_1(config, redis):
    facebook_service = get_facebook_oauth_service(config)

    redirect_uri = config['facebook_login']['redirect_uri']
    params = {
        'scope': 'public_profile',
        'response_type': 'code',
        'redirect_uri': redirect_uri,
        'state':
            hashlib.sha1(str(random.random()).encode('ascii')).hexdigest(),
    }

    url = facebook_service.get_authorize_url(**params)

    f = asyncio.Future()
    f.set_result(url)
    return f


@asyncio.coroutine
def oauth2_to_facebook_2(code_data, config, redis):
    if 'code' in code_data:
        code = code_data['code']

        facebook_service = get_facebook_oauth_service(config)
        redirect_uri = config['facebook_login']['redirect_uri']

        loop = asyncio.get_event_loop()
        req_data = {
            'code': code,
            'redirect_uri': redirect_uri,
        }

        def facebook_token_decoder(data):
            parsed = urllib.parse.parse_qs(
                data.decode('utf8'), keep_blank_values=True)
            for k, v in parsed.items():
                parsed[k] = v[0]
            return parsed

        session = yield from loop.run_in_executor(
            None, lambda: facebook_service.get_auth_session(
                data=req_data, decoder=facebook_token_decoder))

        user = yield from get_user_from_facebook(session.access_token, config)

        return user
    elif 'error' in code_data:
        logger.debug('oauth2_to_facebook_2 error, code_data = %r', code_data)
        raise OAuth2StepError(code_data)
    else:
        logger.debug('oauth2_to_facebook_2 bad data, code_data = %r', code_data)
        raise OAuth2BadData(code_data)
