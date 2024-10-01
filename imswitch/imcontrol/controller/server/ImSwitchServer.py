import threading
import Pyro5
import Pyro5.server
from Pyro5.api import expose
import multiprocessing
from imswitch.imcommon.framework import Worker
from imswitch.imcommon.model import initLogger
from ._serialize import register_serializers
from fastapi.middleware.cors import CORSMiddleware
import asyncio

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
import imswitch
import uvicorn
from functools import wraps
import os
import socket
import os

from imswitch import IS_HEADLESS, __ssl__, __httpport__

import socket
from fastapi.middleware.cors import CORSMiddleware
from http.server import HTTPServer, BaseHTTPRequestHandler
import os
import threading
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.staticfiles import StaticFiles

try:
    pass
#    from arkitekt_next import easy
except ImportError:
    print("Arkitekt not found")

 

import logging

PORT = __httpport__
IS_SSL = __ssl__

_baseDataFilesDir = os.path.join(os.path.dirname(os.path.realpath(imswitch.__file__)), '_data')
static_dir = os.path.join(_baseDataFilesDir,  'static')
imswitchapp_dir = os.path.join(_baseDataFilesDir,  'static', 'imswitch')
app = FastAPI(docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=static_dir), name="static")  # serve static files such as the swagger UI
app.mount("/imswitch", StaticFiles(directory=imswitchapp_dir), name="imswitch") # serve react app


#arpp = easy()


if IS_SSL:
    app.add_middleware(HTTPSRedirectMiddleware)

origins = [
    "http://localhost:8001",
    "http://localhost:8000",
    "http://localhost",
    "http://localhost:8080",
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ServerThread(threading.Thread):
    def __init__(self):
        super().__init__()
        self.server = None

    def run(self):
        try:
            config = uvicorn.Config(
                app,
                host="0.0.0.0",
                port=PORT,
                ssl_keyfile=os.path.join(_baseDataFilesDir, "ssl", "key.pem") if IS_SSL else None,
                ssl_certfile=os.path.join(_baseDataFilesDir, "ssl", "cert.pem") if IS_SSL else None
            )
            self.server = uvicorn.Server(config)
            self.server.run()
        except Exception as e:
            print(f"Couldn't start server: {e}")

    def stop(self):
        if self.server:
            self.server.should_exit = True
            self.server.lifespan.shutdown()
            print("Server is stopping...")
class ImSwitchServer(Worker):

    def __init__(self, api, setupInfo):
        super().__init__()

        self._api = api
        self._name = setupInfo.pyroServerInfo.name
        self._host = setupInfo.pyroServerInfo.host
        self._port = setupInfo.pyroServerInfo.port

        self._paused = False
        self._canceled = False

        self.__logger =  initLogger(self)


    def moveToThread(self, thread) -> None:
        return super().moveToThread(thread)

    def run(self):
        # serve the fastapi
        self.createAPI()

        # To operate remotely we need to provide https
        # openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365
        # uvicorn your_fastapi_app:app --host 0.0.0.0 --port 8001 --ssl-keyfile=./key.pem --ssl-certfile=./cert.pem

        # Create and start the server thread
        self.server_thread = ServerThread()
        self.server_thread.start()
        self.__logger.debug("Started server with URI -> PYRO:" + self._name + "@" + self._host + ":" + str(self._port))


    def stop(self):
        self.__logger.debug("Stopping ImSwitchServer")
        try:
            self.server_thread.stop()
            #self.server_thread.join()
        except Exception as e:
            self.__logger.error("Couldn't stop server: "+str(e))

    def get_ip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))
            IP = s.getsockname()[0]
        except Exception:
            IP = '127.0.0.1'
        finally:
            s.close()
        return IP

    @app.get("/docs", include_in_schema=False)
    async def custom_swagger_ui_html():
        return get_swagger_ui_html(
            openapi_url=app.openapi_url,
            title=app.title + " - ImSwitch Swagger UI",
            oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
            swagger_js_url="/static/swagger-ui-bundle.js",
            swagger_css_url="/static/swagger-ui.css",
        )
        
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                data = await websocket.receive_text()
                print(f"Message received: {data}")
                #await websocket.send_text(f"Message sent: {data}")
        except WebSocketDisconnect:
            print("Connection closed")
        except Exception as e:
            print(f"Connection closed: {e}")
            


    @app.get("/")
    def createAPI(self):
        api_dict = self._api._asdict()
        functions = api_dict.keys()

        def includeAPI(str, func):
            if hasattr(func, '._APIAsyncExecution') and func._APIAsyncExecution:
                @app.get(str) # TODO: Perhaps we want POST instead?
                @wraps(func)
                async def wrapper(*args, **kwargs):
                    return await func(*args, **kwargs) # sometimes we need to return a future 
            else:
                @app.get(str) # TODO: Perhaps we want POST instead?
                @wraps(func)
                #@register
                async def wrapper(*args, **kwargs):
                    return func(*args, **kwargs)
            return wrapper

        def includePyro(func):
            @expose
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)
            return wrapper

        for f in functions:
            func = api_dict[f]
            if hasattr(func, 'module'):
                module = func.module
            else:
                module = func.__module__.split('.')[-1]
            self.func = includePyro(includeAPI("/"+module+"/"+f, func))



# Copyright (C) 2020-2024 ImSwitch developers
# This file is part of ImSwitch.
#
# ImSwitch is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# ImSwitch is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
