#/usr/bin/env python3
import argparse
from buildimage import ImageBuilder
import subprocess


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