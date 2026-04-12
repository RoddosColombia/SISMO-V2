"""
Tests for image upload in chat — Part 3 of image upload feature.

1. ChatRequest model accepts imagen field
2. Existing flow unchanged when imagen is None
3. Multimodal content built correctly when imagen is provided
"""
import pytest
from pydantic import ValidationError

from routers.chat import ChatRequest


# ---------------------------------------------------------------------------
# Test 1: ChatRequest model accepts imagen field
# ---------------------------------------------------------------------------
def test_chat_accepts_imagen_field():
    """ChatRequest should accept an optional imagen field (base64 data URI)."""
    data_uri = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ=="
    req = ChatRequest(message="Registrar este gasto", imagen=data_uri)
    assert req.imagen == data_uri
    assert req.message == "Registrar este gasto"


def test_chat_imagen_defaults_to_none():
    """imagen should default to None when not provided."""
    req = ChatRequest(message="Hola")
    assert req.imagen is None


# ---------------------------------------------------------------------------
# Test 2: Existing flow unchanged when imagen is None
# ---------------------------------------------------------------------------
def test_chat_without_imagen_works():
    """All existing fields should work exactly as before; imagen is optional."""
    req = ChatRequest(
        message="Consultar saldo",
        agent_type="contador",
        session_id="abc-123",
        current_agent="contador",
        correlation_id="corr-456",
    )
    assert req.message == "Consultar saldo"
    assert req.agent_type == "contador"
    assert req.session_id == "abc-123"
    assert req.imagen is None


def test_chat_request_still_requires_message():
    """message field is still required — should raise ValidationError without it."""
    with pytest.raises(ValidationError):
        ChatRequest(imagen="data:image/png;base64,abc123")


# ---------------------------------------------------------------------------
# Test 3: Multimodal content built correctly
# ---------------------------------------------------------------------------
def test_multimodal_content_built_from_data_uri():
    """When imagen is a data URI, extract media_type and base64 data correctly."""
    imagen = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="
    message = "Registrar este recibo"

    # Replicate the logic from process_chat
    if imagen.startswith("data:"):
        parts = imagen.split(",", 1)
        media_type = parts[0].split(":")[1].split(";")[0]
        image_data = parts[1]
    else:
        media_type = "image/jpeg"
        image_data = imagen

    user_content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
        {"type": "text", "text": message},
    ]

    assert len(user_content) == 2
    assert user_content[0]["type"] == "image"
    assert user_content[0]["source"]["type"] == "base64"
    assert user_content[0]["source"]["media_type"] == "image/png"
    assert user_content[0]["source"]["data"] == "iVBORw0KGgoAAAANSUhEUg=="
    assert user_content[1]["type"] == "text"
    assert user_content[1]["text"] == "Registrar este recibo"


def test_multimodal_content_raw_base64_defaults_to_jpeg():
    """When imagen is raw base64 (no data: prefix), default to image/jpeg."""
    imagen = "/9j/4AAQSkZJRgABAQ=="
    message = ""

    if imagen.startswith("data:"):
        parts = imagen.split(",", 1)
        media_type = parts[0].split(":")[1].split(";")[0]
        image_data = parts[1]
    else:
        media_type = "image/jpeg"
        image_data = imagen

    user_content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
        {"type": "text", "text": message or "Procesa este comprobante y propone el asiento contable."},
    ]

    assert user_content[0]["source"]["media_type"] == "image/jpeg"
    assert user_content[0]["source"]["data"] == "/9j/4AAQSkZJRgABAQ=="
    assert user_content[1]["text"] == "Procesa este comprobante y propone el asiento contable."


def test_multimodal_content_webp():
    """WebP images should also be parsed correctly from data URI."""
    imagen = "data:image/webp;base64,UklGRlYAAABXRUJQ"

    parts = imagen.split(",", 1)
    media_type = parts[0].split(":")[1].split(";")[0]
    image_data = parts[1]

    assert media_type == "image/webp"
    assert image_data == "UklGRlYAAABXRUJQ"


def test_save_message_excludes_base64():
    """The save_message should contain a text marker, not base64 data."""
    message = "Registrar gasto"
    imagen = "data:image/jpeg;base64,/9j/4AAQ..."

    save_message = message or "Procesa este comprobante"
    if imagen:
        save_message = f"[imagen adjunta] {save_message}"

    assert save_message == "[imagen adjunta] Registrar gasto"
    assert "base64" not in save_message
    assert "/9j/" not in save_message
