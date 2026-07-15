#!/bin/bash

# Remove S3 notification configuration for a single notification type.
# For eventbridge, also deletes the bucket-configuration CloudFormation stack.
#
# Usage: ./tests/e2e/clean_up_notifications.sh <eventbridge|sns-sqs> <stack_name> <bucket>

set -e

NOTIFICATION_TYPE="${1:?Usage: $0 <eventbridge|sns-sqs> <stack_name> <bucket>}"
STACK_NAME="${2:?Usage: $0 <eventbridge|sns-sqs> <stack_name> <bucket>}"
E2E_TESTING_BUCKET_NAME="${3:?Usage: $0 <eventbridge|sns-sqs> <stack_name> <bucket>}"

TIMESTAMP_FORMAT='+%Y-%m-%dT%H:%M:%SZ'
log() {
    echo "[$(date -u "${TIMESTAMP_FORMAT}")] $*"
}

if [ "${NOTIFICATION_TYPE}" = "eventbridge" ]; then
    log "Deleting CloudFormation stack ${STACK_NAME}-s3-bucket-configuration"
    aws cloudformation delete-stack --stack-name ${STACK_NAME}-s3-bucket-configuration || true
    aws cloudformation wait stack-delete-complete --stack-name ${STACK_NAME}-s3-bucket-configuration || true
fi
