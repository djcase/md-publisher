#!/bin/sh
# changes
#     from flask.ext.autodoc.autodoc import Autodoc
# to
#     from flask_autodoc.autodoc import Autodoc
sed -i 's/flask.ext.autodoc/flask_autodoc/' /usr/local/lib/python3.6/site-packages/flask_autodoc/__init__.py
