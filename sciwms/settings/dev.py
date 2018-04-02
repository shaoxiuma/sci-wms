#!python
# coding=utf-8
from .defaults import *

DEBUG          = True
TESTING        = False

LOGGING = setup_logging(default='INFO')
INSTALLED_APPS += [
    'django_extensions',
    'debug_toolbar'
]
MIDDLEWARE_CLASSES += ['debug_toolbar.middleware.DebugToolbarMiddleware']

LOCAL_APPS = ()
try:
    from local_settings import *
except ImportError:
    pass
try:
    from local.settings import *
except ImportError:
    pass
INSTALLED_APPS += LOCAL_APPS
