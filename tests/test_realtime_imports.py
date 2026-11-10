"""Voice metadata must remain usable without the audio engine dependencies."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_voice_metadata_does_not_import_audio_engines(tmp_path):
    script = textwrap.dedent("""
        import importlib.abc
        import sys
        import types

        class BlockAudioImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname in ('sounddevice', 'numpy', 'realtime.openai', 'realtime.xai'):
                    raise ModuleNotFoundError(fullname)

        sys.meta_path.insert(0, BlockAudioImports())
        import realtime
        from realtime.voices import get_realtime_voices

        assert 'alloy' in get_realtime_voices('openai')
        assert 'Ara' in get_realtime_voices('grok')
        assert 'realtime.openai' not in sys.modules
        assert 'sounddevice' not in sys.modules

        # Preserve the existing package-level provider import for callers.
        engine = types.ModuleType('realtime.openai')
        engine.OpenAIWebSocketProvider = type('Provider', (), {})
        sys.modules['realtime.openai'] = engine
        from realtime import OpenAIWebSocketProvider
        assert OpenAIWebSocketProvider is engine.OpenAIWebSocketProvider
        try:
            realtime.missing_attribute
        except AttributeError:
            pass
        else:
            raise AssertionError('Unknown attribute did not raise AttributeError')
    """)
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
