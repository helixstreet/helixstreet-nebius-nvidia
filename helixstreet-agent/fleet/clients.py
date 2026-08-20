"""Lazy singletons for Google Cloud clients so modules import without credentials."""
from functools import lru_cache

from . import config


@lru_cache(maxsize=1)
def firestore():
    from google.cloud import firestore as _fs

    return _fs.Client(project=config.PROJECT_ID)


@lru_cache(maxsize=1)
def storage():
    from google.cloud import storage as _gcs

    return _gcs.Client(project=config.PROJECT_ID)


@lru_cache(maxsize=1)
def bigquery():
    from google.cloud import bigquery as _bq

    return _bq.Client(project=config.PROJECT_ID)


@lru_cache(maxsize=1)
def dlp():
    from google.cloud import dlp_v2

    return dlp_v2.DlpServiceClient()


@lru_cache(maxsize=1)
def batch():
    from google.cloud import batch_v1

    return batch_v1.BatchServiceClient()
