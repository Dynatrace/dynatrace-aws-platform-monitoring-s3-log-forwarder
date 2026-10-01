#!/bin/bash

# (Re)create the permanent stacks used by the e2e-test-upgrade CI job, from the LATEST GitHub RELEASE
# (the version a customer would be upgrading from; CI then upgrades them to the code under test).
#
# Per region (us-east-1, eu-central-1) this deploys, as in docs/deployment_guide.md:
#   1. <STACK_NAME>         - forwarder (template.yaml, Lambda Layer, NotificationType=EventBridge)
#   2. <STACK_NAME>-s3-cfg  - per-bucket EventBridge rule limited to prefix test/verification/
#
# Safe to re-run: existing stacks are updated in place. To start from scratch, delete the stacks first.
#
# Usage: ./scripts/create_stacks_for_e2e_upgrade_test.sh
#
# Requires: aws CLI, curl, unzip, AWS credentials for the account that owns the buckets.
# The buckets must already exist, in the same region as the forwarder.
#
# Required environment variables:
#   export DT_TENANT_PLATFORM_URL="https://<tenant>.apps.dynatrace.com"
#   export DT_TOKEN_SECRET_ARN_US_EAST_1="arn:aws:secretsmanager:us-east-1:<account>:secret:<name>"
#   export DT_TOKEN_SECRET_ARN_EU_CENTRAL_1="arn:aws:secretsmanager:eu-central-1:<account>:secret:<name>"
#
# Optional:
#   CFN_ROLE_ARN   IAM role CloudFormation assumes for deployments (as in CI)
#   VERSION_TAG    release tag to deploy instead of the latest one (e.g. v1.1.0); also skips the API lookup
#   GITHUB_TOKEN   used for GitHub requests if the gh CLI is not logged in (avoids API rate limits)
#   REGIONS        space separated subset of regions (default: "us-east-1 eu-central-1")
#   DRY_RUN=true   print the deploy commands without executing them

set -euo pipefail

: "${DT_TENANT_PLATFORM_URL:?DT_TENANT_PLATFORM_URL must be set}"
: "${DT_TOKEN_SECRET_ARN_US_EAST_1:?DT_TOKEN_SECRET_ARN_US_EAST_1 must be set}"
: "${DT_TOKEN_SECRET_ARN_EU_CENTRAL_1:?DT_TOKEN_SECRET_ARN_EU_CENTRAL_1 must be set}"

REPO="dynatrace/dynatrace-aws-platform-monitoring-s3-log-forwarder"
STACK_NAME="permanent-s3-log-forwarder-main-branch"
ARCH="x86_64"
LOGS_PREFIX="test/verification/"
: "${REGIONS:=us-east-1 eu-central-1}"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }

run() {
    if [[ "${DRY_RUN:-false}" == "true" ]]; then
        echo "[DRY RUN] $*"
    else
        "$@"
    fi
}

# Per-region config (case statements: macOS ships bash 3.2, which has no associative arrays)
bucket_for_region() { echo "permanent-s3-log-forwarder-main-branch-version-$1"; }
secret_for_region() {
    case "$1" in
        us-east-1)    echo "${DT_TOKEN_SECRET_ARN_US_EAST_1}" ;;
        eu-central-1) echo "${DT_TOKEN_SECRET_ARN_EU_CENTRAL_1}" ;;
        *) echo "ERROR: unsupported region '$1'" >&2; return 1 ;;
    esac
}

ROLE_ARGS=()
[[ -n "${CFN_ROLE_ARN:-}" ]] && ROLE_ARGS+=(--role-arn "${CFN_ROLE_ARN}")

# Download the CloudFormation templates of the latest release (deployment_guide.md, Step 4)
#   The unauthenticated GitHub API is limited to 60 requests/hour per IP (HTTP 403 when exceeded), so an
#   authenticated gh CLI or GITHUB_TOKEN is used when available.
WORK_DIR=$(mktemp -d)
trap 'rm -rf "${WORK_DIR}"' EXIT

USE_GH=false
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then USE_GH=true; fi

if [[ -z "${VERSION_TAG:-}" ]]; then
    if [[ "${USE_GH}" == "true" ]]; then
        VERSION_TAG=$(gh release view --repo "${REPO}" --json tagName --jq .tagName)
    else
        AUTH_ARGS=()
        [[ -n "${GITHUB_TOKEN:-}" ]] && AUTH_ARGS+=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
        VERSION_TAG=$(curl -fsS ${AUTH_ARGS[@]+"${AUTH_ARGS[@]}"} "https://api.github.com/repos/${REPO}/releases/latest" | grep tag_name | cut -d'"' -f4) || {
            echo "ERROR: GitHub API request failed (403 usually means rate limit). Run 'gh auth login', set GITHUB_TOKEN, or set VERSION_TAG (e.g. v1.1.0)." >&2
            exit 1
        }
    fi
fi
[[ -n "${VERSION_TAG}" ]] || { echo "ERROR: could not determine the latest release tag" >&2; exit 1; }

log "Downloading templates.zip for release ${VERSION_TAG}"
if [[ "${USE_GH}" == "true" ]]; then
    gh release download "${VERSION_TAG}" --repo "${REPO}" --pattern templates.zip --dir "${WORK_DIR}"
else
    curl -fsSL -o "${WORK_DIR}/templates.zip" \
        "https://github.com/${REPO}/releases/download/${VERSION_TAG}/templates.zip"
fi
unzip -q "${WORK_DIR}/templates.zip" -d "${WORK_DIR}"

for REGION in ${REGIONS}; do
    BUCKET=$(bucket_for_region "${REGION}")
    SECRET_ARN=$(secret_for_region "${REGION}")

    log "=== ${REGION} | release ${VERSION_TAG} | stack ${STACK_NAME} | bucket ${BUCKET} ==="

    # The layer ARN is resolved by the template from its built-in region map (DynatraceS3LogForwarderLayerArn unset).
    # GrantReadPermissionToBuckets is left empty: read access and the EventBridge rule are scoped to the
    # prefix by the per-bucket stack below, instead of covering the whole bucket.
    log "Deploying forwarder stack"
    run aws cloudformation deploy \
        --region "${REGION}" \
        --stack-name "${STACK_NAME}" \
        --template-file "${WORK_DIR}/template.yaml" \
        --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
        --no-fail-on-empty-changeset \
        --parameter-overrides \
            DynatraceEnvironmentURL="${DT_TENANT_PLATFORM_URL}" \
            DynatraceApiKeySecretsManagerSecret="${SECRET_ARN}" \
            EnableCrossRegionCrossAccountForwarding=true \
            Architecture="${ARCH}" \
            NotificationType=EventBridge \
            DynatraceS3LogForwarderLayerArn="" \
        ${ROLE_ARGS[@]+"${ROLE_ARGS[@]}"}

    log "Enabling EventBridge notifications on bucket ${BUCKET}"
    run aws s3api put-bucket-notification-configuration \
        --region "${REGION}" \
        --bucket "${BUCKET}" \
        --notification-configuration '{"EventBridgeConfiguration":{}}'

    log "Deploying per-bucket S3 configuration stack (prefix: ${LOGS_PREFIX})"
    run aws cloudformation deploy \
        --region "${REGION}" \
        --stack-name "${STACK_NAME}-s3-cfg" \
        --template-file "${WORK_DIR}/dynatrace-aws-s3-log-forwarder-s3-bucket-configuration.yaml" \
        --capabilities CAPABILITY_IAM \
        --no-fail-on-empty-changeset \
        --parameter-overrides \
            DynatraceAwsS3LogForwarderStackName="${STACK_NAME}" \
            LogsBucketName="${BUCKET}" \
            LogsBucketPrefix1="${LOGS_PREFIX}" \
        ${ROLE_ARGS[@]+"${ROLE_ARGS[@]}"}

    log "=== Done: ${REGION} ==="
done

log "Permanent stacks are at release ${VERSION_TAG}; the CI upgrade job will upgrade them from here."
