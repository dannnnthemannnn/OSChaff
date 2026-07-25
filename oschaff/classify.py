"""Classify each source task into a compilation mode.

    channel  — already uses an injectable service via prepare_stateful_website_urls;
               perturb its existing state asset(s), no .py edit.
    bolt_on  — an information task on Chrome with no channel; provision one
               (edit setup() + prompt) if config.bolt_on is set.
    skip     — perceptual/editing (media/CAD), live-web-only, or otherwise out of
               our information-noise axis; copied byte-identical.

Classification is read-only static analysis of the task source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import ChaffConfig, SERVICE_APPS

_APP_TO_SERVICE = {v: k for k, v in SERVICE_APPS.items()}

# related_apps whose difficulty is perceptual/manipulation — not our axis.
PERCEPTUAL = {
    "shotcut", "gimp", "reaper", "musescore", "blender", "mpv", "image_viewer",
    "freecad", "solvespace", "logisim", "libero", "geogebra", "openboard",
}
# web "apps" that aren't information stores (games/viewers).
NON_INFO_WEB = {"dinogame", "slidepuzzle", "glbviewer", "studio.streamview"}


@dataclass
class Classification:
    task_id: str
    mode: str                 # "channel" | "bolt_on" | "skip"
    services: list[str]       # injectable services this task touches (channel mode)
    apps: list[str]           # web apps provisioned via the hook
    reason: str


def _related_apps(src: str) -> list[str]:
    m = re.search(r"related_apps\s*=\s*\[([^\]]*)\]", src)
    return re.findall(r"""["']([^"']+)["']""", m.group(1)) if m else []


def _web_apps(src: str) -> set[str]:
    if "prepare_stateful_website_urls" not in src:
        return set()
    return set(re.findall(r"""app\s*=\s*["']([a-z_\.]+)["']""", src))


def classify_source(task_id: str, src: str, cfg: ChaffConfig) -> Classification:
    related = set(_related_apps(src))
    web = _web_apps(src)

    # channel: uses an injectable service we're targeting
    hit_apps = sorted(web & cfg.apps)
    if hit_apps:
        return Classification(
            task_id, "channel",
            services=sorted({_APP_TO_SERVICE[a] for a in hit_apps}),
            apps=hit_apps,
            reason=f"uses injectable service(s): {hit_apps}",
        )

    # skip: perceptual / non-info web / no Chrome to host a tab
    if related & PERCEPTUAL:
        return Classification(task_id, "skip", [], [], f"perceptual apps: {sorted(related & PERCEPTUAL)}")
    if web & NON_INFO_WEB:
        return Classification(task_id, "skip", [], [], f"non-info web app: {sorted(web & NON_INFO_WEB)}")

    uses_chrome = bool(related & {"chrome", "google-chrome", "browser", "firefox"})
    if not uses_chrome:
        return Classification(task_id, "skip", [], [], "no browser to host an injected channel")

    # bolt_on candidate: info task on Chrome, no existing channel
    if cfg.bolt_on:
        return Classification(task_id, "bolt_on", [], [], "browser info task; provision a channel")
    return Classification(task_id, "skip", [], [], "bolt_on disabled")


def load_and_classify(task_path: str, cfg: ChaffConfig) -> Classification:
    src = open(task_path, encoding="utf-8").read()
    m = re.search(r"task_(\d+)\.py$", task_path)
    task_id = m.group(1) if m else task_path
    return classify_source(task_id, src, cfg)
