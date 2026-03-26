
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://github.com/lboclboc/buildimage.git", # FIXME: correct to proper url.
    "title": "buildimage",
    "description": "Instructions for how to build images in kubernetes",
    "type": "object",
    "required": ["images"],
    "properties": {
        "schemaVersion": {
            "description": "Buildimage compatibility version of this file",
            "type": "string",
            "pattern": r"^[0-9]+\.[0-9]+(\.[0-9]+)?$",
        },
        "images": {
            "description": "List of images to build",
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["directory", "name", "tags"],
                "properties": {
                    "directory": {
                        "description": "sub-director below this file where image Dockerfile is located",
                        "type": "string",
                    },
                    "dockerFile": {
                        "description": "sub-director below this file where image Dockerfile is located",
                        "type": "string",
                    },
                    "name": {
                        "description": "name of image (not including the :tag)",
                        "type": "string",
                    },
                    "tags": {
                        "description": "list of tags to use. Example {{treeHash}}",
                        "type": "array",
                        "minItems": 1,
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
                            "oneOf": [
                                {
                                    # Simple file patching.
                                    "type": "object",
                                    "required": ["path", "match"],
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
                                    }
                                },
                                {
                                    # Kustomize
                                    "type": "object",
                                    "required": ["kustomize"],
                                    "properties": {
                                        "kustomize": {
                                            "description": "path to the kustomization.yaml file",
                                            "type": "string",
                                        },
                                        "name": {
                                            "description": "name of image to lookup in kustomize.yaml, default current image name",
                                            "type": "string",
                                        },
                                        "newTag": {
                                            "description": "value of newTag",
                                            "type": "string",
                                        },
                                    }
                                },
                            ],
                        },
                    },
                },
            },
        },
    },
}
