"""
Tests for AlegraClient — request_with_verify() pattern (FOUND-06).

Rules verified:
- POST -> GET verify -> return record with id
- 422/4xx errors translated to Spanish messages
- /journal-entries NEVER in source code
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx


@pytest.mark.asyncio
async def test_request_with_verify_success():
    """POST returns 201, GET confirms existence."""
    from services.alegra.client import AlegraClient

    mock_db = MagicMock()
    client = AlegraClient(db=mock_db)

    post_response = MagicMock(spec=httpx.Response)
    post_response.status_code = 201
    post_response.raise_for_status = MagicMock()
    post_response.json = MagicMock(return_value={"id": "J-999", "date": "2026-04-01"})

    get_response = MagicMock(spec=httpx.Response)
    get_response.status_code = 200
    get_response.raise_for_status = MagicMock()
    get_response.json = MagicMock(return_value={"id": "J-999", "date": "2026-04-01"})

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=post_response)
    mock_http.get = AsyncMock(return_value=get_response)

    with patch("services.alegra.client.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await client.request_with_verify(
            endpoint="journals",
            method="POST",
            payload={"date": "2026-04-01", "observations": "test"},
        )

    assert result["id"] == "J-999"
    mock_http.post.assert_called_once()
    mock_http.get.assert_called_once()


@pytest.mark.asyncio
async def test_request_with_verify_alegra_error_returns_spanish():
    """Alegra 422 must produce Spanish error, not raw HTTP status."""
    from services.alegra.client import AlegraClient, AlegraError

    mock_db = MagicMock()
    client = AlegraClient(db=mock_db)

    error_response = MagicMock(spec=httpx.Response)
    error_response.status_code = 422
    error_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "422", request=MagicMock(), response=error_response
        )
    )
    error_response.json = MagicMock(return_value={"message": "Invalid entry"})

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=error_response)

    with patch("services.alegra.client.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

        with pytest.raises(AlegraError) as exc:
            await client.request_with_verify(
                endpoint="journals",
                method="POST",
                payload={},
            )

    # Error must be in Spanish, not "422 Unprocessable Entity"
    assert any(word in str(exc.value).lower()
               for word in ["alegra", "datos", "error", "registro"])
    assert "422" not in str(exc.value)


@pytest.mark.asyncio
async def test_request_with_verify_get_fails_raises_alegra_error():
    """When GET verification fails, AlegraError is raised with Spanish message."""
    from services.alegra.client import AlegraClient, AlegraError

    mock_db = MagicMock()
    client = AlegraClient(db=mock_db)

    post_response = MagicMock(spec=httpx.Response)
    post_response.status_code = 201
    post_response.raise_for_status = MagicMock()
    post_response.json = MagicMock(return_value={"id": "J-123"})

    get_response = MagicMock(spec=httpx.Response)
    get_response.status_code = 404
    get_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "404", request=MagicMock(), response=get_response
        )
    )

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=post_response)
    mock_http.get = AsyncMock(return_value=get_response)

    with patch("services.alegra.client.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

        with pytest.raises(AlegraError) as exc:
            await client.request_with_verify(
                endpoint="journals",
                method="POST",
                payload={"date": "2026-04-01"},
            )

    assert "verificaci" in str(exc.value).lower() or "registro" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_never_uses_journal_entries():
    """Ensure the client module never references /journal-entries."""
    import inspect
    from services.alegra import client as alegra_module
    source = inspect.getsource(alegra_module)
    assert "journal-entries" not in source, "NUNCA usar /journal-entries — usa /journals"


@pytest.mark.asyncio
async def test_spanish_error_for_401():
    """401 Unauthorized must produce Spanish message."""
    from services.alegra.client import AlegraClient, AlegraError

    mock_db = MagicMock()
    client = AlegraClient(db=mock_db)

    error_response = MagicMock(spec=httpx.Response)
    error_response.status_code = 401
    error_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "401", request=MagicMock(), response=error_response
        )
    )

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=error_response)

    with patch("services.alegra.client.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

        with pytest.raises(AlegraError) as exc:
            await client.request_with_verify(
                endpoint="journals",
                method="POST",
                payload={},
            )

    error_msg = str(exc.value).lower()
    assert "token" in error_msg or "alegra" in error_msg
    assert "401" not in str(exc.value)


@pytest.mark.asyncio
async def test_alegra_base_url_is_correct():
    """Base URL must be https://api.alegra.com/api/v1."""
    from services.alegra.client import ALEGRA_BASE_URL
    assert ALEGRA_BASE_URL == "https://api.alegra.com/api/v1"
