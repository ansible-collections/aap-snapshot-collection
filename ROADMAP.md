# Roadmap

This document tracks planned features and enhancements for the
`ansible.aap_snapshot` collection.

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
