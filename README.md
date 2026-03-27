# buildimage

Build Docker images from git source for use in Kubernetes deployments. The build images can be tagged with configurable values. The recomended way is to tag it with the tree hash for the docker folder. This is the way the example below use.

By using the tree-hash the source code for building the image is traceable and you can create one complete commit for a change. If using commit hash, two commits is needed. One for the image change and one follow up for the deployment change (kustomize/helm/yaml).

The script uses a file named `images.yaml` to describe what images to build and what deployments to patch with new tags. Built images will also have some labels with metadata defined. The YAML file can use facts using the Jinja2 template format `{{ name }}`.

## Installation

Install from PyPI:

```bash
pip install buildimage
```

## Usage

Run the `buildimage` command in a directory containing an `images.yaml` file or specify the directory as an argument:

```bash
buildimage [OPTIONS] IMAGES_FILE
```

### Options

- `--nopush`: Skip pushing built images
- `--image IMAGE`: Only build named images (can be specified multiple times)
- `IMAGES_FILE`: Path to the `images.yaml` file (default: ./images.yaml)

## Configuration

Create an `images.yaml` file in your project root with the following format:

```yaml
images:
  - name: "image name"               (required)
    directory: "build-directory"     (required)
    dockerFile: "Dockerfile"         (relative to directory}
    tags:                            (required)
      - "tree-{{treeHash}}"          (first tag is later available as {{tag}})
      - "latest"
    labels:
      - name: com.mydomain.repository
        value: "{{repository}}"
    buildArgs:
      - name: "build-arg-name"
        value: "build-arg-value"
    deployments:
      - path: "path/to/deployment.yaml"
        match: "regex-to-match"
        replace: "{{tag}}"           (default value)
      - kustomize: "../development/kustomize.yaml"
        name: "{{name}}"             (default value)
        newTag: "{{tag}}"            (default value)

```

## Available Facts

The following facts are available for templating in `images.yaml`:

- `{{branch}}`: Current Git branch
- `{{commit}}`: Hash for current HEAD commit
- `{{login}}`: Currently logged in used performing build
- `{{name}}`: Name of current image being built (without tags)
- `{{remote}}`: Git remote name
- `{{repositoryFull}}`: Full repository URL
- `{{repository}}`: Repository URL without user info
- `{{tag}}`: Tag used for first built image tag (same as tag0. also tag[1..3] are available)
- `{{top}}`: Top directory path
- `{{topTreeHash}}`: Git tree hash of the top directory
- `{{treeHash}}`: Git tree hash of the image directory (per image)

## Labels

Except the custom labels defined in the images.yaml file following standard labels will be added for the image:

- `org.opencontainers.image.topTreeHash`
- `org.opencontainers.image.source`
- `org.opencontainers.image.revision`
- `org.opencontainers.image.user`
- `org.opencontainers.image.buildimage`

## Example

See the `tests/docker/` directory for a complete example with test images and deployment updates.
