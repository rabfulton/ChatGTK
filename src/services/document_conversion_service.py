"""
Document conversion service for ChatGTK.

This service runs optional external command-line tools (user-configurable) to
convert documents like PDFs into plain text or Markdown.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class DocumentPipeline:
    """A user-configurable external conversion pipeline."""

    id: str
    label: str
    extensions: Tuple[str, ...]
    argv: Optional[Tuple[str, ...]] = None
    shell: Optional[str] = None
    output_ext: str = ".txt"
    timeout_sec: int = 120

    def supports_path(self, path: str) -> bool:
        suffix = Path(path).suffix.lower()
        return suffix in {e.lower() for e in self.extensions}


class DocumentConversionError(RuntimeError):
    pass


class DocumentConversionService:
    """
    Runs configured document conversion pipelines.

    This service is intentionally thin: it does not decide where converted
    content is stored or how it is used (inline vs sources vs indexing).
    """

    def __init__(self, pipelines_json: str):
        self._pipelines = self._parse_pipelines(pipelines_json)

    @property
    def pipelines(self) -> List[DocumentPipeline]:
        return list(self._pipelines)

    def get_default_pipeline_for_path(self, path: str) -> Optional[DocumentPipeline]:
        for pipeline in self._pipelines:
            if pipeline.supports_path(path):
                return pipeline
        return None

    def convert_to_text(
        self,
        input_path: str,
        pipeline_id: str,
        output_path: Optional[str] = None,
        timeout_sec: Optional[int] = None,
    ) -> str:
        """
        Convert a document to text/markdown using the selected pipeline.

        Returns the converted text (decoded as UTF-8 with replacement).
        If output_path is provided and the pipeline writes to a file, the file is
        written; stdout is still captured and returned when available.
        """

        pipeline = self._get_pipeline(pipeline_id)
        input_path = os.path.abspath(input_path)
        if not os.path.exists(input_path):
            raise DocumentConversionError(f"Input file not found: {input_path}")

        resolved_output = os.path.abspath(output_path) if output_path else ""
        effective_timeout = int(timeout_sec) if timeout_sec is not None else int(pipeline.timeout_sec or 120)
        start = time.monotonic()
        try:
            file_size = os.path.getsize(input_path)
        except OSError:
            file_size = -1
        print(
            f"[Import] Converting via pipeline='{pipeline.id}' label='{pipeline.label}' "
            f"input='{input_path}' size={file_size} output='{resolved_output or '-'}' timeout={effective_timeout}s"
        )

        if pipeline.argv:
            argv = [self._substitute(t, input_path, resolved_output) for t in pipeline.argv]
            exe = argv[0] if argv else ""
            if exe and shutil.which(exe) is None:
                raise DocumentConversionError(f"Pipeline executable not found: {exe}")
            print(f"[Import] Running argv: {argv}")
            result = subprocess.run(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=effective_timeout,
                check=False,
            )
        elif pipeline.shell:
            # Advanced option: user-supplied shell pipeline.
            cmd = self._substitute(pipeline.shell, input_path, resolved_output)
            print(f"[Import] Running shell: {cmd}")
            result = subprocess.run(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=effective_timeout,
                check=False,
            )
        else:
            raise DocumentConversionError(f"Pipeline '{pipeline.id}' has no argv or shell command configured.")

        elapsed_ms = int((time.monotonic() - start) * 1000)
        stdout_len = len(result.stdout or b"")
        stderr_len = len(result.stderr or b"")
        print(
            f"[Import] Pipeline finished exit={result.returncode} "
            f"stdout={stdout_len}B stderr={stderr_len}B elapsed={elapsed_ms}ms"
        )

        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            raise DocumentConversionError(
                f"Conversion failed (exit {result.returncode}) for pipeline '{pipeline.id}'.\n{stderr}"
            )

        text = (result.stdout or b"").decode("utf-8", errors="replace")
        if not text.strip() and resolved_output and os.path.exists(resolved_output):
            try:
                with open(resolved_output, "r", encoding="utf-8", errors="replace") as handle:
                    text = handle.read()
                print(f"[Import] Read output file: '{resolved_output}' chars={len(text)}")
            except OSError as e:
                print(f"[Import] Failed reading output file '{resolved_output}': {e}")

        return text

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    def _get_pipeline(self, pipeline_id: str) -> DocumentPipeline:
        for pipeline in self._pipelines:
            if pipeline.id == pipeline_id:
                return pipeline
        raise DocumentConversionError(f"Unknown pipeline id: {pipeline_id}")

    @staticmethod
    def _substitute(template: str, input_path: str, output_path: str) -> str:
        return (
            template.replace("{input}", input_path)
            .replace("{output}", output_path)
        )

    @classmethod
    def _parse_pipelines(cls, pipelines_json: str) -> List[DocumentPipeline]:
        raw = (pipelines_json or "").strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        pipelines: List[DocumentPipeline] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("id", "")).strip()
            label = str(item.get("label", pid or "Pipeline")).strip()
            exts = item.get("extensions") or []
            if isinstance(exts, str):
                exts = [exts]
            if not pid or not isinstance(exts, list) or not exts:
                continue

            argv = item.get("argv")
            shell = item.get("shell")
            output_ext = str(item.get("output_ext", ".txt") or ".txt")
            timeout_sec = item.get("timeout_sec", 120)
            if argv is not None and not isinstance(argv, list):
                argv = None
            if shell is not None and not isinstance(shell, str):
                shell = None
            try:
                timeout_sec = int(timeout_sec)
            except Exception:
                timeout_sec = 120

            pipelines.append(
                DocumentPipeline(
                    id=pid,
                    label=label,
                    extensions=tuple(str(e).lower() for e in exts if str(e).strip()),
                    argv=tuple(str(t) for t in argv) if argv else None,
                    shell=shell.strip() if shell else None,
                    output_ext=output_ext if output_ext.startswith(".") else f".{output_ext}",
                    timeout_sec=max(1, timeout_sec),
                )
            )
        return pipelines
