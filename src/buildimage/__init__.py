#!/usr/bin/env python
import argparse
from dataclasses import dataclass
import io
from jinja2 import Environment, FileSystemLoader
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import yaml
from jsonschema import validate, ValidationError
from dataclasses import dataclass, field


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

IMAGE_YAML_FILE = "images.yaml"

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://github.com/lboclboc/buildimage.git", # FIXME: correct to proper url.
    "title": "buildimage",
    "description": "Instructions for how to build images in kubernetes",
    "type": "object",
    "properties": {
        "images": {
            "description": "List of images to build",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "directory": {
                        "description": "sub-director below this file where image Dockerfile is located",
                        "type": "string",
                    },
                    "name": {
                        "description": "name of image (not including the :tag)",
                        "type": "string",
                    },
                    "tags": {
                        "description": "list of tags to use. Example {{ treeHash }}",
                        "type": "array",
                        "items": {
                            "type": "string",
                        },
                    },
                    "labels": {
                        "description": "docker image labels",
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "description": "name of label, example com.mycompany.repository",
                                    "type": "string",
                                },
                                "value": {
                                    "description": "value of label, example {{ repository }}",
                                    "type": "string",
                                },
                            },
                            "required": ["name", "value"],
                        },
                    },
                    "buildArgs": {
                        "description": "Build arguments for image",
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "description": "build arg. Example BASE_IMAGE",
                                    "type": "string",
                                },
                                "value": {
                                    "description": "value of build arg, example 'busybox'",
                                    "type": "string",
                                },
                            },
                            "required": ["name", "value"],
                        },
                    },
                    "deployments": {
                        "description": "Deployments to update",
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "description": "path to file to modify",
                                    "type": "string",
                                },
                                "match": {
                                    "description": "regular expression to match",
                                    "type": "string",
                                },
                                "replace": {
                                    "description": "recplavement value",
                                    "type": "string",
                                },

                            },
                            "required": ["path", "match", "replace"],
                        },
                    },
                },
                "required": ["directory", "name", "tags"],
            },
            "minItems": 1
        },
    },
    "required": ["images"],
}

@dataclass
class Image:
    name: str  # Basename of image, including host, port, namespace and repo
    tag: str
    image_facts: dict[str, str]
    fullname: str = field(init=False)
    def __post_init__(self):
        self.fullname = self.name + ":" + self.tag

class ImageBuilder:
    """Holds the context during the whole build for all images and specs."""
    def __init__(self, top: str) -> None:
        self._top = Path(top)
        self._spec: dict[str, object] | None = None
        self._facts: dict[str, str] | None = dict()
        self.get_facts()

    @staticmethod
    def command(cmd: list[str]) -> str:
        return subprocess.run(cmd, stdout=subprocess.PIPE, check=True).stdout.decode().strip()

    @staticmethod
    def get_tree_hash(dir: Path) -> str:
        dir = f"./{dir}" if not dir.is_absolute() else str(dir)  # Needed since Path strips "./"
        tree_hash = ImageBuilder.command(["git", "rev-parse", f"HEAD:{dir}/."])
        dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", f"{dir}/"])
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
        f["treeHash"] = "{treeHash}"  # This actually needs to be expanded per image rather that globally.
        f["top"] = str(self._top)

    def load_spec(self) -> None:
        env = Environment(loader=FileSystemLoader("."))
        template = env.get_template(str(self._top / IMAGE_YAML_FILE))
        rendered = template.render(**self._facts)

        with io.StringIO(rendered) as fin:
            self._spec: dict = yaml.safe_load(fin)

        validate(instance=self._spec, schema=SCHEMA)

    def build_images(self, images_to_build: list[str] = None) -> None:
        """Builds all images and returns a list of built Image objects."""
        build_result: dict[str, list[Image]] = dict()
        for img in self._spec["images"]:
            if images_to_build and img["name"] not in images_to_build:
                continue
            image_dir = Path(img["directory"])
            if not image_dir.is_absolute():
                image_dir = self._facts["top"] / image_dir

            image_facts: dict[str, str] = dict()
            (image_facts["treeHash"], image_facts["dirty"]) = self.get_tree_hash(image_dir)

            labels = [
                # This will make the images.yaml file usage traceable from the image.
                "--label", f"com.github.lboclboc.buildimage.topTreeHash={self._facts['topTreeHash']}",
            ]
            for b in img.get("labels") or []:
                labels.extend(["--label", f"{b['name']}={b['value'].format(**image_facts)}"])

            buildargs = []
            for b in img.get("buildArgs") or []:
                buildargs.extend(["--build-arg", f"{b['name']}={b['value'].format(**image_facts)}"])

            image_list: list[Image] = []
            for tag in img.get("tags") or []:
                tag = tag.format(**image_facts)
                i = Image(img["name"], tag, image_facts)
                if len(image_list) == 0:
                    cmd = ["docker", "build", "-t", i.fullname] + buildargs + labels + [str(image_dir)]
                    logging.info(f"Building {i.fullname} in {image_dir}...")
                    subprocess.run(cmd, check=True)
                else:
                    cmd = ["docker", "tag", image_list[0].fullname, i.fullname]
                    logging.info(f"Tagging {i.fullname}...")
                    subprocess.run(cmd, check=True)

                image_list.append(i)
            if len(image_list) == 0:
                raise RuntimeError(f"No tags specified in {IMAGE_YAML_FILE} for image {img['name']}")

            build_result[img["name"]] = image_list

        if len(build_result) == 0:
            raise RuntimeError("No images found to build.")

        return build_result

    def update_deployments(self, build_result: dict[str, list[Image]]) -> None:
        for img in self._spec["images"]:
            if img["name"] not in build_result:
                continue
            i = build_result[img["name"]][0]  # Use first built image data only.
            for deploy in (img.get("deployments") or []):
                path = self._top / deploy["path"].format(**i.image_facts)
                match = deploy["match"].format(**i.image_facts)
                replace = deploy["replace"].format(**i.image_facts)
                lines = []
                with path.open() as fin:
                    for l in fin:
                        lines.append(re.sub(match, replace, l))

                with path.open("w") as fout:
                    for l in lines:
                        fout.write(l)


def get_arguments():
    parser = argparse.ArgumentParser("buildimage")
    parser.add_argument("--nopush", action="store_true", help="Skip pushing built images")
    parser.add_argument("--image", action='append', default=None, help="Only build named images, can be specified multiple times")
    parser.add_argument("directory", nargs="?", help="Path to directory for the images.yaml file", default=".")
    return parser.parse_args()


def main() -> None:
    args = get_arguments()

    builder = ImageBuilder(args.directory)

    try:
        builder.load_spec()
    except ValidationError as e:
        logging.error(f"Error in yaml-file: {e}")
        sys.exit(1)

    build_result: dict[str, list[Image]] = builder.build_images(args.image)

    if not args.nopush:
        for name in build_result:
            for image in build_result[name]:
                subprocess.run(["docker", "push", image.fullname], check=True)

    builder.update_deployments(build_result)