import asyncio
import aiohttp
import rauth
import json
from .types import User
from .errors import (OAuth2StepError, OAuth2BadData)
from ..log import logger


def get_weibo_oauth_service(config):
    client_id = config['weibo_login']['client_id']
    client_secret = config['weibo_login']['client_secret']
    weibo_service = rauth.OAuth2Service(
        client_id=client_id,
        client_secret=client_secret,
        name='weibo',
        authorize_url='https://api.weibo.com/oauth2/authorize',
        access_token_url='https://api.weibo.com/oauth2/access_token',
        base_url='https://api.weibo.com/2/')
    return weibo_service


@asyncio.coroutine
def access_weibo_api(method, api_url, params):
    client_res = yield from aiohttp.request(method, api_url,
                                            params=params,
                                            allow_redirects=True)
    rjson = json.loads((yield from client_res.read()).decode('utf8'))
    client_res.close()
    return rjson


@asyncio.coroutine
def get_user_from_weibo(platform_key, config):
    uid_json = yield from access_weibo_api(
        'GET',
        'https://api.weibo.com/2/account/get_uid.json',
        {'access_token': platform_key})
    logger.debug('uid_json = %r', uid_json)

    user_json = yield from access_weibo_api(
        'GET',
        'https://api.weibo.com/2/users/show.json',
        {'access_token': platform_key,
         'uid': uid_json['uid']})
    logger.debug('user_json = %r', user_json)

    # TODO
    #email_json = yield from access_weibo_api(
    #    'GET',
    #    'https://api.weibo.com/2/account/profile/email.json',
    #    {'access_token': platform_key})
    #logger.debug('email_json = %r', email_json)

    user = User('n/a', user_json['screen_name'],
                user_json['profile_image_url'],
                user_json['profile_image_url'],
                'weibo', platform_key)
    return user


@asyncio.coroutine
def oauth2_to_weibo_1(config, redis):
    weibo_service = get_weibo_oauth_service(config)

    redirect_uri = config['weibo_login']['redirect_uri']
    params = {'scope': 'email',
              'response_type': 'code',
              'redirect_uri': redirect_uri}

    url = weibo_service.get_authorize_url(**params)

    f = asyncio.Future()
    f.set_result(url)
    return f


@asyncio.coroutine
def oauth2_to_weibo_2(code_data, config, redis):
    if 'code' in code_data:
        code = code_data['code']

        weibo_service = get_weibo_oauth_service(config)
        redirect_uri = config['weibo_login']['redirect_uri']

        loop = asyncio.get_event_loop()
        req_data = {'code': code, 'redirect_uri': redirect_uri}

        def weibo_token_decoder(data):
            return json.loads(data.decode('utf8'))

        session = yield from loop.run_in_executor(
            None, lambda: weibo_service.get_auth_session(
                data=req_data, decoder=weibo_token_decoder))

        user = yield from get_user_from_weibo(session.access_token, config)

        return user
    elif 'error' in code_data:
        logger.debug('oauth2_to_weibo_2 error, code_data = %r', code_data)
        raise OAuth2StepError(code_data)
    else:
        logger.debug('oauth2_to_weibo_2 bad data, code_data = %r', code_data)
        raise OAuth2BadData(code_data)
