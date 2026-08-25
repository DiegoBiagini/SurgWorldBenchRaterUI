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

```bash
python run_human_rating.py \
  --configs /path/to/bundle/configs/*.yaml \
  --output-folder ./ratings
```

If the shell does not expand `*.yaml`, list the files explicitly.

Open the URL Streamlit prints (typically `http://localhost:8501`).

- Enter a rater ID (locked for the session; reuse it to resume).
- Score each clip, then **Save and next**.
- Keep `--output-folder` outside the video trees.

Pass `--include-rated` to also queue already-rated clips (unrated first, then
rated) so you can review or edit scores after a restart.

## Aggregate

After raters finish:

```bash
python run_aggregate_human_ratings.py --output-folder ./ratings
```

Optional `--configs` uses each YAML `output_folder` directory name. Omit it to
scan every subfolder of `--output-folder`.

## Docker

The image contains only the app. Mount configs, videos, prompts, and a ratings
directory at runtime. Paths in the YAML must resolve **inside the container**
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
  --configs /data/configs/control_cosmos_h_og_base.yaml \
  --output-folder /data/ratings
```

With Compose, put a bundle (or `configs/*.yaml` whose paths resolve under `/data`)
in `./data` or set `DATA_DIR`:

```bash
DATA_DIR=/path/to/bundle docker compose up --build
```

Compose expands `/data/configs/*.yaml`. List files explicitly on `docker run`
if your layout differs.

`--include-rated` works the same as locally:

```bash
docker run --rm -p 8501:8501 -v /path/to/bundle:/data \
  surgworldbench-rater-ui \
  --configs /data/configs/control_cosmos_h_og_base.yaml \
  --output-folder /data/ratings \
  --include-rated
```
