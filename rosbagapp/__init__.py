from flask import Flask

app = Flask(__name__)
app.secret_key = "secret_Key:1234567890"

# Bootstrap(app)

from rosbagapp.api.routes import mod

app.register_blueprint(api.routes.mod, url_prefix='/api')

