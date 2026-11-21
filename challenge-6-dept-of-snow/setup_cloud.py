"""Creates the Google Cloud resources for the ADS agent (safe to re-run).

  1. Cloud Storage bucket <project>-ads-data with
       policies/*.txt          ADS policy and procedure documents
       backend/*.jsonl         ADS operations records (roads, plows, closures, incidents, requests)
  2. AI Applications datastore "ads-policy-docs"        (unstructured documents) -> RAG grounding
  3. AI Applications datastore "ads-operations-backend" (structured JSON records) -> ADS backend MCP server
  4. Imports both from Cloud Storage
  5. Search app "ads-policy-search" on the policy datastore, then waits until it returns results

Usage (from the challenge-6-dept-of-snow folder, with ads_agent/.env filled in):
    python setup_cloud.py
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
load_dotenv(HERE / "ads_agent" / ".env")

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
COLLECTION = f"projects/{PROJECT}/locations/global/collections/default_collection"
BUCKET = os.getenv("GCS_BUCKET", f"{PROJECT}-ads-data")
POLICY_DS = "ads-policy-docs"
OPS_DS = "ads-operations-backend"
POLICY_ENGINE = "ads-policy-search"


def step(msg):
    print(f"\n==> {msg}", flush=True)


def upload() -> None:
    step(f"Uploading data to gs://{BUCKET}")
    client = storage.Client(project=PROJECT)
    try:
        bucket = client.create_bucket(BUCKET, location="US")
        print("    created bucket")
    except Conflict:
        bucket = client.bucket(BUCKET)
        print("    bucket exists")
    for f in sorted((HERE / "data" / "policies").glob("*.txt")):
        bucket.blob(f"policies/{f.name}").upload_from_filename(str(f), content_type="text/plain")
        print(f"    policies/{f.name}")
    f = HERE / "data" / "backend" / "ads_operations.jsonl"
    bucket.blob(f"backend/{f.name}").upload_from_filename(str(f), content_type="application/json")
    print(f"    backend/{f.name}")


def create_datastore(ds_id: str, display: str, content: de.DataStore.ContentConfig) -> None:
    step(f"Creating datastore {ds_id}")
    try:
        de.DataStoreServiceClient().create_data_store(
            parent=COLLECTION, data_store_id=ds_id,
            data_store=de.DataStore(
                display_name=display, industry_vertical=de.IndustryVertical.GENERIC,
                solution_types=[de.SolutionType.SOLUTION_TYPE_SEARCH], content_config=content,
            ),
        ).result(timeout=300)
        print("    created")
    except AlreadyExists:
        print("    exists")


def import_docs(ds_id: str, uri: str, schema: str, id_field: str | None = None) -> None:
    step(f"Importing {uri} into {ds_id}")
    request = de.ImportDocumentsRequest(
        parent=f"{COLLECTION}/dataStores/{ds_id}/branches/default_branch",
        gcs_source=de.GcsSource(input_uris=[uri], data_schema=schema),
        reconciliation_mode=de.ImportDocumentsRequest.ReconciliationMode.FULL,
    )
    if id_field:
        request.id_field = id_field
    op = de.DocumentServiceClient().import_documents(request=request)
    result = op.result(timeout=1800)
    print(f"    success={op.metadata.success_count} failures={op.metadata.failure_count}")
    for err in list(result.error_samples)[:3]:
        print(f"    error: {err.message}")


def create_engine() -> None:
    step(f"Creating search app {POLICY_ENGINE}")
    try:
        de.EngineServiceClient().create_engine(
            parent=COLLECTION, engine_id=POLICY_ENGINE,
            engine=de.Engine(
                display_name="ADS policy search", solution_type=de.SolutionType.SOLUTION_TYPE_SEARCH,
                industry_vertical=de.IndustryVertical.GENERIC, data_store_ids=[POLICY_DS],
                search_engine_config=de.Engine.SearchEngineConfig(
                    search_tier=de.SearchTier.SEARCH_TIER_ENTERPRISE,
                    search_add_ons=[de.SearchAddOn.SEARCH_ADD_ON_LLM],
                ),
            ),
        ).result(timeout=300)
        print("    created")
    except AlreadyExists:
        print("    exists")


def wait_searchable() -> None:
    step("Waiting until policy documents are searchable")
    client = de.SearchServiceClient()
    serving = f"{COLLECTION}/engines/{POLICY_ENGINE}/servingConfigs/default_search"
    for i in range(40):
        try:
            res = list(client.search(request=de.SearchRequest(
                serving_config=serving, query="When does plowing start on Priority 1 routes?", page_size=3)).results)
            if res:
                print(f"    searchable ({len(res)} results)")
                return
        except NotFound:
            pass
        print(f"    not indexed yet ({i + 1}/40), retrying in 30s", flush=True)
        time.sleep(30)
    print("    WARNING: not searchable after 20 minutes; indexing may still finish later")


def check_backend() -> None:
    step("Checking backend records")
    docs = list(de.DocumentServiceClient().list_documents(request=de.ListDocumentsRequest(
        parent=f"{COLLECTION}/dataStores/{OPS_DS}/branches/default_branch", page_size=200)))
    print(f"    {len(docs)} records in {OPS_DS}")


if __name__ == "__main__":
    print(f"Project: {PROJECT}")
    upload()
    create_datastore(POLICY_DS, "ADS policy and procedure documents", de.DataStore.ContentConfig.CONTENT_REQUIRED)
    create_datastore(OPS_DS, "ADS operations backend records", de.DataStore.ContentConfig.NO_CONTENT)
    import_docs(POLICY_DS, f"gs://{BUCKET}/policies/*.txt", "content")
    import_docs(OPS_DS, f"gs://{BUCKET}/backend/*.jsonl", "custom", id_field="id")
    create_engine()
    check_backend()
    wait_searchable()
    print("\nDone. Datastore IDs for ads_agent/.env:")
    print(f"POLICY_DATASTORE_ID={COLLECTION}/dataStores/{POLICY_DS}")
    print(f"OPS_DATASTORE_ID={COLLECTION}/dataStores/{OPS_DS}")
