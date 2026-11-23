import os
from http.server import HTTPServer, SimpleHTTPRequestHandler

PORT = 8089
DIRECTORY = os.path.join(os.path.dirname(__file__), "static")

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

def run():
    server_address = ('', PORT)
    httpd = HTTPServer(server_address, Handler)
    print(f"TacTicTap Beta Simulator running at http://localhost:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")

if __name__ == '__main__':
    run()
