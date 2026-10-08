import pytest

from app import PRESETS, create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_index_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"SFD" in r.data and b"app.js" in r.data
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_health(client):
    assert client.get("/api/health").get_json()["status"] == "ok"


def test_solve_object_form_with_series(client):
    r = client.post("/api/solve", json={
        "kind": "simply_supported", "length": 6, "EI": 1000,
        "point_loads": [{"P": 10, "x": 2}],
    })
    body = r.get_json()
    assert r.status_code == 200
    assert body["reactions"]["R_A"] == pytest.approx(10 * 4 / 6)
    s = body["series"]
    assert len(s["x"]) == len(s["moment"]) == len(s["deflection"]) > 100
    assert body["max_deflection"]["value"] < 0
    assert body["segments"] and body["working"]


def test_solve_legacy_list_form(client):
    r = client.post("/api/solve", json={"length": 4, "udls": [[5, 0, 4]], "series": False})
    body = r.get_json()
    assert body["reactions"]["R_B"] == pytest.approx(10)
    assert "series" not in body


def test_solve_varying_load_and_fixed_beam(client):
    r = client.post("/api/solve", json={
        "kind": "fixed_fixed", "length": 10, "distributed": [{"w1": 3, "w2": 3, "a": 0, "b": 10}],
    })
    assert r.get_json()["support_moments"]["M_A"] == pytest.approx(-25, rel=1e-3)


@pytest.mark.parametrize("payload, msg", [
    ({"length": "abc"}, "number"),
    ({"length": 5, "point_loads": [{"P": 1, "x": 9}]}, "outside the beam"),
    ({"length": 5, "kind": "nope"}, "Unknown beam type"),
    ({"length": 5, "EI": -1}, "EI"),
    ({"length": 5, "point_loads": [{"P": 1, "x": 1}] * 51}, "At most"),
    ({"length": 5, "point_loads": "x"}, "must be a list"),
])
def test_solve_validation(client, payload, msg):
    r = client.post("/api/solve", json=payload)
    assert r.status_code == 400 and msg in r.get_json()["error"]


def test_solve_requires_json(client):
    r = client.post("/api/solve", data="hello")
    assert r.status_code == 400


def test_pdf_report(client):
    p = dict(PRESETS["overhang"], units={"force": "kN", "length": "m"}, title="My beam")
    r = client.post("/api/report.pdf", json=p)
    assert r.status_code == 200 and r.data[:4] == b"%PDF"
    assert "My-beam.pdf" in r.headers["Content-Disposition"]


def test_csv_export(client):
    r = client.post("/api/export.csv", json=dict(PRESETS["cantilever"], units={"force": "N", "length": "mm"}))
    lines = r.data.decode().splitlines()
    assert lines[0].startswith("x (mm),V (N)") and "deflection (mm)" in lines[0]
    assert len(lines) > 1000


@pytest.mark.parametrize("key", list(PRESETS))
def test_presets_solve(client, key):
    assert client.post("/api/solve", json=PRESETS[key]).status_code == 200
