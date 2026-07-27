import asyncio
import os
import unittest

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["USER_CONTENT_DIR"] = "/tmp/protracklite-test-user-content"

from fastapi import HTTPException
from starlette.requests import Request

from app.main import http_exception_handler
from app.security import create_refresh_token


def browser_request(path: str, query: str = "", refresh_token: str = "") -> Request:
    headers = [(b"accept", b"text/html")]
    if refresh_token:
        headers.append((b"cookie", f"refresh_token={refresh_token}".encode()))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "server": ("tasks.omnihire.in", 443),
            "client": ("127.0.0.1", 12345),
            "root_path": "",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "headers": headers,
        }
    )


class BrowserAuthRedirectTests(unittest.TestCase):
    def test_valid_refresh_cookie_renews_access_and_returns_to_requested_page(self):
        refresh_token = create_refresh_token("12:solulever")
        request = browser_request("/solulever/lists", "list_id=5", refresh_token)

        response = asyncio.run(
            http_exception_handler(request, HTTPException(status_code=401, detail="Authentication required"))
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/solulever/lists?list_id=5")
        set_cookie_headers = [
            value.decode() for name, value in response.raw_headers if name.lower() == b"set-cookie"
        ]
        self.assertTrue(any(cookie.startswith("access_token=") for cookie in set_cookie_headers))
        self.assertFalse(any(cookie.startswith("refresh_token=") for cookie in set_cookie_headers))

    def test_missing_refresh_cookie_redirects_to_organization_login(self):
        request = browser_request("/solulever/lists", "list_id=5")

        response = asyncio.run(
            http_exception_handler(request, HTTPException(status_code=401, detail="Authentication required"))
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/solulever/login")

    def test_refresh_cookie_cannot_cross_organizations(self):
        refresh_token = create_refresh_token("12:another-org")
        request = browser_request("/solulever/lists", "list_id=5", refresh_token)

        response = asyncio.run(
            http_exception_handler(request, HTTPException(status_code=401, detail="Authentication required"))
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/solulever/login")


if __name__ == "__main__":
    unittest.main()
