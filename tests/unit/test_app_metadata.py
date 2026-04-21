from app import APP_NAME, __version__


def test_package_metadata():
    assert APP_NAME == "MendCode"
    assert __version__ == "0.1.0"
