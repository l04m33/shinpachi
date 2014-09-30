import configparser
import os
import multiprocessing


class ConfigError(Exception):
    pass


class ConfigNotFoundError(Exception):
    pass


def init_config(file_name=None):
    config = configparser.ConfigParser()
    config.read_dict({
        'log': {
            'level': 'INFO',
        },
        'proxy': {
            'enabled': 'no',
            'host': '*',
            'port': '9999',
            'backlog': '128',
            'processes': str(multiprocessing.cpu_count()),
        },
        'http_proxy': {
            'enabled': 'yes',
            'host': '*',
            'port': '9997',
            'backlog': '128',
            'processes': str(multiprocessing.cpu_count()),
            'auth_ip': 'no',
            'loop_detection_ip': '127.0.0.1',
        },
        'http': {
            'enabled': 'yes',
            'host': '*',
            'port': '8080',
            'backlog': '64',
            'processes': str(multiprocessing.cpu_count()),
            'ssl': 'no',
            'ssl_key': '',
            'ssl_cert': '',
            'need_auth': 'no',
        },
        'redis': {
            'host': 'localhost',
            'port': '6379',
            'pool_size': '5',
        },
        'bridge': {
            'xsub_address': 'tcp://127.0.0.1:7999',
            'xpub_address': 'tcp://127.0.0.1:7997',
            'pub_address': 'tcp://127.0.0.1:7995',
        },
        'twitter_login': {
            'consumer_key': '',
            'consumer_secret': '',
        },
        'facebook_login': {
            'client_id': '',
            'client_secret': '',
            'redirect_uri': '',
        },
        'weibo_login': {
            'client_id': '',
            'client_secret': '',
            'redirect_uri': '',
        },
        'google_login': {
            'client_id': '',
            'client_secret': '',
            'redirect_uri': '',
        },
        'github_login': {
            'client_id': '',
            'client_secret': '',
            'redirect_uri': '',
        },
        'misc': {
            'config_file': '',
        },
    })

    if file_name is not None:
        if not os.path.isfile(file_name):
            raise ConfigNotFoundError('No such file: \'{}\''.format(file_name))
        config.read(file_name)
        config['misc']['config_file'] = file_name
    return config


# XXX: supports only *nix
def get_abs_path(config, fname):
    if fname.startswith('/'):
        return os.path.abspath(fname)

    config_file = config['misc']['config_file']
    config_dir, config_file_name = os.path.split(config_file)
    abspath = os.path.abspath('{}/{}'.format(config_dir, fname))
    return abspath
