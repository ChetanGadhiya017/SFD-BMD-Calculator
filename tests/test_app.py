import pytest

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_index_renders_example(client):
    r = client.get("/?example=overhang")
    assert r.status_code == 200 and b"Calculate" in r.data


def test_form_post_returns_results_and_plot(client):
    r = client.post("/", data={
        "kind": "simply_supported", "length": "6", "support_a": "0", "support_b": "6",
        "pl_p": ["10"], "pl_x": ["2"], "udl_w": [""], "udl_a": [""], "udl_b": [""],
        "force_unit": "kN", "length_unit": "m",
    })
    assert r.status_code == 200
    assert b"data:image/png;base64" in r.data
    assert b"6.667" in r.data  # R_A = 10*4/6


def test_form_post_invalid_beam(client):
    r = client.post("/", data={"kind": "simply_supported", "length": "5", "pl_p": ["1"], "pl_x": ["9"]})
    assert r.status_code == 400 and b"outside the beam" in r.data


def test_json_api(client):
    r = client.post("/api/solve", json={"length": 4, "udls": [[5, 0, 4]]})
    body = r.get_json()
    assert r.status_code == 200
    assert body["reactions"]["R_A"] == pytest.approx(10)
    assert body["max_sagging_moment"]["value"] == pytest.approx(10, rel=1e-3)


def test_json_api_error(client):
    r = client.post("/api/solve", json={"length": "abc"})
    assert r.status_code == 400 and "number" in r.get_json()["error"]
