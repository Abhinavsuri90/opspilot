import json

from app.main import app

print(json.dumps(app.openapi()))
