"""Library generations of the PML route: dense only / WP-PML5a (mlfmm, no dict) / WP-PML5b (mlfmm dict)."""

import types

import pytest

from sbgui.checks import capability_issues
from sbgui.config import default_config
from sbgui.worker import library_features

SIG = ("with_pml(open_mesh: specklebem._specklebem.OpenSurfaceMesh, excitation: specklebem._specklebem.Excitation, *, "
       "pml: Optional[specklebem._specklebem.PmlTermination] = None, object: specklebem._specklebem.Material, "
       "exterior: Optional[specklebem._specklebem.Material] = None, wavelength: Optional[float] = None, "
       "formulation: object = 'auto', preconditioner: str = 'auto', solver: str = 'gmres', compression: str = 'dense', "
       "gmres: Optional[dict] = None, kernels: Optional[dict] = None{extra}) -> specklebem._specklebem.Simulation\n\n")
DOCS = {  # bodies as in python/src/bind_simulation.cpp at b960d4b^, b960d4b and 9b8123a
    "dense_only": SIG.format(extra="") + 'As for Simulation(); compression must be "dense" (the MLFMM does not '
                                         "support the PML).",
    "pml5a": SIG.format(extra="") + 'Simulation of an open surface terminated by a PML (ADR 0009; dense, or "mlfmm" '
                                    "since WP-PML5a).",
    "pml5b": SIG.format(extra=", mlfmm: Optional[dict] = None") + 'Simulation of an open surface terminated by a PML '
                                                                   '(ADR 0009; dense, or "mlfmm" since WP-PML5a).',
}


def fake_sb(doc):
    def with_pml(*a, **k):
        pass

    with_pml.__doc__ = doc
    return types.SimpleNamespace(Simulation=types.SimpleNamespace(with_pml=with_pml), make_open_surface_mesh=1)


@pytest.mark.parametrize("gen,mlfmm,params", [("dense_only", False, False), ("pml5a", True, False),
                                              ("pml5b", True, True)])
def test_feature_probes_tell_the_generations_apart(gen, mlfmm, params):
    f = library_features(fake_sb(DOCS[gen]), have_h5py=False)
    assert f["pml"] and f["pml_mlfmm"] == mlfmm and f["pml_mlfmm_params"] == params


def test_pre_flight_per_generation():
    cfg = default_config()
    cfg["solver"]["compression"] = "mlfmm"
    meta = {"termination": "pml"}

    def levels(gen):
        caps = {"features": library_features(fake_sb(DOCS[gen]), have_h5py=False)}
        return [i.level for i in capability_issues(cfg, caps, meta, 100_000)]

    assert levels("dense_only") == ["error"]
    assert levels("pml5a") == ["warning"]  # the reported build: runs, settings ignored, exact ring
    assert levels("pml5b") == []
    cfg["solver"]["compression"] = "dense"
    assert [i.level for i in capability_issues(cfg, {"features": library_features(fake_sb(DOCS["dense_only"]),
                                                                                    False)}, meta, 5000)] == []
    assert capability_issues(cfg, None, {"termination": "box"}, 5000) == []
