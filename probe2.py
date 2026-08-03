from fastapi import FastAPI
from core.api_routes import create_api_routes
from core.health_check import create_health_routes
def make():
    app = FastAPI()
    app.include_router(create_api_routes(service_manager=None, config=None))
    hr, _ = create_health_routes(service_manager=None, config=None)
    app.include_router(hr)
    return app
