#/usr/bin/env python3
import argparse
from buildimage import ImageBuilder
from jsonschema import ValidationError
import logging
import subprocess


def get_arguments():
    parser = argparse.ArgumentParser("buildimage")
    parser.add_argument("--debug", action="store_true", help="Debug the buildimage script")
    parser.add_argument("--nopush", action="store_true", help="Skip pushing built images")
    parser.add_argument("--image", action='append', default=None, help="Only build named images, can be specified multiple times")
    parser.add_argument("directory", nargs="?", help="Path to directory for the images.yaml file", default=".")
    return parser.parse_args()


def main() -> None:
    args = get_arguments()
    quiet = True
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
        quiet = False

    builder = ImageBuilder(args.directory)

    try:
        builder.load_spec()
    except ValidationError as e:
        logging.error(f"Error in yaml-file: {e}")
        sys.exit(1)

    build_result: dict[str, list[Image]] = builder.build_images(args.image, quiet=quiet)

    if not args.nopush:
        for name in build_result:
            for image in build_result[name]:
                cmd = ["docker", "push"]
                if quiet:
                    cmd += ["--quiet"]
                cmd += [image.fullname]
                logging.debug(f"pushing with: {' '.join(cmd)}")
                subprocess.run(cmd, check=True)

    modified_files = builder.update_deployments(build_result)

    # Reporting
    if len(build_result) != 0:
        print("Built images:")
        for name, images in build_result.items():
            for image in images:
                print(f"  {image.fullname}")

    if modified_files:
        print(f"Following files where modified: ")
        for file in modified_files:
            print(f"  {file}")
        print("Consider git commit --amend for those")
