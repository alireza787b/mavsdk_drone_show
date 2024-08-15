#gcs-server/__init__.py
import os
import sys
from flask import Flask

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

def create_app(config_name=None):
    """
    Create and configure an instance of the Flask application.
    
    :param config_name: The configuration name (e.g., 'development', 'production').
    :return: Configured Flask application instance.
    """
    app = Flask(__name__)

    # Load configuration based on the environment or provided config name
    if config_name:
        app.config.from_object(f'config.{config_name.capitalize()}Config')
    else:
        app.config.from_object('config.DefaultConfig')

    # Set up logging if not already set by the environment
    if not app.debug and not app.testing:
        import logging
        from logging.handlers import RotatingFileHandler
        if not os.path.exists('logs'):
            os.mkdir('logs')
        file_handler = RotatingFileHandler('logs/gcs-server.log', maxBytes=10240, backupCount=10)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)

        app.logger.setLevel(logging.INFO)
        app.logger.info('GCS-Server startup')

    # Register blueprints
    # from your_module import your_blueprint
    # app.register_blueprint(your_blueprint)

    # Initialize other extensions (e.g., database, migrations)
    # db.init_app(app)
    # migrate.init_app(app, db)

    return app
