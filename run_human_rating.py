"""
run_human_rating.py — Blind Streamlit UI for rating generated control-prompt videos.

Requires: pip install streamlit

Usage:
    python run_human_rating.py --pages-config rater_pages.yaml
"""

from __future__ import annotations

import argparse
import inspect
import os
import random
import sys
from pathlib import Path

from harness.human_rating import (
    SCORE_KEYS,
    Clip,
    discover_clips,
    is_clip_rated,
    load_generation_sources,
    load_rating,
    maybe_write_rater_aggregate,
    rating_json_path,
    refresh_rater_aggregates,
    save_rating,
    sanitize_rater_id,
    unrated_clips,
)
from harness.pages_config import RatingPage, load_pages_config

# Placeholder copy — replace with the rating procedure for each criterion.
RATING_HELP = {
    "query_followed": "TODO: How to score query following (1 = not followed, 5 = fully followed).",
    "tool_consistency": "TODO: How to score tool consistency (1 = tools morph/jump, 5 = stable tools).",
    "anatomy_natural": "TODO: How to score anatomy (1 = implausible, 5 = natural tissue behaviour).",
}

SCORE_LABELS = {
    "query_followed": "How much is the query followed?",
    "tool_consistency": "Do tools stay consistent throughout the video?",
    "anatomy_natural": "Does the anatomy behave naturally?",
}

SCORE_OPTIONS = [1, 2, 3, 4, 5]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Blind human rater for generated videos (Streamlit)"
    )
    parser.add_argument(
        "--pages-config",
        required=True,
        help="YAML listing rating-set pages (path, configs, output_folder)",
    )
    return parser.parse_args(argv)


def _argv_for_app() -> list[str]:
    argv = sys.argv[1:]
    if "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1 :]
    return argv


def running_under_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except Exception:
        return False


def launch_streamlit() -> None:
    try:
        import streamlit  # noqa: F401
    except ImportError as exc:
        raise SystemExit("streamlit is required. Install with: pip install streamlit") from exc

    script = str(Path(__file__).resolve())
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        script,
        "--",
        *_argv_for_app(),
    ]
    print("Launching Streamlit (first load can take a bit while clips are indexed)…", flush=True)
    print(" ".join(cmd), flush=True)
    os.execv(sys.executable, cmd)


def _state_key(page_path: str, name: str) -> str:
    return f"{name}::{page_path}"


def _score_widget_key(page_path: str, clip_id: str, score_key: str) -> str:
    return f"score::{page_path}::{clip_id}::{score_key}"


def _hydrate_score_widgets(
    page_path: str, clip: Clip, output_root: Path, rater_id: str
) -> None:
    import streamlit as st

    path = rating_json_path(
        output_root, clip.source.folder_name, rater_id, clip.output_stem
    )
    existing = load_rating(path)
    scores = (existing or {}).get("scores") or {}
    for key in SCORE_KEYS:
        widget_key = _score_widget_key(page_path, clip.clip_id, key)
        if widget_key not in st.session_state and key in scores:
            st.session_state[widget_key] = int(scores[key])


def _collect_scores(page_path: str, clip: Clip) -> dict[str, int] | None:
    import streamlit as st

    scores: dict[str, int] = {}
    for key in SCORE_KEYS:
        value = st.session_state.get(_score_widget_key(page_path, clip.clip_id, key))
        if value is None:
            return None
        scores[key] = int(value)
    return scores


def _init_queue(
    page_path: str,
    clips: list[Clip],
    output_root: Path,
    rater_id: str,
    *,
    include_rated: bool,
) -> None:
    import streamlit as st

    queue_key = _state_key(page_path, "queue_ids")
    index_key = _state_key(page_path, "queue_index")
    if queue_key in st.session_state:
        return
    print(
        f"Building session queue for rater {rater_id!r} on page {page_path!r} …",
        flush=True,
    )
    remaining = unrated_clips(output_root, clips, rater_id)
    remaining_ids = [c.clip_id for c in remaining]
    random.shuffle(remaining_ids)
    if include_rated:
        remaining_set = set(remaining_ids)
        rated_ids = [c.clip_id for c in clips if c.clip_id not in remaining_set]
        random.shuffle(rated_ids)
        order = remaining_ids + rated_ids
        print(
            f"Queue ready: {len(remaining_ids)} unrated + {len(rated_ids)} rated "
            f"/ {len(clips)} total",
            flush=True,
        )
    else:
        order = remaining_ids
        print(
            f"Queue ready: {len(order)} unrated / {len(clips)} total "
            f"(already-rated clips skipped)",
            flush=True,
        )
    st.session_state[queue_key] = order
    st.session_state[index_key] = 0


def _load_clips(config_paths: list[str]) -> list[Clip]:
    print("Discovering clips…", flush=True)
    sources = load_generation_sources(config_paths)
    clips = discover_clips(sources)
    print("Clip discovery done.", flush=True)
    return clips


def _session_clips(page_path: str, config_paths: list[str]) -> list[Clip]:
    import streamlit as st

    key = tuple(str(Path(p).resolve()) for p in config_paths)
    cache_key = _state_key(page_path, "_clips")
    paths_key = _state_key(page_path, "_clips_key")
    cached = st.session_state.get(paths_key)
    if cached != key or cache_key not in st.session_state:
        st.session_state[cache_key] = _load_clips(list(key))
        st.session_state[paths_key] = key
    return st.session_state[cache_key]


LAYOUT_CSS = """
<style>
    [data-testid="stHeader"] { display: none; }
    [data-testid="stToolbar"] { display: none; }
    [data-testid="stDecoration"] { display: none; }
    footer { visibility: hidden; }
    .block-container {
        padding-top: 0.6rem !important;
        padding-bottom: 0.4rem !important;
        padding-left: 1.2rem !important;
        padding-right: 1.2rem !important;
        max-width: 100% !important;
    }
    div[data-testid="stVerticalBlock"] { gap: 0.35rem !important; }
    div[data-testid="stHorizontalBlock"] { gap: 0.6rem !important; }
    .stRadio { margin-bottom: 0.15rem; }
    .stRadio > label { font-size: 0.92rem; }
    [data-testid="stTextArea"] textarea { font-size: 0.85rem !important; line-height: 1.25 !important; }
    video { max-height: 42vh !important; width: 100% !important; object-fit: contain; }
    [data-testid="stForm"] { border: 0 !important; padding: 0 !important; }
</style>
"""

ENTER_SAVE_NEXT_JS = """
<script>
(() => {
  const doc = window.parent.document;
  if (window.parent.__raterEnterSaveNext) return;
  window.parent.__raterEnterSaveNext = true;
  doc.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.repeat || e.isComposing) return;
    const el = e.target;
    const tag = (el && el.tagName) || "";
    if (tag === "TEXTAREA") return;
    if (tag === "INPUT") {
      const type = (el && el.type) || "";
      if (["text", "password", "search", "email", "number", "url"].includes(type)) return;
    }
    const buttons = Array.from(doc.querySelectorAll("button"));
    const btn = buttons.find((b) => b.innerText.trim() === "Save and next");
    if (btn && !btn.disabled) {
      e.preventDefault();
      btn.click();
    }
  }, true);
})();
</script>
"""


def _inject_layout_css() -> None:
    import streamlit as st

    st.markdown(LAYOUT_CSS, unsafe_allow_html=True)


def _inject_enter_save_next_js() -> None:
    import streamlit.components.v1 as components

    components.html(ENTER_SAVE_NEXT_JS, height=0)


def _supports_kwarg(fn, name: str) -> bool:
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _show_video(path: Path) -> None:
    import streamlit as st

    kwargs: dict = {}
    params = inspect.signature(st.video).parameters
    for key, value in (("loop", True), ("autoplay", True), ("muted", True)):
        if key in params:
            kwargs[key] = value
    st.video(str(path), **kwargs)


def _text_box(label: str, value: str, *, height: int, path: Path | None = None) -> None:
    import streamlit as st

    st.markdown(f"**{label}**")
    if path is not None:
        parts = path.parts
        short = str(Path(*parts[-4:])) if len(parts) >= 4 else str(path)
        st.caption(short)
    if value:
        st.text_area(
            label,
            value=value,
            height=height,
            disabled=True,
            label_visibility="collapsed",
        )
    else:
        st.caption("Missing")


def _render_nav_strip(
    home_page,
    rating_pages: list[tuple],
    current_path: str | None,
) -> None:
    import streamlit as st

    cols = st.columns(len(rating_pages) + 1)
    with cols[0]:
        st.page_link(home_page, label="Home", disabled=current_path is None)
    for col, (page_obj, spec) in zip(cols[1:], rating_pages):
        with col:
            st.page_link(
                page_obj,
                label=spec.title,
                disabled=spec.path == current_path,
            )


def _render_rater_gate(page: RatingPage) -> tuple[str, bool]:
    import streamlit as st

    rid_key = _state_key(page.path, "rater_id")
    inc_key = _state_key(page.path, "include_rated")
    if st.session_state.get(rid_key):
        return st.session_state[rid_key], bool(st.session_state.get(inc_key, False))

    st.markdown(f"### {page.title}")
    st.caption(
        "Enter a rater ID. It stays locked for this set in this session and names "
        "the output folders."
    )
    with st.form(f"rater_id_form::{page.path}"):
        raw = st.text_input("Rater ID", placeholder="e.g. diego")
        include_rated = st.checkbox(
            "Show already labeled samples",
            value=False,
            help="Also queue clips you have already rated so you can review or edit scores.",
        )
        submitted = st.form_submit_button("Start rating")
    if submitted:
        try:
            st.session_state[rid_key] = sanitize_rater_id(raw)
            st.session_state[inc_key] = bool(include_rated)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    st.stop()
    raise AssertionError("unreachable")


def _render_clip_media(clip: Clip) -> None:
    _show_video(clip.video_path)
    query_name = clip.query_path.name if clip.query_path else "_query.txt"
    txt_name = clip.source_prompt_path.name if clip.source_prompt_path else ".txt"
    _text_box(query_name, clip.query, height=68, path=clip.query_path)
    _text_box(txt_name, clip.source_prompt, height=88, path=clip.source_prompt_path)


def _render_score_radios(page_path: str, clip: Clip) -> None:
    import streamlit as st

    st.markdown("**Ratings**")
    for key in SCORE_KEYS:
        st.radio(
            SCORE_LABELS[key],
            options=SCORE_OPTIONS,
            index=None,
            horizontal=True,
            key=_score_widget_key(page_path, clip.clip_id, key),
            help=RATING_HELP[key],
        )


def _save_current(
    page_path: str, clip: Clip, output_root: Path, rater_id: str, clips: list[Clip]
) -> bool:
    import streamlit as st

    scores = _collect_scores(page_path, clip)
    if scores is None:
        st.warning("Select all three ratings before saving.")
        return False
    save_rating(output_root, clip, rater_id, scores)
    maybe_write_rater_aggregate(output_root, clip.source.folder_name, rater_id, clips)
    return True


def render_home(
    home_page,
    rating_nav: list[tuple],
) -> None:
    import streamlit as st

    _inject_layout_css()
    _render_nav_strip(home_page, rating_nav, current_path=None)
    st.markdown("### Human video rating")
    st.caption("Choose a rating set. Each set has its own clips, output folder, and rater ID.")
    for page_obj, spec in rating_nav:
        st.page_link(page_obj, label=spec.title)
        st.caption(f"`/{spec.path}` · {len(spec.configs)} config(s)")


def render_rating_page(
    page: RatingPage,
    home_page,
    rating_nav: list[tuple],
) -> None:
    import streamlit as st

    _inject_layout_css()
    _render_nav_strip(home_page, rating_nav, current_path=page.path)

    output_root = page.output_folder
    config_paths = [str(p) for p in page.configs]
    with st.spinner("Indexing videos and queries (see the terminal for progress)…"):
        clips = _session_clips(page.path, config_paths)
    clips_by_id = {c.clip_id: c for c in clips}

    rater_id, include_rated = _render_rater_gate(page)
    output_root.mkdir(parents=True, exist_ok=True)
    agg_key = _state_key(page.path, "_aggregates_checked_for")
    if st.session_state.get(agg_key) != rater_id:
        with st.spinner("Checking resume / aggregates…"):
            refresh_rater_aggregates(output_root, clips, rater_id)
        st.session_state[agg_key] = rater_id
    _init_queue(
        page.path, clips, output_root, rater_id, include_rated=include_rated
    )

    queue_key = _state_key(page.path, "queue_ids")
    index_key = _state_key(page.path, "queue_index")
    queue_ids: list[str] = st.session_state[queue_key]
    n_total = len(clips)
    n_rated = sum(1 for c in clips if is_clip_rated(output_root, c, rater_id))
    n_left = n_total - n_rated

    if not queue_ids:
        st.markdown("### All clips rated")
        st.success(f"All {n_total} clips are rated for `{rater_id}` on **{page.title}**.")
        st.progress(1.0)
        st.caption(f"0 remaining ({n_rated} / {n_total} rated)")
        st.info(
            "Start a new browser session for this set and check "
            "**Show already labeled samples** to review or edit saved scores."
        )
        return

    index = min(int(st.session_state[index_key]), len(queue_ids) - 1)
    st.session_state[index_key] = index
    clip = clips_by_id[queue_ids[index]]
    clip_already_rated = is_clip_rated(output_root, clip, rater_id)
    _hydrate_score_widgets(page.path, clip, output_root, rater_id)

    status = " · already rated" if clip_already_rated else ""
    st.markdown(
        f"**Set:** {page.title} · **Rater:** `{rater_id}` · "
        f"Clip {index + 1}/{len(queue_ids)} in queue{status}"
    )

    form_kwargs: dict = {"clear_on_submit": False}
    if _supports_kwarg(st.form, "enter_to_submit"):
        form_kwargs["enter_to_submit"] = False

    with st.form(f"rating_form::{page.path}", **form_kwargs):
        left, right = st.columns((3, 2))
        with left:
            _render_clip_media(clip)
        with right:
            _render_score_radios(page.path, clip)

        b_prev, b_save, b_save_next, b_next = st.columns(4)
        with b_prev:
            prev_clicked = st.form_submit_button(
                "Previous", disabled=index <= 0, use_container_width=True
            )
        with b_save:
            save_clicked = st.form_submit_button("Save", use_container_width=True)
        save_next_kwargs: dict = {"type": "primary", "use_container_width": True}
        has_shortcut = _supports_kwarg(st.form_submit_button, "shortcut")
        if has_shortcut:
            save_next_kwargs["shortcut"] = "Enter"
        with b_save_next:
            save_next_clicked = st.form_submit_button(
                "Save and next", **save_next_kwargs
            )
        with b_next:
            next_clicked = st.form_submit_button(
                "Next", disabled=index >= len(queue_ids) - 1, use_container_width=True
            )

    if not has_shortcut:
        _inject_enter_save_next_js()

    st.progress(n_rated / n_total if n_total else 1.0)
    st.caption(
        f"{n_left} remaining ({n_rated} / {n_total} rated) · Enter saves and goes to next"
    )
    if n_left == 0:
        st.success("All clips are rated. You can still go back and edit saved scores.")

    if prev_clicked:
        st.session_state[index_key] = index - 1
        st.rerun()
    if next_clicked:
        st.session_state[index_key] = index + 1
        st.rerun()
    if save_clicked:
        if _save_current(page.path, clip, output_root, rater_id, clips):
            st.rerun()
    if save_next_clicked:
        if _save_current(page.path, clip, output_root, rater_id, clips):
            if index < len(queue_ids) - 1:
                st.session_state[index_key] = index + 1
            st.rerun()


def render_app(pages: list[RatingPage]) -> None:
    import streamlit as st

    st.set_page_config(
        page_title="Human video rating",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    rating_nav: list[tuple] = []
    nav_items = []

    def _home() -> None:
        render_home(home_page, rating_nav)

    home_page = st.Page(_home, title="Home", default=True)
    nav_items.append(home_page)

    for spec in pages:
        def _make_page(bound: RatingPage = spec):
            def _page() -> None:
                render_rating_page(bound, home_page, rating_nav)

            _page.__name__ = f"rating_{bound.path}"
            return _page

        page_obj = st.Page(_make_page(), title=spec.title, url_path=spec.path)
        rating_nav.append((page_obj, spec))
        nav_items.append(page_obj)

    pg = st.navigation(nav_items, position="hidden")
    pg.run()


def main() -> None:
    if not running_under_streamlit():
        launch_streamlit()
        return
    args = parse_args(_argv_for_app())
    pages = load_pages_config(args.pages_config)
    render_app(pages)


if __name__ == "__main__":
    main()
