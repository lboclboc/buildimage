import pytest
import buildimage
import buildimage.__main__
import sys
import re
import json
import os
import subprocess
import shutil

def load_image(image: str) -> dict[str, object]:
    txt = subprocess.run(["docker", "image", "inspect", image], check=True, stdout=subprocess.PIPE).stdout.decode()
    return json.loads(txt)[0]

def grep(file_path: str, pattern: str) -> bool:
    with open(file_path, 'r') as file:
        for line_number, line in enumerate(file, start=1):
            if re.search(pattern, line):
                return True
    return False

def test_load_spec():
    builder = buildimage.ImageBuilder("./docker")
    builder.load_spec()
    assert len(builder._spec) == 1
    assert builder._spec["images"][0]["name"] == "harbor.mycompany.com/library/test-image-1"
    assert builder._spec["images"][0]["directory"] == "test-image-1"
    assert builder._spec["images"][0]["labels"][0]["value"] == "https://github.com/lboclboc/buildimage.git"
    assert builder._spec["images"][0]["buildArgs"][0]["value"] == "root"

def test_build():
    builder = buildimage.ImageBuilder("./docker")
    builder.load_spec()
    build_result: dict[str, list[buildimage.Image]] = builder.build_images()

    fullname = build_result["harbor.mycompany.com/library/test-image-1"][0].fullname
    img1 = load_image(fullname)
    assert img1["Config"]["Labels"]["com.mydomain.repository"] == "https://github.com/lboclboc/buildimage.git"
    assert "com.github.lboclboc.buildimage.topTreeHash" in img1["Config"]["Labels"]
    assert "com.mydomain.repository" in img1["Config"]["Labels"]
    assert img1["RepoTags"][0] == fullname or img1["RepoTags"][1] == fullname

    img2 = load_image(build_result["harbor.mycompany.com/library/test-image-2"][0].fullname)
    assert img1["Config"]["Labels"]["com.mydomain.repository"] == "https://github.com/lboclboc/buildimage.git"
    assert "com.github.lboclboc.buildimage.topTreeHash" in img1["Config"]["Labels"]
    assert "com.mydomain.repository" in img1["Config"]["Labels"]

def test_update_deployments():
    shutil.copy("deployment/kustomize.yaml.org", "deployment/kustomize.yaml")
    builder = buildimage.ImageBuilder("./docker")
    builder.load_spec()
    build_result = builder.build_images(["harbor.mycompany.com/library/test-image-1"])
    builder.update_deployments(build_result)

def test_main():
    arg0 = os.path.join(os.path.dirname(__file__), "../src/buildimage/__init__.py")
    shutil.copy("deployment/kustomize.yaml.org", "deployment/kustomize.yaml")
    sys.argv = [arg0, "--nopush", "docker"]
    buildimage.__main__.main()
    assert grep("deployment/kustomize.yaml", "tree-")

    shutil.copy("deployment/kustomize.yaml.org", "deployment/kustomize.yaml")
    sys.argv = [arg0, "--image", "harbor.mycompany.com/library/test-image-2", "--nopush", "docker"]
    buildimage.__main__.main()
    assert not grep("deployment/kustomize.yaml", "tree-")

    shutil.copy("deployment/kustomize.yaml.org", "deployment/kustomize.yaml")
    sys.argv = [arg0, "--image", "harbor.mycompany.com/library/test-image-1", "docker"]

    with pytest.raises(subprocess.CalledProcessError):
        buildimage.__main__.main()
