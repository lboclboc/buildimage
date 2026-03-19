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
        value: "{{ .repository }}"
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
                },
                "required": ["directory", "name", "tags"],
            },
            "minItems": 1
        },
    },
    "required": ["images"],
}


class ImageBuilder:
    """Holds the context during the whole build for all images and specs."""
    def __init__(self, top: str) -> None:
        self._top = Path(top)
        self._spec: dict[str, object] | None = None
        self._facts: dict[str, str] | None = dict()
        self._built_images: list[str] | None = None
        self.get_facts()

    @staticmethod
    def command(cmd: list[str]) -> str:
        return subprocess.run(cmd, stdout=subprocess.PIPE, check=True).stdout.decode().strip()

    def get_facts(self) -> None:
        """calculate various facts that can be used in the images.yaml file"""
        f = self._facts
        f["branch"] = self.command(["git", "branch", "--show-current"])
        f["remote"] = self.command(["git", "config", f"branch.{f['branch']}.remote"])
        f["repositoryFull"] = self.command(["git", "remote", "get-url", f["remote"]])
        f["repository"] = re.sub(r"//.*@", "//", f["repositoryFull"])  # Drop user info
        tree_hash = self.command(["git", "rev-parse", "HEAD:./"])
        f["treeHash"] = tree_hash + "-dirty" if subprocess.run(["git", "diff", "--quiet", "HEAD", "./"]) else tree_hash
        # FIXME: git-commit also as fact
        # FIXME:
        f["top"] = str(self._top)

    def load_spec(self) -> None:
        env = Environment(loader=FileSystemLoader("."))
        template = env.get_template(str(self._top / IMAGE_YAML_FILE))
        rendered = template.render(**self._facts)

        with io.StringIO(rendered) as fin:
            self._spec: dict = yaml.safe_load(fin)

        validate(instance=self._spec, schema=SCHEMA)

    def build_images(self) -> None:
        for image in self._spec["images"]:
            buildargs = []
            for b in image.get("build-args") or []:
                buildargs.extend(["--build-arg", f"{b['name']}={b['value']}"])

            labels = []
            for b in image.get("labels") or []:
                labels.extend(["--label", f"{b['name']}={b['value']}"])

            self._built_images = []
            for tag in image.get("tags") or []:
                self._built_images.append(f"{image['name']}:{tag}")
            if len(self._built_images) == 0:
                raise RuntimeError("No tags specified in {IMAGE_YAML_FILE}")

            image_dir = Path(image["directory"])
            if not image_dir.is_absolute():
                image_dir = self._facts["top"] / image_dir

            cmd = ["docker", "build", "-t", self._built_images[0]] + buildargs + labels + [str(image_dir)]
            logging.info(f"Building {self._built_images[0]} in {image['directory']}")
            subprocess.run(cmd, check=True)

            for name in self._built_images[1:]:
                logging.info(f"Tagging {name}")
                subprocess.run(["docker", "tag", self._built_images[0], name], check=True)


def get_arguments():
    parser = argparse.ArgumentParser("buildimage")
    parser.add_argument("--nopush", action="store_true", help="Skip pushing built images")
    parser.add_argument("--image", nargs="*", help="Only build named images, can be specified multiple times")
    parser.add_argument("directory", nargs="1", help="Path to directory for the images.yaml file", default=".")
    return parser.parse_args()


def main() -> None:
    args = get_arguments()

    builder = ImageBuilder(args.directory)
    try:
        builder.load_spec()
    except ValidationError as e:
        logging.error(f"Error in yaml-file: {e}")
        sys.exit(1)

    builder.build_images()
    # FIXME: implement deployments updates.
    # builder.update_deployments()
    if not args.nopush:
        builder.push_images()


if __name__ == "__main__":
    main()
