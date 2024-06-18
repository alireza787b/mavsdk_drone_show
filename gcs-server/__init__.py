#gcs-server/__init__.py
import os
import sys
from flask import Flask

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))


def create_app():
    app = Flask(__name__)
    return app
