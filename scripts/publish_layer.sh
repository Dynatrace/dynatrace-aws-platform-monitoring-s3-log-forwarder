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

# Publish the Lambda Layer (x86_64) to one or more AWS regions with public access.
# Assumes the layer has already been built with build_docker.sh layer.
#
# Usage:
#   ./scripts/publish_layer.sh <zip>                                              # All commercial regions
#   ./scripts/publish_layer.sh <zip> --regions us-east-1,eu-west-1,eu-central-1  # Specific regions
#   ./scripts/publish_layer.sh <zip> --no-update-files                            # Skip README/template.yaml updates

set -e

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
LAYER_NAME="dynatrace-aws-platform-monitoring-s3-log-forwarder"
ZIP_FILE="${1:?Usage: $0 <zip> [--regions r1,r2,...]}"
REGIONS=()
FAILED_REGIONS=()
PUBLISHED_ARNS=()  # Entries in the form "region=arn"
UPDATE_FILES=true

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

parse_args() {
    local idx=2
    while [[ $idx -le $# ]]; do
        case "${!idx}" in
            --regions)
                idx=$((idx + 1))
                IFS=',' read -ra REGIONS <<< "${!idx:?--regions requires a value}"
                ;;
            --no-update-files)
                UPDATE_FILES=false
                ;;
            *)
                echo "Unknown option: ${!idx}"
                echo "Usage: $0 <zip> [--regions r1,r2,...]"
                exit 1
                ;;
        esac
        idx=$((idx + 1))
    done
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Look up the ARN for a given region from PUBLISHED_ARNS.
# Returns empty string (exit 0) if not found — safe to use with set -e.
lookup_arn() {
    local region="$1"
    local entry
    for entry in "${PUBLISHED_ARNS[@]}"; do
        if [[ "${entry%%=*}" == "$region" ]]; then
            echo "${entry#*=}"
            return 0
        fi
    done
}

# Check whether a region appears in a newline-separated string.
is_seen() {
    local region="$1" seen_list="$2"
    echo "$seen_list" | grep -qxF "$region"
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
        --compatible-architectures x86_64 \
        --description "Dynatrace AWS S3 Log Forwarder (x86_64)" \
        --query 'LayerVersionArn' \
        --output text 2>&1) || {
        echo "  FAILED to publish in $region"
        FAILED_REGIONS+=("$region")
        return
    }

    local layer_version
    layer_version=$(echo "$layer_version_arn" | grep -o '[0-9]*$')
    echo "  Published: $layer_version_arn"

    aws lambda add-layer-version-permission \
        --region "$region" \
        --layer-name "$LAYER_NAME" \
        --version-number "$layer_version" \
        --statement-id allow-all-accounts \
        --principal "*" \
        --action lambda:GetLayerVersion \
        --output json > /dev/null 2>&1 || {
        echo "  FAILED to grant public access in $region"
        FAILED_REGIONS+=("$region")
        return
    }

    echo "  Public access granted."
    PUBLISHED_ARNS+=("$region=$layer_version_arn")
}

# ---------------------------------------------------------------------------
# Update README.md — upsert rows in the "Lambda Layer ARNs" table
# ---------------------------------------------------------------------------

update_readme() {
    local readme_file="$REPO_ROOT/README.md"
    [[ -f "$readme_file" ]] || return

    echo "Updating Lambda Layer ARNs table in $readme_file..."

    local in_table=0 sep_found=0 seen="" output="" line stripped row_region row_arn entry r a

    while IFS= read -r line || [[ -n "$line" ]]; do
        stripped="${line#"${line%%[![:space:]]*}"}"
        stripped="${stripped%"${stripped##*[![:space:]]}"}"

        # Detect table header
        if [[ $in_table -eq 0 && "$stripped" == "| Region | Layer ARN |" ]]; then
            in_table=1
            output+="$line"$'\n'
            continue
        fi

        # Detect separator row
        if [[ $in_table -eq 1 && $sep_found -eq 0 && "$stripped" == \|---* ]]; then
            sep_found=1
            output+="$line"$'\n'
            continue
        fi

        if [[ $in_table -eq 1 && $sep_found -eq 1 ]]; then
            if [[ "$stripped" == \|*\| ]]; then
                # Existing row — replace ARN if this region was published
                row_region=$(echo "$stripped" | awk -F'|' '{gsub(/ /,"",$2); print $2}')
                row_arn=$(lookup_arn "$row_region")
                if [[ -n "$row_arn" ]]; then
                    output+="| $row_region | $row_arn |"$'\n'
                    seen+="$row_region"$'\n'
                else
                    output+="$line"$'\n'
                fi
                continue
            else
                # End of table — append any newly published regions not already present
                for entry in "${PUBLISHED_ARNS[@]}"; do
                    r="${entry%%=*}"; a="${entry#*=}"
                    if ! is_seen "$r" "$seen"; then
                        output+="| $r | $a |"$'\n'
                        seen+="$r"$'\n'
                    fi
                done
                in_table=0
            fi
        fi

        output+="$line"$'\n'
    done < "$readme_file"

    # Handle table at end of file
    if [[ $in_table -eq 1 ]]; then
        for entry in "${PUBLISHED_ARNS[@]}"; do
            r="${entry%%=*}"; a="${entry#*=}"
            is_seen "$r" "$seen" || output+="| $r | $a |"$'\n'
        done
    fi

    # Preserve original trailing-newline behaviour.
    # Note: $(...) strips trailing newlines, so check the last byte via od instead.
    if [[ "$(tail -c1 "$readme_file" | od -An -tx1 | tr -d ' \n')" == "0a" ]]; then
        printf '%s' "$output" > "$readme_file"
    else
        printf '%s' "${output%$'\n'}" > "$readme_file"
    fi
    echo "README.md updated."
}

# ---------------------------------------------------------------------------
# Update template.yaml — replace Arn values in the LayerArns mapping
# ---------------------------------------------------------------------------

update_template() {
    local template_file="$REPO_ROOT/template.yaml"
    [[ -f "$template_file" ]] || return

    echo "Updating LayerArns mappings in $template_file..."

    local in_layer_arns=0 current_region="" output="" line stripped new_arn indent

    while IFS= read -r line || [[ -n "$line" ]]; do
        stripped="${line#"${line%%[![:space:]]*}"}"
        stripped="${stripped%"${stripped##*[![:space:]]}"}"

        # Detect start of LayerArns block
        if [[ "$stripped" == "LayerArns:" ]]; then
            in_layer_arns=1
            output+="$line"$'\n'
            continue
        fi

        # Detect end of LayerArns block (next top-level key)
        if [[ $in_layer_arns -eq 1 && "$line" =~ ^[A-Za-z] ]]; then
            in_layer_arns=0
            current_region=""
        fi

        if [[ $in_layer_arns -eq 1 ]]; then
            # Region key (4-space indent)
            if [[ "$line" =~ ^[[:space:]]{4}([a-z0-9-]+):$ ]]; then
                current_region="${BASH_REMATCH[1]}"
                output+="$line"$'\n'
                continue
            fi

            # Arn value (6-space indent) — replace if this region was published
            if [[ -n "$current_region" && "$line" =~ ^[[:space:]]{6}Arn: ]]; then
                new_arn=$(lookup_arn "$current_region")
                if [[ -n "$new_arn" ]]; then
                    indent="${line%%Arn:*}"
                    output+="${indent}Arn: $new_arn"$'\n'
                    continue
                fi
            fi
        fi

        output+="$line"$'\n'
    done < "$template_file"

    # Preserve original trailing-newline behaviour.
    # Note: $(...) strips trailing newlines, so check the last byte via od instead.
    if [[ "$(tail -c1 "$template_file" | od -An -tx1 | tr -d ' \n')" == "0a" ]]; then
        printf '%s' "$output" > "$template_file"
    else
        printf '%s' "${output%$'\n'}" > "$template_file"
    fi
    echo "template.yaml updated."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

parse_args "$@"

if [[ ! -f "$ZIP_FILE" ]]; then
    echo "Error: $ZIP_FILE not found. Run build_docker.sh layer first." >&2
    exit 1
fi

if [[ ${#REGIONS[@]} -eq 0 ]]; then
    echo "Querying available AWS regions..."
    # me-* regions (Middle East) are excluded — currently defunct and publishing fails there
    REGIONS=($(aws ec2 describe-regions --query "Regions[].RegionName" --output text | tr '\t' '\n' | grep -v '^me-'))
fi

echo "Publishing Lambda Layer: $LAYER_NAME"
echo "ZIP: $ZIP_FILE"
echo "Regions: ${REGIONS[*]}"
echo ""

for REGION in "${REGIONS[@]}"; do
    publish_to_region "$REGION"
    echo ""
done

if [[ ${#PUBLISHED_ARNS[@]} -gt 0 && "$UPDATE_FILES" == true ]]; then
    update_readme
    update_template
fi

echo ""
echo "=== Publishing Summary ==="
echo "Attempted: ${#REGIONS[@]}  |  Published: ${#PUBLISHED_ARNS[@]}  |  Failed: ${#FAILED_REGIONS[@]}"

if [[ ${#FAILED_REGIONS[@]} -gt 0 ]]; then
    echo "Failed regions: ${FAILED_REGIONS[*]}"
    exit 1
fi

echo "All regions published successfully."
