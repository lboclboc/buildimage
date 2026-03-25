# buildimage

Build Docker images for use in Kubernetes deployments. The build images can be tagged with configurable values. The recomended way is to tag it with the tree hash from the docker folder. This is the way the example below use.

The script uses a file named `images.yaml` to describe what images to build and what deployments to patch with new tags. Built images will also have some labels with metadata defined. The YAML file can use facts using the Jinja2 template format `{{ name }}`.

## Installation

Install from PyPI:

```bash
pip install buildimage
```

## Usage

Run the `buildimage` command in a directory containing an `images.yaml` file or specify the directory as an argument:

```bash
buildimage [OPTIONS] DIRECTORY
```

### Options

- `--nopush`: Skip pushing built images
- `--image IMAGE`: Only build named images (can be specified multiple times)
- `DIRECTORY`: Path to directory containing the `images.yaml` file (default: current directory)

## Configuration

Create an `images.yaml` file in your project root with the following format:

```yaml
images:
  - name: "image name"               (required)
    directory: "build-directory"     (required)
    dockerFile: "Dockerfile"
    tags:                            (required)
      - "tree-{{treeHash}}"
    labels:
      - name: com.mydomain.repository
        value: "{{repository}}"
    buildArgs:
      - name: "build-arg-name"
        value: "build-arg-value"
    deployments:
      - path: "path/to/deployment.yaml"
        match: "regex-to-match"
        replace: "replacement-value"
```

### Available Facts

The following facts are available for templating in `images.yaml`:

- `{{branch}}`: Current Git branch
- `{{remote}}`: Git remote name
- `{{repositoryFull}}`: Full repository URL
- `{{repository}}`: Repository URL without user info
- `{{commit}}`: Hash for current HEAD commit
- `{{topTreeHash}}`: Git tree hash of the top directory
- `{{treeHash}}`: Git tree hash of the image directory (per image)
- `{{login}}`: Currently logged in used performing build
- `{{top}}`: Top directory path

## Example

See the `tests/docker/` directory for a complete example with test images and deployment updates.
