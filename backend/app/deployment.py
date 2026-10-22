import os


def create_app():
    mode = os.environ.get("CARELOOP_DEPLOYMENT_MODE", "published")
    if mode == "published":
        from backend.app.main import app

        return app
    if mode == "review":
        from backend.app.review_preview import create_review_app

        return create_review_app()
    raise ValueError("CARELOOP_DEPLOYMENT_MODE must be published or review")
