"""artifact_paths.py — Build stable output paths for one generated clip run."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

from content_registry import load_registry


@dataclass(frozen=True)
class ArtifactPaths:
    output_dir: Path
    registry_id: str

    @property
    def run_dir(self) -> Path:
        return self.output_dir / "runs" / self.registry_id

    @property
    def audio_dir(self) -> Path:
        return self.run_dir / "audio"

    @property
    def clips_dir(self) -> Path:
        return self.run_dir / "clips"

    @property
    def videos_dir(self) -> Path:
        return self.run_dir / "videos"

    @property
    def manifest(self) -> Path:
        return self.run_dir / "manifest.json"

    @property
    def audio(self) -> Path:
        return self.audio_dir / "voiceover.mp3"

    @property
    def srt(self) -> Path:
        return self.audio_dir / "voiceover.srt"

    @property
    def raw_video(self) -> Path:
        return self.videos_dir / "raw.mp4"

    @property
    def final_video(self) -> Path:
        return self.videos_dir / "final.mp4"

    def clip(self, index: int) -> Path:
        return self.clips_dir / f"clip_{index:02d}.mp4"

    def normalized_clip(self, index: int) -> Path:
        return self.clips_dir / f"norm_{index:02d}.mp4"

    def ensure_dirs(self) -> None:
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.videos_dir.mkdir(parents=True, exist_ok=True)


def build_artifact_paths(output_dir: Path, registry_id: str) -> ArtifactPaths:
    paths = ArtifactPaths(output_dir=Path(output_dir), registry_id=registry_id)
    paths.ensure_dirs()
    return paths


def reserve_artifact_paths(
    output_dir: Path,
    *,
    registry_path: str | Path | None = None,
    prefix: str = "clipforge",
) -> ArtifactPaths:
    output_dir = Path(output_dir)
    runs_dir = output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).date().isoformat()
    pattern = re.compile(rf"^{re.escape(prefix)}-{today}-(\d+)$")

    while True:
        seen: set[int] = set()

        for entry in load_registry(registry_path).get("entries", []):
            match = pattern.match(str(entry.get("id", "")))
            if match:
                seen.add(int(match.group(1)))

        for run_dir in runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            match = pattern.match(run_dir.name)
            if match:
                seen.add(int(match.group(1)))

        next_number = max(seen, default=0) + 1
        registry_id = f"{prefix}-{today}-{next_number:03d}"
        paths = ArtifactPaths(output_dir=output_dir, registry_id=registry_id)

        try:
            paths.run_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue

        paths.ensure_dirs()
        return paths
