# Releasing aap_snapshot

This guide describes the maintainer process for staging and publishing a new
version of the `ansible.aap_snapshot` collection.

## Stage the release

1. Open the **Stage Collection Release** workflow:
   https://github.com/ansible-collections/aap-snapshot-collection/actions/workflows/stage-release.yml
2. Choose **Run workflow**, select the `main` branch, enter the version to
   release (for example, `1.2.0`), and start the workflow. The selected branch
   is used as the base for the release pull request, so run it from `main`.
3. Wait for the `stage-release` job to finish. It updates the version in
   `galaxy.yml`, generates the changelog from the pending fragments, pushes a
   `release/<version>` branch, and opens a pull request against `main`.

## Review and merge the release pull request

Review the generated pull request. Check that the version in `galaxy.yml` and
the generated changelog are correct, then approve and merge the pull request.

## Review and publish the draft release

After the pull request is merged, the **Create Draft Release** workflow runs.
Open that workflow run and find the draft release link in the **Create draft
GitHub Release** step. Review the generated release notes and add a **Highlights**
section if needed. Confirm the version and tag, then click **Publish**.

## Verify publication and notify CRC

Publishing the GitHub Release triggers Zuul to build and publish the
collection. Wait for the Zuul build and publish job to succeed, then notify the
`#ansible-partners` channel about the release for CRC. Include the version and
the published GitHub Release link in the message.
