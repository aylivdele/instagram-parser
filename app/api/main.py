from fastapi import FastAPI

from app.api.routes import register, folders, competitors, alerts


def create_app() -> FastAPI:

    app = FastAPI(title="Instagram Monitor API")

    app.include_router(register.router, prefix="/api")
    app.include_router(folders.router, prefix="/api")
    app.include_router(competitors.router, prefix="/api")
    app.include_router(alerts.router, prefix="/api")

    return app
