import math

import pytest

from beam_solver import UDL, Beam, BeamError, MomentLoad, PointLoad, solve


def approx(a, b, tol=1e-3):
    return math.isclose(a, b, rel_tol=tol, abs_tol=tol)


def m_at(res, x):
    i = int(abs(res.x - x).argmin())
    return float(res.moment[i])


def test_simply_supported_central_point_load():
    # Classic: R = P/2, Mmax = PL/4 at midspan
    r = solve(Beam(8, point_loads=[PointLoad(20, 4)]))
    assert approx(r.reactions["R_A"], 10) and approx(r.reactions["R_B"], 10)
    v, x = r.max_moment
    assert approx(v, 40) and approx(x, 4)
    assert approx(m_at(r, 0), 0) and approx(m_at(r, 8), 0)


def test_simply_supported_eccentric_point_load():
    # R_A = Pb/L, R_B = Pa/L, Mmax = Pab/L under the load
    r = solve(Beam(6, point_loads=[PointLoad(10, 2)]))
    assert approx(r.reactions["R_A"], 10 * 4 / 6)
    assert approx(r.reactions["R_B"], 10 * 2 / 6)
    assert approx(r.max_moment[0], 10 * 2 * 4 / 6)
    assert approx(abs(r.max_shear[0]), 10 * 4 / 6)


def test_simply_supported_full_udl():
    # R = wL/2, Mmax = wL^2/8 at midspan, V varies linearly
    r = solve(Beam(4, udls=[UDL(5, 0, 4)]))
    assert approx(r.reactions["R_A"], 10) and approx(r.reactions["R_B"], 10)
    v, x = r.max_moment
    assert approx(v, 5 * 16 / 8) and approx(x, 2)
    assert approx(float(r.shear[int(abs(r.x - 2).argmin())]), 0, 1e-2)


def test_partial_udl_shear_stays_constant_after_load():
    # The original app reset shear to zero after a UDL ended — wrong.
    r = solve(Beam(10, udls=[UDL(2, 0, 5)]))
    ra, rb = r.reactions["R_A"], r.reactions["R_B"]
    assert approx(ra + rb, 10) and approx(rb, 2.5)
    i = int(abs(r.x - 8).argmin())
    assert approx(float(r.shear[i]), ra - 10)


def test_cantilever_tip_load():
    r = solve(Beam(3, kind="cantilever", point_loads=[PointLoad(4, 3)]))
    assert approx(r.reactions["R_A"], 4)
    assert approx(r.fixed_end_moment, -12)
    assert approx(r.min_moment[0], -12) and approx(r.min_moment[1], 0)
    assert approx(m_at(r, 3), 0)


def test_cantilever_udl():
    r = solve(Beam(2, kind="cantilever", udls=[UDL(3, 0, 2)]))
    assert approx(r.fixed_end_moment, -3 * 4 / 2)
    assert approx(m_at(r, 2), 0)


def test_applied_moment_on_simple_beam():
    # Clockwise couple M0 at midspan: R_A = -M0/L, R_B = M0/L, jump of M0 in BMD
    r = solve(Beam(4, moments=[MomentLoad(8, 2)]))
    assert approx(r.reactions["R_A"], -2) and approx(r.reactions["R_B"], 2)
    assert approx(r.min_moment[0], -4) and approx(r.max_moment[0], 4)


def test_overhanging_beam_has_contraflexure():
    # Supports at 0 and 4, beam 6 long, UDL everywhere + tip load
    b = Beam(6, support_a=0, support_b=4, udls=[UDL(2, 0, 6)], point_loads=[PointLoad(3, 6)])
    r = solve(b)
    assert approx(r.reactions["R_A"] + r.reactions["R_B"], 15)
    # Hogging over support B: M = -(w*2^2/2 + P*2) = -10
    assert approx(m_at(r, 4), -10)
    assert len(r.contraflexure_points) == 1
    assert approx(r.contraflexure_points[0], 1.5)
    assert approx(m_at(r, 6), 0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"length": 0},
        {"length": 5, "kind": "fixed"},
        {"length": 5, "point_loads": [PointLoad(1, 6)]},
        {"length": 5, "udls": [UDL(1, 3, 2)]},
        {"length": 5, "support_a": 3, "support_b": 2},
    ],
)
def test_invalid_beams(kwargs):
    with pytest.raises(BeamError):
        Beam(**kwargs)


def test_moment_closes_at_free_end_for_random_loads():
    b = Beam(
        12,
        point_loads=[PointLoad(7, 1.5), PointLoad(3, 9)],
        udls=[UDL(1.2, 2, 7), UDL(0.5, 6, 12)],
        moments=[MomentLoad(-4, 10)],
    )
    r = solve(b)
    assert abs(m_at(r, 0)) < 1e-6 and abs(m_at(r, 12)) < 1e-6


def test_jump_from_applied_moment_is_not_contraflexure():
    r = solve(Beam(6, support_a=0, support_b=4.5, udls=[UDL(2, 0, 6)],
                   point_loads=[PointLoad(10, 2), PointLoad(3, 6)], moments=[MomentLoad(5, 3.5)]))
    assert all(abs(x - 3.5) > 1e-3 for x in r.contraflexure_points)
    assert len(r.contraflexure_points) == 2


def test_cli(capsys, tmp_path):
    from beam_solver.__main__ import main

    out = tmp_path / "b.png"
    assert main(["--length", "6", "--point", "10@2", "--plot", str(out)]) == 0
    text = capsys.readouterr().out
    assert "6.667" in text and out.stat().st_size > 1000
    assert main(["--length", "5", "--point", "1@9"]) == 2
