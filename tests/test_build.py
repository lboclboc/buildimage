import pytest
import buildimage
import sys


def test_load_spec():
    builder = buildimage.ImageBuilder("./docker")
    builder.load_spec()
    assert len(builder._spec) == 1
    assert builder._spec["images"][0]["name"] == "harbor.mycompany.com/library/test-image"
    assert builder._spec["images"][0]["directory"] == "."
    assert builder._spec["images"][0]["labels"][0]["value"] == "https://github.com/lboclboc/buildimage.git"
    assert builder._spec["images"][0]["buildArgs"][0]["value"] == "root"

def test_build():
    builder = buildimage.ImageBuilder("./docker")
    builder.load_spec()
    builder.build_images()