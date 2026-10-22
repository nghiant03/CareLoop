from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute

from backend.app.api.chat import ChatResponse, router


def test_chat_openapi_documents_request_response_and_identity_errors():
    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()
    operation = schema["paths"]["/chat"]["post"]
    models = schema["components"]["schemas"]

    request = models["ChatRequest"]
    assert request["required"] == ["message"]
    assert request["additionalProperties"] is False
    assert "anonymous" in request["properties"]["patient_id"]["description"]
    assert "latest proposal" in request["properties"]["envelope_id"]["description"]

    responses = operation["responses"]
    assert responses["200"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/ChatResponse"
    )
    assert set(models["ChatResponse"]["required"]) == {
        "answer", "claims", "citations", "escalated", "status",
    }
    assert models["ChatResponse"]["properties"]["status"]["enum"] == [
        "answered", "refused", "escalated",
    ]
    assert {"type": "null"} in models["ChatCitation"]["properties"]["url"]["anyOf"]
    assert "not found" in responses["404"]["description"]
    assert "differs" in responses["409"]["description"]
    assert "422" in responses
    assert "approved values" in operation["description"]


def test_chat_response_model_is_documentation_only():
    route = next(route for route in router.routes if isinstance(route, APIRoute) and route.path == "/chat")
    assert route.response_model == dict[str, Any]
    assert route.responses[200]["model"] is ChatResponse
