"""Smoke test: verifies the package layout is importable by the suite."""


def test_packages_importable():
    import common.helper  # noqa: F401
    import rangermodels.ranger_models  # noqa: F401
    import servicefinder.node_selector  # noqa: F401
    import serviceprovider.health_check  # noqa: F401
