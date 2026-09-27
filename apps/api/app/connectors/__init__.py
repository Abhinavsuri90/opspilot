"""Connector registry. Every external side effect in OpsPilot goes through one of these."""

from collections.abc import Callable

from app.connectors.base import Connector, ConnectorConfigError
from app.connectors.csv_export import CsvExportConnector
from app.connectors.google_sheets import GoogleSheetsConnector
from app.connectors.postgres_table import PostgresTableConnector
from app.connectors.webhook import WebhookConnector
from app.workflow_config import ACTION_TYPE_CONNECTORS

_REGISTRY: dict[str, Callable[[], Connector]] = {
    "webhook": WebhookConnector,
    "csv_export": CsvExportConnector,
    "postgres_table": PostgresTableConnector,
    "google_sheets": GoogleSheetsConnector,
}


def connector_types() -> list[str]:
    return list(_REGISTRY)


def get_connector(connector_type: str) -> Connector:
    factory = _REGISTRY.get(connector_type)
    if factory is None:
        raise ConnectorConfigError(f"Unknown connector type: {connector_type}")
    return factory()


def connector_type_for(action_type: str) -> str | None:
    return ACTION_TYPE_CONNECTORS.get(action_type)


__all__ = [
    "Connector",
    "ConnectorConfigError",
    "connector_type_for",
    "connector_types",
    "get_connector",
]
