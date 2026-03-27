#!/usr/bin/env python
from dataclasses import dataclass, field
from glob import glob
import io
from jinja2 import Environment, FileSystemLoader
from jsonschema import validate, ValidationError
import logging
import os
from packaging.version import Version
from pathlib import Path
import re
import subprocess
import sys
import yaml
from .schema import SCHEMA

__version__ = "1.6.0"

"""
Build docker images for use in kubernetes deployments.

The script uses a file named images.yaml file to describe what images to build and what deployments to patch
with new tags. Built image will also have some labels with metadata defined.
The yaml-file can use facts using the ninja2 template forms {{ name }}.
Format of the file is:
images:
  - directory: "build-directory"
    name: "image name"
    tags:
      - "tree-{{ treeHash }}"
    labels:
      - name: com.mydomain.repository
        value: "{{ repository }}"
    buildArgs:
      - name: "build-arg-name"
        value: "build-arg-value"
  . . .
"""


@dataclass
class Image:
    name: str  # Basename of image, including host, port, namespace and repo
    tag: str
    facts: dict[str, str]
    fullname: str = field(init=False)
    def __post_init__(self):
        self.fullname = self.name + ":" + self.tag

class ImageBuilder:
    """Holds the context during the whole build for all images and specs."""
    def __init__(self, images_file:str = "images.yaml") -> None:
        self._images_file = images_file
        self._top = Path(os.path.dirname(images_file))
        self._spec: dict[str, object] | None = None
        self._facts: dict[str, str] | None = dict()
        self.get_facts()

    @staticmethod
    def command(cmd: list[str]) -> str:
        return subprocess.run(cmd, stdout=subprocess.PIPE, check=True).stdout.decode().strip()

    @staticmethod
    def get_tree_hash(dir: Path) -> str:
        dir = f"./{dir}" if not dir.is_absolute() else str(dir)  # Needed since Path strips "./"
        tree_hash = ImageBuilder.command(["git", "-C", dir, "rev-parse", "HEAD:./"])
        dirty = subprocess.run(["git", "-C", dir, "diff", "--quiet", "HEAD", "./"]).returncode != 0
        logging.debug(f"Image dir {dir} is dirty")
        return (tree_hash + "-dirty" if dirty else tree_hash, dirty)

    def get_facts(self) -> None:
        """calculate various facts that can be used in the images.yaml file"""
        f = self._facts
        f["branch"] = self.command(["git", "branch", "--show-current"])
        f["remote"] = self.command(["git", "config", f"branch.{f['branch']}.remote"])
        f["commit"] = self.command(["git", "rev-parse", "HEAD"])
        f["repositoryFull"] = self.command(["git", "remote", "get-url", f["remote"]])
        f["repository"] = re.sub(r"//.*@", "//", f["repositoryFull"])  # Drop user info
        (f["topTreeHash"], _) = self.get_tree_hash(self._top)
        f["top"] = str(self._top)
        f["login"] = os.getlogin()
        # Theese needs to be expanded per image at a later stage:
        f["treeHash"] = "{treeHash}"
        f["name"] = "{name}"
        f["tag"] = "{tag}"
        f["tag0"] = "{tag}"
        f["tag1"] = "{tag1}"
        f["tag2"] = "{tag2}"
        f["tag3"] = "{tag3}"

    def load_spec(self) -> None:
        env = Environment(loader=FileSystemLoader("."))
        template = env.get_template(str(self._images_file))
        rendered = template.render(**self._facts)

        with io.StringIO(rendered) as fin:
            self._spec: dict = yaml.safe_load(fin)

        validate(instance=self._spec, schema=SCHEMA)
        if "schemaVersion" in self._spec:
            if Version(self._spec["schemaVersion"]) > Version(__version__):
                raise ValueError("You need version {self._spec['schemaVersion']} of buildimage")

    def build_images(self, images_to_build: list[str] = None, quiet: bool = True) -> None:
        """Builds all images and returns a list of built Image objects."""
        build_result: dict[str, list[Image]] = dict()
        for img in self._spec["images"]:
            if images_to_build and img["name"] not in images_to_build:
                continue

            image_dir = Path(img["directory"])
            if not image_dir.is_absolute():
                image_dir = self._facts["top"] / image_dir

            docker_file = image_dir / (img.get("dockerFile") or "Dockerfile")

            image_facts: dict[str, str] = dict()
            (image_facts["treeHash"], image_facts["dirty"]) = self.get_tree_hash(image_dir)
            image_facts["name"] = img["name"]

            labels = [
                # This will make the images.yaml file usage traceable from the image.
                "--label", f"org.opencontainers.image.topTreeHash={self._facts['topTreeHash']}",
                "--label", f"org.opencontainers.image.source={self._facts['repository']}",
                "--label", f"org.opencontainers.image.revision={self._facts['commit']}",
                "--label", f"org.opencontainers.image.user={self._facts['login']}",
                "--label", f"org.opencontainers.image.buildimage={__version__}",
            ]
            for b in img.get("labels") or []:
                labels.extend(["--label", f"{b['name']}={b['value'].format(**image_facts)}"])

            buildargs = []
            for b in img.get("buildArgs") or []:
                buildargs.extend(["--build-arg", f"{b['name']}={b['value'].format(**image_facts)}"])

            image_list: list[Image] = []
            for tag_no, tag in enumerate(img["tags"]):
                tag = tag.format(**image_facts)
                image_facts[f"tag{tag_no}"] = tag
                i = Image(img["name"], tag, image_facts)
                if len(image_list) == 0:
                    cmd = ["docker", "build", "-t", i.fullname]
                    cmd += buildargs
                    cmd += labels
                    cmd += ["-f", str(docker_file)]
                    if quiet:
                        cmd += ["--quiet"]
                    cmd += [str(image_dir)]
                    logging.debug(f"Building {i.fullname} in {image_dir} with: {' '.join(cmd)}")
                    subprocess.run(cmd, check=True)
                else:
                    cmd = ["docker", "tag", image_list[0].fullname, i.fullname]
                    logging.debug(f"Tagging {i.fullname} with: {' '.join(cmd)}")
                    subprocess.run(cmd, check=True)

                image_list.append(i)

            image_facts[f"tag"] = image_facts[f"tag0"]

            build_result[img["name"]] = image_list

        if len(build_result) == 0:
            raise RuntimeError("No images found to build.")

        return build_result

    def update_deployments(self, build_result: dict[str, list[Image]]) -> set[str]:
        """Update deployments with new tags."""
        modified_files: set[str] = set()
        for img in self._spec["images"]:
            if img["name"] not in build_result:
                continue

            logging.debug(f"updating deployment for {img['name']}")
            i = build_result[img["name"]][0]  # Use first built image data only.
            for deployment in (img.get("deployments") or []):
                if "path" in deployment:
                    modified_files.update(self.update_file_deployment(deployment, i.facts))
                elif "kustomize" in deployment:
                    modified_files.update(self.update_kustomize_deployment(deployment, i.facts))

        return modified_files

    def update_file_deployment(self, deployment: dict, facts: dict[str, str]) -> set:
        """Simple sed style patching of a file."""
        paths = glob(str(self._top / deployment["path"].format(**facts)))
        match = re.compile(deployment["match"].format(**facts))
        replace = (deployment.get("replace") or "{tag}").format(**facts)
        modified_files: set[str] = set()

        for path in paths:
            lines = []
            with open(path) as fin:
                for line in fin:
                    new_line = match.sub(replace, line)
                    lines.append(new_line)
                    if new_line != line:
                        modified_files.add(path)

            with open(path, "w") as fout:
                for l in lines:
                    fout.write(l)
        return modified_files

    def update_kustomize_deployment(self, deployment: dict, facts: dict[str, str]) -> set:
        from ruamel.yaml import YAML
        modified = False
        yaml = YAML()
        yaml.preserve_quotes = True  # optional, keeps quotes

        kustomize_file = Path(deployment["kustomize"])
        if not kustomize_file.is_absolute():
            kustomize_file = self._top / kustomize_file

        with kustomize_file.open() as f:
            kustomize_data = yaml.load(f)

        # Modify a specific value
        image_name = deployment.get("name") or facts["name"]
        for kustomize_image in kustomize_data["images"]:
            if kustomize_image["name"] == image_name:
                raw_tag = deployment.get("newTag") or "{tag}"
                old_tag = kustomize_image["newTag"]
                kustomize_image["newTag"] = raw_tag.format(**facts)
                modified = (old_tag != kustomize_image["newTag"])
                break
        else:
            raise RuntimeError(f"Could not find image {image_name} in {kustomize_file}")

        with  kustomize_file.open("w") as f:
            yaml.dump(kustomize_data, f)

        return {deployment["kustomize"]} if modified else set()
