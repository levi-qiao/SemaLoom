from __future__ import annotations

from fastapi.testclient import TestClient

from semaloom.app.factory import create_app


def test_studio_session_can_read_published_data_with_csrf_and_current_roles() -> None:
    with TestClient(create_app(load_fixtures=True)) as client:
        login = client.post("/v0.1/studio/session/demo", json={"persona": "studio-admin"})
        assert login.status_code == 200
        headers = {"Origin": "http://testserver", "X-CSRF-Token": client.cookies["semaloom_csrf"]}
        body = {
            "metric": "tax.reportedIncome",
            "bindings": {"taxpayerId": "TAXPAYER-A", "taxYear": 2024},
            "periodFrom": "2024-01-01",
            "periodTo": "2025-01-01",
        }
        result = client.post("/v0.1/query", json=body, headers=headers)
        assert result.status_code == 200
        obs = result.json()["observations"][0]
        assert obs["kind"] == "PRESENT" and obs["unit"] == "CNY" and obs["valueType"] == "DECIMAL"
        assert (
            client.get("/v0.1/describe", params={"semanticId": "tax.reportedIncome"}).status_code
            == 200
        )
        assert client.post("/v0.1/query", json=body).status_code == 403
        assert (
            client.post(
                "/v0.1/query", json=body, headers={**headers, "Origin": "https://untrusted.example"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/v0.1/query", json=body, headers={**headers, "Authorization": "Bearer invalid"}
            ).status_code
            == 401
        )
        claim = client.post(
            "/v0.1/claims/evaluate",
            headers=headers,
            json={
                "claimId": "tax.incomeReconciles",
                "bindings": body["bindings"],
                "periodFrom": body["periodFrom"],
                "periodTo": body["periodTo"],
                "dimensions": {"jurisdiction": "CN"},
            },
        )
        assert claim.status_code == 200 and claim.json()["claim"]["truth"] == "TRUE"
        assert client.delete("/v0.1/studio/session", headers=headers).status_code == 200
        assert client.post("/v0.1/query", json=body, headers=headers).status_code == 401
        client.post("/v0.1/studio/session/demo", json={"persona": "viewer"})
        headers["X-CSRF-Token"] = client.cookies["semaloom_csrf"]
        forbidden = client.post("/v0.1/query", json=body, headers=headers)
        assert forbidden.json()["observations"][0]["kind"] == "FORBIDDEN"
        assert client.get("/v0.1/search", params={"q": "收入"}).status_code == 403
