"""Creates the private RAG datastore in Google Cloud AI Applications (Vertex AI Search).

Steps (each one is skipped if it already exists, so the script is safe to re-run):
  1. Create a Cloud Storage bucket and upload the documents in ./corpus
  2. Create an AI Applications data store (unstructured documents)
  3. Import the documents from Cloud Storage into the data store
  4. Create a search app (engine) on top of the data store
  5. Wait until the documents are indexed and a test query returns results

Usage (from the challenge-2-rag folder, with rag_agent/.env filled in):
    python setup_datastore.py
"""

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google.api_core.exceptions import AlreadyExists, Conflict, NotFound
from google.cloud import discoveryengine_v1 as de
from google.cloud import storage

HERE = Path(__file__).parent
load_dotenv(HERE / "rag_agent" / ".env")

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.getenv("DATASTORE_LOCATION", "global")
DATASTORE_ID = os.getenv("DATASTORE_SHORT_ID", "lumora-internal-docs")
ENGINE_ID = os.getenv("ENGINE_ID", "lumora-internal-search")
BUCKET = os.getenv("GCS_BUCKET", f"{PROJECT}-lumora-corpus")
BUCKET_LOCATION = os.getenv("GCS_BUCKET_LOCATION", "US")
CORPUS_DIR = HERE / "corpus"

COLLECTION = f"projects/{PROJECT}/locations/{LOCATION}/collections/default_collection"
DATASTORE_PATH = f"{COLLECTION}/dataStores/{DATASTORE_ID}"


def step(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def upload_corpus() -> str:
    step(f"Uploading corpus to gs://{BUCKET}/corpus/")
    client = storage.Client(project=PROJECT)
    try:
        bucket = client.create_bucket(BUCKET, location=BUCKET_LOCATION)
        print(f"    created bucket {BUCKET}")
    except Conflict:
        bucket = client.bucket(BUCKET)
        print(f"    bucket {BUCKET} already exists")
    files = sorted(CORPUS_DIR.glob("*.txt"))
    if not files:
        sys.exit(f"No .txt files found in {CORPUS_DIR}")
    for f in files:
        bucket.blob(f"corpus/{f.name}").upload_from_filename(str(f), content_type="text/plain")
        print(f"    uploaded {f.name}")
    return f"gs://{BUCKET}/corpus/*.txt"


def create_datastore() -> None:
    step(f"Creating data store {DATASTORE_ID}")
    client = de.DataStoreServiceClient()
    try:
        op = client.create_data_store(
            parent=COLLECTION,
            data_store_id=DATASTORE_ID,
            data_store=de.DataStore(
                display_name="Lumora internal documents",
                industry_vertical=de.IndustryVertical.GENERIC,
                solution_types=[de.SolutionType.SOLUTION_TYPE_SEARCH],
                content_config=de.DataStore.ContentConfig.CONTENT_REQUIRED,
            ),
        )
        op.result(timeout=300)
        print("    created")
    except AlreadyExists:
        print("    already exists")


def import_documents(gcs_uri: str) -> None:
    step(f"Importing documents from {gcs_uri}")
    client = de.DocumentServiceClient()
    op = client.import_documents(
        request=de.ImportDocumentsRequest(
            parent=f"{DATASTORE_PATH}/branches/default_branch",
            gcs_source=de.GcsSource(input_uris=[gcs_uri], data_schema="content"),
            # FULL replaces the data store contents with exactly what is in the bucket.
            reconciliation_mode=de.ImportDocumentsRequest.ReconciliationMode.FULL,
        )
    )
    print("    import started, waiting (this usually takes 1-5 minutes)...", flush=True)
    result = op.result(timeout=1800)
    meta = op.metadata  # ImportDocumentsMetadata
    print(f"    import finished: success={meta.success_count} failures={meta.failure_count}")
    for err in list(result.error_samples)[:5]:
        print(f"    error sample: {err.message}")


def create_engine() -> None:
    step(f"Creating search app {ENGINE_ID}")
    client = de.EngineServiceClient()
    try:
        op = client.create_engine(
            parent=COLLECTION,
            engine_id=ENGINE_ID,
            engine=de.Engine(
                display_name="Lumora internal search",
                solution_type=de.SolutionType.SOLUTION_TYPE_SEARCH,
                industry_vertical=de.IndustryVertical.GENERIC,
                data_store_ids=[DATASTORE_ID],
                search_engine_config=de.Engine.SearchEngineConfig(
                    search_tier=de.SearchTier.SEARCH_TIER_ENTERPRISE,
                    search_add_ons=[de.SearchAddOn.SEARCH_ADD_ON_LLM],
                ),
            ),
        )
        op.result(timeout=300)
        print("    created")
    except AlreadyExists:
        print("    already exists")


def wait_until_searchable(query: str = "How many days of annual leave do employees get?") -> None:
    step(f"Waiting for indexing (test query: {query!r})")
    client = de.SearchServiceClient()
    serving_config = f"{COLLECTION}/engines/{ENGINE_ID}/servingConfigs/default_search"
    for attempt in range(40):
        try:
            resp = client.search(
                request=de.SearchRequest(serving_config=serving_config, query=query, page_size=3)
            )
            results = list(resp.results)
            if results:
                print(f"    searchable: {len(results)} result(s), top hit = {results[0].document.name.rsplit('/', 1)[-1]}")
                return
        except NotFound:
            pass
        print(f"    not indexed yet (check {attempt + 1}/40), retrying in 30s...", flush=True)
        time.sleep(30)
    print("    WARNING: still no results after 20 minutes. Indexing can take longer; try the agent later.")


def main() -> None:
    print(f"Project: {PROJECT} | location: {LOCATION}")
    gcs_uri = upload_corpus()
    create_datastore()
    import_documents(gcs_uri)
    create_engine()
    wait_until_searchable()
    print("\nDone. Put this value in rag_agent/.env:")
    print(f"DATASTORE_ID={DATASTORE_PATH}")


if __name__ == "__main__":
    main()
