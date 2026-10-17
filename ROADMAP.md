# Roadmap

This document tracks supported migration paths, planned enhancements, and
features for consideration for the `ansible.aap_snapshot` collection.

## Current

### Migration paths

| Source | Target | Status |
|--------|--------|--------|
| RPM Installer | OCP Operator | **Supported** |
| RPM Installer | Containerized Installer | Planned |
| Containerized Installer | OCP Operator | Planned |
| Containerized Installer | Containerized Installer | Planned |
| OCP Operator | OCP Operator | Planned |

## Long-term

### Upload export artifacts to cloud object storage

Support uploading export artifacts directly to S3-compatible or Azure Blob
Storage backends. This would allow operators to store migration artifacts in
durable, centralized storage rather than relying solely on local filesystem
paths.

**Potential scope:**

- AWS S3 and S3-compatible stores (MinIO, Ceph RGW)
- Azure Blob Storage
- Configurable bucket/container, prefix, and credentials
- Optional integration with `artifact_import` to pull directly from a remote
  URI instead of a local `artifact_file` path

## Features for consideration

### Import Automation Hub content into object storage

Importing Automation Hub content into S3-compatible or Azure Blob object
storage is a feature for consideration. **This work is not currently scoped,
and there is no committed delivery timeline.** The collection does not
currently support importing Hub content into these storage backends.

Customers whose target Hub uses S3-compatible or Azure Blob object storage
must pre-populate that storage with the source Hub content outside the
collection, then run the collection using an artifact exported without Hub
content. See [Automation Hub Content Storage](README.md#automation-hub-content-storage)
for the required preparation.

This feature concerns Hub's content storage backend, separately from storing
the migration artifact archive in cloud object storage as described above.
