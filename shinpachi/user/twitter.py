import asyncio
import aiohttp
import rauth
import json
import hashlib
import random
import time
from .types import User
from .errors import (OAuth2StepError, OAuth2BadData)
from ..log import logger


def get_twitter_oauth_service(config):
    consumer_key = config['twitter_login']['consumer_key']
    consumer_secret = config['twitter_login']['consumer_secret']
    twitter_service = rauth.OAuth1Service(
        name='twitter',
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        request_token_url='https://api.twitter.com/oauth/request_token',
        access_token_url='https://api.twitter.com/oauth/access_token',
        authorize_url='https://api.twitter.com/oauth/authorize',
        base_url='https://api.twitter.com/1.1/')
    return twitter_service


@asyncio.coroutine
def access_twitter_api(method, api_url, params):
    client_res = yield from aiohttp.request(method, api_url,
                                            params=params,
                                            allow_redirects=True)
    rjson = json.loads((yield from client_res.read()).decode('utf8'))
    client_res.close()
    return rjson


def get_twitter_oauth_params(access_token, config,
                             signature_class=rauth.oauth.HmacSha1Signature):
    consumer_key = config['twitter_login']['consumer_key']
    oauth_params = {
        'oauth_consumer_key': consumer_key,
        'oauth_nonce':
            hashlib.sha1(str(random.random()).encode('ascii')).hexdigest(),
        'oauth_signature_method': signature_class.NAME,
        'oauth_timestamp': int(time.time()),
        'oauth_token': access_token,
        'oauth_version': rauth.OAuth1Session.VERSION,
    }

    return oauth_params


def sign_twitter_oauth_params(method, url, oauth_params, access_secret,
                              consumer_secret,
                              other_params=None, other_data=None,
                              other_headers=None,
                              signature_class=rauth.oauth.HmacSha1Signature):
    signature = signature_class()

    sign_kw = {}
    if other_params is not None:
        sign_kw['params'] = other_params
    if other_data is not None:
        sign_kw['data'] = other_data
    if other_headers is not None:
        sign_kw['headers'] = other_headers

    oauth_signature = signature.sign(consumer_secret, access_secret,
                                     method, url, oauth_params, sign_kw)
    return oauth_signature


@asyncio.coroutine
def get_user_from_twitter(platform_key, config):
    access_token, access_secret = platform_key.split(';')
    oauth_params = get_twitter_oauth_params(access_token, config)
    api_url = 'https://api.twitter.com/1.1/account/verify_credentials.json'
    consumer_secret = config['twitter_login']['consumer_secret']
    oauth_signature = sign_twitter_oauth_params(
        'GET', api_url, oauth_params, access_secret, consumer_secret)
    oauth_params['oauth_signature'] = oauth_signature
    user_json = yield from access_twitter_api('GET', api_url, oauth_params)
    logger.debug('user_json = %r', user_json)

    user = User('n/a', user_json['name'],
                user_json['profile_image_url'],
                user_json['profile_image_url_https'],
                'twitter', platform_key)
    logger.debug('user = %r', user)
    return user


# In seconds
OAUTH_TOKEN_EXPIRE_TIME = 5 * 60


@asyncio.coroutine
def oauth_to_twitter_1(config, redis):
    loop = asyncio.get_event_loop()
    twitter_service = get_twitter_oauth_service(config)
    request_token, request_secret = yield from loop.run_in_executor(
        None, twitter_service.get_request_token)
    yield from redis.set('twitter_oauth.' + request_token,
                         request_secret,
                         expire=OAUTH_TOKEN_EXPIRE_TIME)
    authorize_url = twitter_service.get_authorize_url(request_token)
    return authorize_url


@asyncio.coroutine
def oauth_to_twitter_2(code_data, config, redis):
    if 'oauth_token' not in code_data \
            or 'oauth_verifier' not in code_data:
        logger.debug('oauth_to_twitter_2 bad data, code_data = %r', code_data)
        raise OAuth2BadData(code_data)

    token = code_data['oauth_token'][0]
    verifier = code_data['oauth_verifier'][0]

    secret = yield from redis.get('twitter_oauth.' + token)
    if secret is None:
        logger.debug('oauth_to_twitter_2 token expired, code_data = %r', code_data)
        raise OAuth2BadData(code_data)

    yield from redis.delete(['twitter_oauth.' + token])

    twitter_service = get_twitter_oauth_service(config)
    loop = asyncio.get_event_loop()
    session = yield from loop.run_in_executor(
        None,
        lambda: twitter_service.get_auth_session(
            token, secret, method='POST',
            data={'oauth_verifier': verifier}))

    logger.debug('access_token = %r', session.access_token)
    logger.debug('access_token_secret = %r', session.access_token_secret)

    platform_key = '{};{}'.format(session.access_token,
                                  session.access_token_secret)
    user = yield from get_user_from_twitter(platform_key, config)
    return user
