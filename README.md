Finance-bot
===============

CI: Docker build and push
------------------------

This repository includes a GitHub Actions workflow that builds the Docker image and pushes it to Docker Hub when there is a push to the `master` branch.

Required repository secrets
- `DOCKERHUB_USERNAME` — your Docker Hub username
- `DOCKERHUB_TOKEN` — a Docker Hub access token (recommended) or your password

How it works
- On push to `master`, the workflow uses Buildx to build multi-arch images and pushes the image tagged `horacix/finbot` to Docker Hub.

Set secrets
1. Go to your GitHub repository -> Settings -> Secrets and variables -> Actions
2. Add `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`

Test locally
1. Build the image locally:

```bash
docker build -t horacix/finbot:latest .
```

2. Push to Docker Hub (you can also test with a personal tag):

```bash
docker login
docker push horacix/finbot:latest
```

Notes
- The workflow uses `docker/build-push-action` to build & push.
