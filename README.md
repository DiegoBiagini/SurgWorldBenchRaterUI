# SurgWorldBench rater UI

Blind Streamlit rater for SurgWorldBench generated videos. Clips from several
generation YAMLs are pooled and shuffled so the rater does not see which model
produced each clip. Ratings are stored per rater.

This repository is the rating app plus the pages and generation YAMLs under
[`harness_configs/`](harness_configs/) and [`gen_configs/`](gen_configs/).
Videos, prompts, and rating output live on the **rater filesystem** (default
`/mnt/rater_filesystem`). Those paths must exist on the machine, or at the
same path inside the container.

Scoring rules: [`harness/guidelines.md`](harness/guidelines.md).

## Local install

Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run

[`harness_configs/base_config.yaml`](harness_configs/base_config.yaml) lists
each rating set: URL path, generation configs, and output folder. The shipped
`gen_configs/*.yaml` files use absolute paths under `/mnt/rater_filesystem`
(prompts, videos, ratings).

To write your own pages YAML, see
[`harness_configs/rater_pages.example.yaml`](harness_configs/rater_pages.example.yaml).
Relative `configs` paths resolve against the pages file directory. `configs`
entries may include globs. Absolute `output_folder` values are used as-is.

```bash
python run_human_rating.py --pages-config harness_configs/base_config.yaml
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
python run_aggregate_human_ratings.py --pages-config harness_configs/base_config.yaml
```

## Rater filesystem

Generation YAMLs point at `/mnt/rater_filesystem/...`. That tree is **not** in
this repo. On the host it is usually already at `/mnt/rater_filesystem`. If it
lives somewhere else, bind-mount that directory to `/mnt/rater_filesystem` in
Docker (see below). Inside the container the path must still be
`/mnt/rater_filesystem` so the YAMLs keep working.

[`harness_configs/base_config.yaml`](harness_configs/base_config.yaml) and
[`gen_configs/`](gen_configs/) expect this layout (one subdirectory per
benchmark task):

```text
/mnt/rater_filesystem/
  benchmark_outputs/
    benchmark_data_control/
      control_prompts/                  # original prompts (folder_path for og_base)
        LEMON/004/move_right.txt
        LEMON/004/move_right_query.txt
        …
      control_prompts_refined_cosmos/   # folder_path for cosmos3 *refined_cosmos*
      control_prompts_refined_mm/       # folder_path for minimax *refined_mm*
      gen_videos_cosmos_h_og_base/      # output_folder: generated clips
        LEMON_004_move_right.mp4
        LEMON_004_move_right.txt        # required sidecar (same stem as the mp4)
        LEMON_004_move_right.json       # optional metadata
        …
      gen_videos_cosmos3_h_surgical_refined_cosmos/
      gen_videos_cosmos3_nano_refined_cosmos/
      gen_videos_cosmos3_super_refined_cosmos/
      gen_videos_minimax_h3_refined_mm/
      human_rating/                     # pages YAML output_folder (written by the UI)
        gen_videos_cosmos_h_og_base/
          <rater_id>/
            LEMON_004_move_right.json
          <rater_id>.json               # per-rater aggregate
    benchmark_data_manipulation/        # same pattern: manipulation_prompts*, gen_videos_*, human_rating/
    benchmark_data_needle_passing/      # same pattern: needle_passing_prompts*, gen_videos_*, human_rating/
```

**Prompts** (`folder_path`): three levels, `{dataset}/{index}/{stem}.txt`. Query
text is `{stem}_query.txt` next to it. Video stems are
`{dataset}_{index}_{stem}` (for example `LEMON_004_move_right`). For refined
prompt folders (`*_refined_cosmos`, `*_refined_mm`) the UI also reads the
matching original tree (`control_prompts`, `manipulation_prompts`,
`needle_passing_prompts`).

**Videos** (`output_folder` in each gen YAML): flat directory of `.mp4` files.
A clip is rated only if `{stem}.mp4` and `{stem}.txt` both exist.

**Ratings** (`output_folder` in the pages YAML): created automatically. Keep
this directory outside the `gen_videos_*` trees.

## Docker

The image contains only the app. Compose mounts:

- the rater filesystem at `/mnt/rater_filesystem`
- [`harness_configs/`](harness_configs/) and [`gen_configs/`](gen_configs/) so
  [`base_config.yaml`](harness_configs/base_config.yaml) can load the gen YAMLs

`gen_configs` is nested under `harness_configs` in the container because
relative `configs:` entries are resolved against the pages YAML directory.

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
  -v /mnt/rater_filesystem:/mnt/rater_filesystem \
  -v "$(pwd)/harness_configs":/app/harness_configs \
  -v "$(pwd)/gen_configs":/app/harness_configs/gen_configs:ro \
  surgworldbench-rater-ui \
  --pages-config /app/harness_configs/base_config.yaml
```

The first `-v` host path can be any directory that should appear as
`/mnt/rater_filesystem` in the container. Do not add `:ro` on the
`harness_configs` mount: Docker needs it writable to create the nested
`gen_configs` mountpoint.

With Compose, from the repo root:

```bash
docker compose up --build
```

If the data is not at `/mnt/rater_filesystem` on the host, set
`RATER_FILESYSTEM` (Compose interpolates
`${RATER_FILESYSTEM:-/mnt/rater_filesystem}:/mnt/rater_filesystem`):

```bash
RATER_FILESYSTEM=/path/on/host docker compose up --build
```

You can also put `RATER_FILESYSTEM=/path/on/host` in `.env`.

## Docker with HTTP password

[`Dockerfile.auth`](Dockerfile.auth) adds nginx in front of Streamlit with HTTP
Basic Authentication. The password is read at **runtime** from the environment
(typically `.env`); it is not stored in the image.

```bash
cp .env.example .env   # set RATER_PASSWORD (and optional RATER_USER, RATER_FILESYSTEM)
docker compose -f docker-compose.auth.yml up --build
```

Open `http://localhost:8501`. The browser asks for a username and password
(`RATER_USER`, default `rater`, plus `RATER_PASSWORD`). This is a shared secret,
not per-rater accounts.

Equivalent `docker run`:

```bash
docker build -f Dockerfile.auth -t surgworldbench-rater-ui-auth .
docker run --rm -p 8501:80 \
  --env-file .env \
  -v /mnt/rater_filesystem:/mnt/rater_filesystem \
  -v "$(pwd)/harness_configs":/app/harness_configs \
  -v "$(pwd)/gen_configs":/app/harness_configs/gen_configs:ro \
  surgworldbench-rater-ui-auth \
  --pages-config /app/harness_configs/base_config.yaml
```

Map host **8501 → container 80** (nginx). Streamlit listens only on localhost
inside the container, so it is not reachable without the password.

`RATER_PASSWORD` is required. Over plain HTTP the password is only
Base64-encoded. To serve **HTTPS** with a real certificate (Let’s Encrypt or
an institution cert), see [`https.md`](https.md).
