import sys
import os

if not 'MD_PUBLISHER_ROOT' in os.environ:
    os.environ['MD_PUBLISHER_ROOT'] = '/app'
MD_PUBLISHER_ROOT = os.environ['MD_PUBLISHER_ROOT']

if MD_PUBLISHER_ROOT not in sys.path:
   sys.path.append(MD_PUBLISHER_ROOT)

from md_publisher import app as application
