"""G19: CSV export of observable arrays (no library)."""

import io

import numpy as np

from sbgui.export import observable_csv


def test_columns_scalars_vectors_and_complex():
    data = {"theta": np.linspace(0, 1, 4), "sigma": np.arange(4.0), "C_sca": np.asarray(1.5e-12),
            "plane": np.asarray("xz"), "d": np.arange(12.0).reshape(4, 3), "F": np.array([1 + 2j] * 4),
            "weights": np.ones(7)}  # other length: left out
    csv = observable_csv(data)
    lines = csv.splitlines()
    assert lines[0] == "# C_sca = 1.5e-12" and lines[1] == "# plane = xz"
    assert lines[2] == "theta,sigma,d_x,d_y,d_z,F_re,F_im"
    table = np.loadtxt(io.StringIO(csv), delimiter=",", comments="#", skiprows=3)
    assert table.shape == (4, 7) and table[3, 4] == 11.0 and table[0, 6] == 2.0


def test_no_table():
    assert observable_csv({"R": np.asarray(0.3)}) is None
    assert observable_csv({}) is None
