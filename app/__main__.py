import uvicorn

from app.config import config

_server_cfg = config["server"]

uvicorn.run("app.main:app", host=_server_cfg["host"], port=_server_cfg["port"], reload=True)
