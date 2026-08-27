# SurgWorldBench rater UI

Blind Streamlit rater for SurgWorldBench generated videos. Clips from several
generation YAMLs are pooled and shuffled so the rater does not see which model
produced each clip. Ratings are stored per rater.

This repository is the rating app only. It does not include videos or prompts.
Point it at a portable bundle from SurgWorldBench
(`python export_human_rating_bundle.py …`) or any YAML whose `folder_path` and
`output_folder` resolve on this machine (or inside the container).

Scoring rules: [`harness/guidelines.md`](harness/guidelines.md).

## Local install

Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run

Write a pages YAML (see [`rater_pages.example.yaml`](rater_pages.example.yaml))
that lists each rating set: URL path, generation configs, and output folder.

```yaml
pages:
  - path: control
    title: Control
    configs:
      - /path/to/bundle/configs/control_a.yaml
      - /path/to/bundle/configs/control_b.yaml
    output_folder: ./ratings/control
  - path: experimental
    title: Experimental
    configs:
      - /path/to/bundle/configs/exp_*.yaml
    output_folder: ./ratings/experimental
```

Relative `configs` and `output_folder` paths resolve against the pages file.
`configs` entries may include globs.

```bash
python run_human_rating.py --pages-config rater_pages.yaml
```

Open the URL Streamlit prints (typically `http://localhost:8501`).

- Home lists every rating set. Each set is also at `/<path>` (for example
  `http://localhost:8501/control`).
- On a set, enter a rater ID (locked for that set in this session; reuse it to
  resume). Check **Show already labeled samples** if you want previously rated
  clips in the queue (unrated first, then rated).
- Score each clip, then **Save and next** (or press **Enter**).
- Keep each page `output_folder` outside the video trees.

## Aggregate

After raters finish, rebuild per-set aggregates from the pages YAML:

```bash
python run_aggregate_human_ratings.py --pages-config rater_pages.yaml
```

## Docker

The image contains only the app. Mount configs, videos, prompts, ratings, and a
pages YAML at runtime. Paths in the YAMLs must resolve **inside the container**
(a bundle from `export_human_rating_bundle.py` already uses relative paths).

Pass host proxy env vars as build args so `pip` can reach PyPI (omit the
`--build-arg` lines if you have a direct network):

```bash
docker build -t surgworldbench-rater-ui . \
  --build-arg HTTP_PROXY \
  --build-arg HTTPS_PROXY \
  --build-arg NO_PROXY \
  --build-arg http_proxy \
  --build-arg https_proxy \
  --build-arg no_proxy

docker run --rm -p 8501:8501 \
  -v /path/to/bundle:/data \
  surgworldbench-rater-ui \
  --pages-config /data/rater_pages.yaml
```

With Compose, put a bundle (including `rater_pages.yaml` whose paths resolve
under `/data`) in `./data` or set `DATA_DIR`:

```bash
DATA_DIR=/path/to/bundle docker compose up --build
```

## Docker with HTTP password

[`Dockerfile.auth`](Dockerfile.auth) adds nginx in front of Streamlit with HTTP
Basic Authentication. The password is read at **runtime** from the environment
(typically `.env`); it is not stored in the image.

```bash
cp .env.example .env   # set RATER_PASSWORD (and optional RATER_USER)
DATA_DIR=/path/to/bundle docker compose -f docker-compose.auth.yml up --build
```

Open `http://localhost:8501`. The browser asks for a username and password
(`RATER_USER`, default `rater`, plus `RATER_PASSWORD`). This is a shared secret,
not per-rater accounts.

Equivalent `docker run`:

```bash
docker build -f Dockerfile.auth -t surgworldbench-rater-ui-auth .
docker run --rm -p 8501:80 \
  --env-file .env \
  -v /path/to/bundle:/data \
  surgworldbench-rater-ui-auth \
  --pages-config /data/rater_pages.yaml
```

Map host **8501 → container 80** (nginx). Streamlit listens only on localhost
inside the container, so it is not reachable without the password.

`RATER_PASSWORD` is required. Over plain HTTP the password is only
Base64-encoded. To serve **HTTPS** with a real certificate (Let’s Encrypt or
an institution cert), see [`https.md`](https.md).
