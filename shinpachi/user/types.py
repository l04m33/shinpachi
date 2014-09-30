import collections


User = collections.namedtuple(
    'User',
    ['email', 'name', 'avatar', 'avatar_https', 'platform', 'key'])
