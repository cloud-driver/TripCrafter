from flask import Flask
from gevent import pywsgi

app = Flask(__name__)
@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"

server = pywsgi.WSGIServer(('0.0.0.0', 12345), app)
server.serve_forever()
