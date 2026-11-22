"""Download the embedding model at image build time, so the container needs no internet for it.

The Dockerfile runs this, then sets HF_HUB_OFFLINE=1 for runtime. EMBEDDING_MODEL can be passed as a build arg.
"""

import os

from sentence_transformers import SentenceTransformer


def main() -> None:
    name = os.getenv("EMBEDDING_MODEL", "").strip() or "sdadas/mmlw-roberta-base"
    model = SentenceTransformer(name, device="cpu")
    dim = model.get_embedding_dimension()
    print(f"[download_models] {name}: {dim} dimensions, cached for offline use")


if __name__ == "__main__":
    main()
