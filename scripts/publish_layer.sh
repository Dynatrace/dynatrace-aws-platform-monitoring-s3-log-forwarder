#!/bin/bash

# Copyright 2024 Dynatrace LLC
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#      https://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Publish the Lambda Layer to one or more AWS regions with public access.
# Assumes the layer has already been built with build_docker.sh layer.
#
# Usage:
#   ./scripts/publish_layer.sh <zip>                                              # All commercial regions (x86_64)
#   ./scripts/publish_layer.sh <zip> --arch arm64                                 # arm64 layer
#   ./scripts/publish_layer.sh <zip> --regions us-east-1,eu-west-1,eu-central-1  # Specific regions
#   ./scripts/publish_layer.sh <zip> --no-update-files                            # Skip template.yaml update
#   ./scripts/publish_layer.sh <zip> --arns-output arns.txt                       # Also write region=arn pairs

set -e

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
ZIP_FILE="${1:?Usage: $0 <zip> [--arch x86_64|arm64] [--regions r1,r2,...]}"
ARCH="x86_64"
REGIONS=()
FAILED_REGIONS=()
PUBLISHED_ARNS=()          # Entries in the form "region=arn"
PERMISSION_FAILED_ARNS=()  # Published, but not made public — see the summary
UPDATE_FILES=true
ARNS_OUTPUT=""             # Optional file to write "region=arn" pairs to

# Regions excluded from the publish.
# These are regions where Lambda Layer publishing is not supported or not desired.
EXCLUDED_REGIONS=(me-central-1 me-south-1)

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

parse_args() {
    local idx=2
    while [[ $idx -le $# ]]; do
        case "${!idx}" in
            --arch)
                idx=$((idx + 1))
                ARCH="${!idx:?--arch requires a value}"
                ;;
            --regions)
                idx=$((idx + 1))
                IFS=',' read -ra REGIONS <<< "${!idx:?--regions requires a value}"
                ;;
            --no-update-files)
                UPDATE_FILES=false
                ;;
            --arns-output)
                idx=$((idx + 1))
                ARNS_OUTPUT="${!idx:?--arns-output requires a value}"
                ;;
            *)
                echo "Unknown option: ${!idx}"
                echo "Usage: $0 <zip> [--arch x86_64|arm64] [--regions r1,r2,...] [--no-update-files] [--arns-output <file>]"
                exit 1
                ;;
        esac
        idx=$((idx + 1))
    done
}

# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------

publish_to_region() {
    local region="$1"
    echo "--- Publishing to $region ---"

    local layer_version_arn
    layer_version_arn=$(aws lambda publish-layer-version \
        --region "$region" \
        --layer-name "$LAYER_NAME" \
        --zip-file "fileb://$ZIP_FILE" \
        --compatible-runtimes python3.14 \
        --compatible-architectures "$ARCH" \
        --description "$LAYER_DESCRIPTION" \
        --query 'LayerVersionArn' \
        --output text) || {
        echo "  FAILED to publish in $region"
        FAILED_REGIONS+=("$region")
        return
    }

    local layer_version="${layer_version_arn##*:}"
    echo "  Published: $layer_version_arn"

    aws lambda add-layer-version-permission \
        --region "$region" \
        --layer-name "$LAYER_NAME" \
        --version-number "$layer_version" \
        --statement-id allow-all-accounts \
        --principal "*" \
        --action lambda:GetLayerVersion \
        --output json > /dev/null || {
        # The layer version already exists at this point and has consumed a version
        # number in this region. Re-running the publish would burn another one and
        # push the region further out of step with the rest, so record it separately
        # and print the narrower remediation in the summary instead.
        echo "  FAILED to grant public access in $region"
        FAILED_REGIONS+=("$region")
        PERMISSION_FAILED_ARNS+=("$region=$layer_version_arn")
        return
    }
    PUBLISHED_ARNS+=("$region=$layer_version_arn")
}

# ---------------------------------------------------------------------------
# Update template.yaml — rewrite Mappings.LayerArns.<region>.{x86|arm64} with
# the fully-qualified ARN actually returned for each region. Layer version
# numbers are a per-region counter in AWS and are not synchronized across
# regions, so every region gets its own ARN and regions we did not publish to
# are left untouched.
# ---------------------------------------------------------------------------

update_template() {
    local template_file="$REPO_ROOT/template.yaml"
    [[ -f "$template_file" ]] || return

    [[ ${#PUBLISHED_ARNS[@]} -gt 0 ]] || { echo "No published ARNs — skipping template update."; return; }

    local arch_key
    [[ "$ARCH" == "arm64" ]] && arch_key="arm64" || arch_key="x86"

    echo "Updating Mappings.LayerArns (${arch_key}) in $template_file..."
    printf '%s\n' "${PUBLISHED_ARNS[@]}" \
        | python3 "$REPO_ROOT/scripts/update_layer_arns.py" \
            --template "$template_file" \
            --arch-key "$arch_key"
}

# ---------------------------------------------------------------------------
# Write the "region=arn" pairs to a file so another job — which gets its own
# fresh checkout and therefore none of the template edits made above — can apply
# the same ARNs. Layer versions differ per region, so the pairs must be passed
# through in full; a single version number cannot represent the publish result.
# ---------------------------------------------------------------------------

write_arns_output() {
    [[ -n "$ARNS_OUTPUT" ]] || return

    if [[ ${#PUBLISHED_ARNS[@]} -eq 0 ]]; then
        : > "$ARNS_OUTPUT"
        echo "No published ARNs — wrote empty $ARNS_OUTPUT."
        return
    fi

    printf '%s\n' "${PUBLISHED_ARNS[@]}" > "$ARNS_OUTPUT"
    echo "Wrote ${#PUBLISHED_ARNS[@]} region=arn pair(s) to $ARNS_OUTPUT."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

parse_args "$@"


case "${ARCH}" in
    x86_64)
        LAYER_NAME="dynatrace-aws-platform-monitoring-s3-log-forwarder"
        LAYER_DESCRIPTION="Dynatrace AWS S3 Log Forwarder (x86_64)"
        ;;
    arm64)
        LAYER_NAME="dynatrace-aws-platform-monitoring-s3-log-forwarder-arm64"
        LAYER_DESCRIPTION="Dynatrace AWS S3 Log Forwarder (arm64)"
        ;;
    *)
        echo "ERROR: unknown architecture '${ARCH}'. Use 'x86_64' or 'arm64'." >&2
        exit 1
        ;;
esac

if [[ ! -f "$ZIP_FILE" ]]; then
    echo "Error: $ZIP_FILE not found. Run build_docker.sh layer first." >&2
    exit 1
fi

if [[ ${#REGIONS[@]} -eq 0 ]]; then
    echo "Querying available AWS regions..."
    # Joined with a subshell IFS rather than an external tool: BSD paste(1) on
    # macOS requires a file operand and would abort the script under `set -e`.
    exclude_pattern=$(IFS='|'; echo "${EXCLUDED_REGIONS[*]}")
    REGIONS=($(aws ec2 describe-regions --query "Regions[].RegionName" --output text | tr '\t' '\n' | grep -Ev "^(${exclude_pattern})$"))
    echo "Excluded regions: ${EXCLUDED_REGIONS[*]}"
fi

echo "Publishing Lambda Layer: $LAYER_NAME"
echo "ZIP: $ZIP_FILE"
echo "Regions: ${REGIONS[*]}"
echo ""

for REGION in "${REGIONS[@]}"; do
    publish_to_region "$REGION"
    echo ""
done

echo ""
echo "=== Publishing Summary ==="
echo "Attempted: ${#REGIONS[@]}  |  Published: ${#PUBLISHED_ARNS[@]}  |  Failed: ${#FAILED_REGIONS[@]}"

if [[ ${#PERMISSION_FAILED_ARNS[@]} -gt 0 ]]; then
    echo ""
    echo "The following layer versions were published but could NOT be made public."
    echo "They already exist — do NOT re-run the publish for these regions, or they will"
    echo "advance another version. Grant access to the existing version instead:"
    for entry in "${PERMISSION_FAILED_ARNS[@]}"; do
        region="${entry%%=*}"
        arn="${entry#*=}"
        echo "  aws lambda add-layer-version-permission --region ${region} \\"
        echo "      --layer-name ${LAYER_NAME} --version-number ${arn##*:} \\"
        echo "      --statement-id allow-all-accounts --principal '*' --action lambda:GetLayerVersion"
    done
fi

if [[ ${#FAILED_REGIONS[@]} -gt 0 ]]; then
    echo ""
    echo "Failed regions: ${FAILED_REGIONS[*]}"
    echo "template.yaml and ARN output file were NOT updated due to failures in some regions."
    exit 1
fi

if [[ ${#PUBLISHED_ARNS[@]} -gt 0 && "$UPDATE_FILES" == true ]]; then
    update_template
fi

write_arns_output

echo "All regions published successfully."
