#!/bin/bash
# Usage: ./scripts/rewrite_nested_template_url.sh <s3_url> [output_file]
# Replaces the local TemplateURL for cloudwatch-monitoring-dashboard.yaml in template.yaml
# with the given S3 URL. Writes to output_file if provided, otherwise modifies template.yaml in place.

set -e

S3_URL="${1:?Usage: $0 <s3_url> [output_file]}"
OUTPUT_FILE="${2:-}"

grep -qF 'TemplateURL: ./cloudwatch-monitoring-dashboard.yaml' template.yaml \
    || { echo "ERROR: expected local TemplateURL not found in template.yaml" >&2; exit 1; }

if [[ -n "${OUTPUT_FILE}" ]]; then
    sed "s|TemplateURL: \./cloudwatch-monitoring-dashboard\.yaml|TemplateURL: ${S3_URL}|" \
        template.yaml > "${OUTPUT_FILE}"
else
    sed -i "s|TemplateURL: \./cloudwatch-monitoring-dashboard\.yaml|TemplateURL: ${S3_URL}|" \
        template.yaml
fi
