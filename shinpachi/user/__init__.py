import asyncio
from ..log import logger
from .weibo import (get_user_from_weibo,
                    oauth2_to_weibo_1,
                    oauth2_to_weibo_2)
from .twitter import (get_user_from_twitter,
                      oauth_to_twitter_1,
                      oauth_to_twitter_2)
from .google import (get_user_from_google,
                     oauth2_to_google_1,
                     oauth2_to_google_2)
from .github import (get_user_from_github,
                     oauth2_to_github_1,
                     oauth2_to_github_2)
from .facebook import (get_user_from_facebook,
                       oauth2_to_facebook_1,
                       oauth2_to_facebook_2)


SUPPORTED_PLATFORMS = {
    'weibo': {
        'get_user': get_user_from_weibo,
        'oauth2_login_1': oauth2_to_weibo_1,
        'oauth2_login_2': oauth2_to_weibo_2,
    },
    'twitter': {
        'get_user': get_user_from_twitter,
        'oauth2_login_1': oauth_to_twitter_1,
        'oauth2_login_2': oauth_to_twitter_2,
    },
    'facebook': {
        'get_user': get_user_from_facebook,
        'oauth2_login_1': oauth2_to_facebook_1,
        'oauth2_login_2': oauth2_to_facebook_2,
    },
    'google': {
        'get_user': get_user_from_google,
        'oauth2_login_1': oauth2_to_google_1,
        'oauth2_login_2': oauth2_to_google_2,
    },
    'github': {
        'get_user': get_user_from_github,
        'oauth2_login_1': oauth2_to_github_1,
        'oauth2_login_2': oauth2_to_github_2,
    },
}


@asyncio.coroutine
def get_user(key, config):
    try:
        platform, platform_key = key.split(':')
    except ValueError:
        logger.warning('Invalid Key: %r', key)
        return None

    platform_handler = SUPPORTED_PLATFORMS.get(platform, None)
    if platform_handler is None:
        return None

    return (yield from (platform_handler['get_user'])(platform_key, config))


@asyncio.coroutine
def oauth_login(form_data, config, redis):
    platform = platform_handler = None
    for pl, handler in SUPPORTED_PLATFORMS.items():
        if (pl + '_login').encode('utf8') in form_data:
            platform, platform_handler = pl, handler
            break

    logger.debug('platform = %r', platform)

    if platform is not None:
        return (yield from (platform_handler['oauth2_login_1'])(config, redis))
    else:
        return None


@asyncio.coroutine
def oauth2_code_cb(platform, code_data, config, redis):
    platform_handler = SUPPORTED_PLATFORMS.get(platform, None)
    if platform_handler is None:
        return None

    return (yield from (platform_handler['oauth2_login_2'])(code_data, config, redis))
