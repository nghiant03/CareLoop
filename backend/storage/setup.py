"""One shot deployment schema setup."""

import logging

import psycopg

from backend.storage.migrate import initialize_database
from backend.storage.postgres import database_url


def prepare_deployment() -> None:
    urls = {component: database_url(component) for component in ("clinical", "knowledge")}
    if not all(urls.values()):
        raise ValueError("Deployment setup requires both clinical and knowledge PostgreSQL URLs")
    for component, url in urls.items():
        result = initialize_database(url, component)
        logging.getLogger("careloop.setup").info(
            "%s schema ready (version=%s, initialized=%s)",
            component, result["schema_version"], result["initialized"],
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        prepare_deployment()
    except (psycopg.Error, ValueError, RuntimeError, OSError):
        raise SystemExit("Database setup failed; application startup is blocked. Check PostgreSQL access and schema compatibility.") from None
