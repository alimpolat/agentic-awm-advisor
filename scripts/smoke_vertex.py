"""Day-1 smoke test: verify Vertex AI auth + both Gemini models respond.

Run from the repo root:  uv run python scripts/smoke_vertex.py
Expected: two short 'Hello' replies naming each model.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm.vertex_client import generate  # noqa: E402
from app.settings import settings  # noqa: E402


def main() -> int:
    print(f"project={settings.gcp_project_id} location={settings.gcp_location}")
    ok = True
    for model in (settings.gemini_model_pro, settings.gemini_model_flash):
        try:
            r = generate(model, "Say 'Hello' and name the model you are, in one sentence.")
            print(f"[{model}] -> {r.text.strip()}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"[{model}] FAILED: {type(e).__name__}: {e}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
