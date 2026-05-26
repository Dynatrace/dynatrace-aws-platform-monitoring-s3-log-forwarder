# GitHub Release Guide

This guide describes how to publish a GitHub release for the Dynatrace AWS S3 Log Forwarder using the `publish_github_release.sh` script.

## Prerequisites

- [GitHub CLI (`gh`)](https://cli.github.com) installed and authenticated:
  ```bash
  gh auth login
  ```

## What the Script Does

1. Verifies that `gh` is installed and authenticated
2. Fetches all tags from the remote repository
3. Resolves or validates the release tag
4. Validates that all release assets exist locally
5. Prints a release summary and asks for confirmation
6. Packages all assets into a single `.zip` file
7. Creates the GitHub release with the zip attached
8. Cleans up the temporary zip file

## Usage

```bash
./scripts/publish_github_release.sh (--major | --minor | --patch | <tag>) [OPTIONS]
```

### Tag Selection (exactly one required)

| Argument | Description | Example (from `v1.2.3`) |
|---|---|---|
| `--patch` | Increment patch version | `v1.2.3` → `v1.2.4` |
| `--minor` | Increment minor version | `v1.2.3` → `v1.3.0` |
| `--major` | Increment major version | `v1.2.3` → `v2.0.0` |
| `<tag>` | Use an explicit tag | `v1.2.3` |

When using `--patch`, `--minor`, or `--major`, the script automatically detects the latest semver tag in the repository (ignoring non-semver tags such as `v1.0-beta`) and computes the next version accordingly. The auto-detected tag is printed to the console before the summary.

### Options

| Option | Description |
|---|---|
| `--draft` | Create the release as a draft (not publicly visible until published) |
| `--notes "<text>"` | Custom release notes. If omitted, notes are auto-generated from merged pull requests |
| `-h`, `--help` | Print usage information |

### Examples

```bash
# Increment minor version with auto-generated notes
./scripts/publish_github_release.sh --minor

# Increment patch version and create as a draft
./scripts/publish_github_release.sh --patch --draft

# Increment major version with custom notes
./scripts/publish_github_release.sh --major --notes "Breaking changes: ..."

# Publish a specific explicit tag
./scripts/publish_github_release.sh v2.0.0

# Publish an explicit tag as a draft with custom notes
./scripts/publish_github_release.sh v2.0.0 --draft --notes "Initial release candidate"
```

## Release Assets

The following files are bundled into a single zip archive (`dynatrace-aws-s3-log-forwarder-<tag>.zip`) and attached to the release:

| File | Description |
|---|---|
| `template.yaml` | Main SAM/CloudFormation deployment template |
| `dynatrace-aws-s3-log-forwarder-s3-bucket-configuration.yaml` | S3 bucket configuration template |
| `dynatrace-aws-s3-log-forwarder-appconfig.yaml` | AppConfig configuration template |
| `eventbridge-cross-region-or-account-forward-rules.yaml` | EventBridge cross-region/account forwarding rules template |
| `dynatrace-aws-s3-log-forwarder-layer.yaml` | Lambda Layer CloudFormation template |

## Auto-generated Release Notes

When `--notes` is not provided, the script passes `--generate-notes` to the GitHub CLI. GitHub then automatically generates release notes based on pull requests merged since the previous release tag, grouped by their labels.

## Draft Releases

When `--draft` is used:
- The release is saved on GitHub but is **not publicly visible**
- The git tag is **not created** until the draft is published
- You can review and edit the release on GitHub before publishing it
- To publish the draft: `gh release edit <tag> --draft=false`

## Tag Validation

The script enforces the following rules for tags:

- Must follow the `vMAJOR.MINOR.PATCH` format (e.g. `v1.2.3`)
- Must not already exist in the repository

When using bump flags (`--major`, `--minor`, `--patch`), only tags strictly matching `vMAJOR.MINOR.PATCH` are considered for the latest version detection. Non-semver tags (e.g. `v1.0-beta`, `v2.0-rc1`) are ignored.

