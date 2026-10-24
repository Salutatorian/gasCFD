import struct

import numpy as np

from app.airfield import q_criterion, slice_bytes, vortex_bytes


def test_spin_is_positive_and_plain_shear_is_not():
    axis = np.linspace(-1.0, 1.0, 12)
    dx = float(axis[1] - axis[0])
    x, y, z = np.meshgrid(axis, axis, axis, indexing="ij")
    spinning = q_criterion(-y, x, np.zeros_like(z), dx)
    shear = q_criterion(y, np.zeros_like(y), np.zeros_like(z), dx)
    assert float(spinning.mean()) > 0.2
    assert abs(float(shear.mean())) < 0.05


def test_vortex_tube_becomes_a_surface_and_slice_is_one_fine_cut():
    axis = np.linspace(-1.2, 1.2, 22)
    dx = float(axis[1] - axis[0])
    x, y, z = np.meshgrid(axis, axis, axis, indexing="ij")
    core = np.exp(-8.0 * (x * x + y * y))
    mask = np.zeros(x.shape, np.uint8)
    origin = np.array([axis[0], axis[0], axis[0]], dtype=np.float64)
    raw = vortex_bytes(mask, origin, dx, -y * core, x * core, np.zeros_like(z), np.full(x.shape, 6.0), 10.0)
    vertices, triangles = struct.unpack_from("<II", raw, 0)
    assert vertices > 8
    assert triangles > 8
    points = np.frombuffer(raw, dtype=np.float32, count=vertices * 3, offset=8).reshape(vertices, 3)
    assert abs(float(points[:, 0].mean())) < 0.4
    assert abs(float(points[:, 1].mean())) < 0.4
    assert float(points[:, 2].max() - points[:, 2].min()) > 0.6
    sliced = slice_bytes(origin, dx, np.ones(x.shape, np.float32), mask)
    planes = struct.unpack_from("<I", sliced, 0)[0]
    assert planes == 1
    nu, nv = struct.unpack_from("<II", sliced, 24)
    assert nu == x.shape[0] * 4
    assert nv == x.shape[2] * 4
