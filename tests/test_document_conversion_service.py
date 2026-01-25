import os
import sys
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_parses_default_pipelines():
    from config import DEFAULT_DOCUMENT_IMPORT_PIPELINES_JSON
    from services.document_conversion_service import DocumentConversionService

    svc = DocumentConversionService(DEFAULT_DOCUMENT_IMPORT_PIPELINES_JSON)
    assert svc.pipelines
    assert any(".pdf" in p.extensions for p in svc.pipelines)


def test_substitution_in_argv():
    from services.document_conversion_service import DocumentConversionService

    pipelines = [
        {
            "id": "p",
            "label": "P",
            "extensions": [".pdf"],
            "argv": ["echo", "{input}", "{output}"],
            "output_ext": ".txt",
        }
    ]
    svc = DocumentConversionService(json.dumps(pipelines))
    p = svc.pipelines[0]
    assert p.id == "p"
    assert p.output_ext == ".txt"


def test_invalid_json_yields_no_pipelines():
    from services.document_conversion_service import DocumentConversionService

    svc = DocumentConversionService("{not json")
    assert svc.pipelines == []

