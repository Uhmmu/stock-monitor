from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth_routes import router


def test_reddit_oauth_callback_is_public_html_placeholder():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get('/api/auth/reddit/callback')

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/html')
    assert response.headers['cache-control'] == 'no-store'
    assert '<title>Reddit OAuth Callback</title>' in response.text
    assert 'This endpoint is reserved for Reddit OAuth authentication.' in response.text
    assert 'No user action is required.' in response.text
