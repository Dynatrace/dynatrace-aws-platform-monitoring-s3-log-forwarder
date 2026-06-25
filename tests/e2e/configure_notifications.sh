#!/bin/bash

# Configure all 3 S3 notification types on the test bucket using prefix isolation.
# Each notification type routes only its own prefix to the Lambda:
#
#   <prefix>/eventbridge/  →  EventBridge rule (via bucket-config stack)
#   <prefix>/sns/          →  SNS topic → SQS → Lambda
#   <prefix>/sqs/          →  SQS queue → Lambda (direct)
#
# Usage: ./tests/e2e/configure_notifications.sh <stack_name> <bucket> <prefix> <cfn_role_arn>

set -e

STACK_NAME="${1:?Usage: $0 <stack_name> <bucket> <prefix> <cfn_role_arn>}"
E2E_TESTING_BUCKET_NAME="${2:?Usage: $0 <stack_name> <bucket> <prefix> <cfn_role_arn>}"
E2E_TEST_PREFIX="${3:?Usage: $0 <stack_name> <bucket> <prefix> <cfn_role_arn>}"
CFN_ROLE_ARN="${4:?Usage: $0 <stack_name> <bucket> <prefix> <cfn_role_arn>}"
command -v jq &>/dev/null || { echo "ERROR: jq is required but not installed" >&2; exit 1; }

TIMESTAMP_FORMAT='+%Y-%m-%dT%H:%M:%SZ'
log() {
    echo "[$(date -u "${TIMESTAMP_FORMAT}")] $*"
}

log "Retrieving SNS topic ARN from stack ${STACK_NAME}"
SNS_TOPIC_ARN=$(aws cloudformation describe-stacks --stack-name "${STACK_NAME}" \
    --query 'Stacks[0].Outputs[?OutputKey==`S3NotificationsSNSTopic`].OutputValue' \
    --output text)
[[ "${SNS_TOPIC_ARN}" =~ ^arn:aws:sns: ]] || { echo "ERROR: could not retrieve a valid SNS topic ARN from stack ${STACK_NAME} (got: '${SNS_TOPIC_ARN}')" >&2; exit 1; }

log "Retrieving SQS queue ARN from stack ${STACK_NAME}"
QUEUE_ARN=$(aws cloudformation describe-stacks --stack-name "${STACK_NAME}" \
    --query 'Stacks[0].Outputs[?OutputKey==`SQSProcessingQueue`].OutputValue' \
    --output text)
[[ "${QUEUE_ARN}" =~ ^arn:aws:sqs: ]] || { echo "ERROR: could not retrieve a valid SQS queue ARN from stack ${STACK_NAME} (got: '${QUEUE_ARN}')" >&2; exit 1; }

log "Deploying the S3 bucket configuration template (EventBridge prefix: ${E2E_TEST_PREFIX}/eventbridge/)"
aws cloudformation deploy --stack-name ${STACK_NAME}-s3-bucket-configuration --parameter-overrides \
                DynatraceAwsS3LogForwarderStackName=${STACK_NAME} \
                LogsBucketName=${E2E_TESTING_BUCKET_NAME} \
                LogsBucketPrefix1=${E2E_TEST_PREFIX}/eventbridge/ \
                --capabilities CAPABILITY_IAM \
                --template-file dynatrace-aws-s3-log-forwarder-s3-bucket-configuration.yaml \
                --role-arn ${CFN_ROLE_ARN}

log "Configuring all 3 S3 notification types on bucket ${E2E_TESTING_BUCKET_NAME}"
NOTIFICATION_CONFIG=$(jq -n \
    --arg sns_arn "${SNS_TOPIC_ARN}" \
    --arg sqs_arn "${QUEUE_ARN}" \
    --arg sns_prefix "${E2E_TEST_PREFIX}/sns/" \
    --arg sqs_prefix "${E2E_TEST_PREFIX}/sqs/" \
    '{
        "EventBridgeConfiguration": {},
        "TopicConfigurations": [{
            "TopicArn": $sns_arn,
            "Events": ["s3:ObjectCreated:*"],
            "Filter": {"Key": {"FilterRules": [{"Name": "prefix", "Value": $sns_prefix}]}}
        }],
        "QueueConfigurations": [{
            "QueueArn": $sqs_arn,
            "Events": ["s3:ObjectCreated:*"],
            "Filter": {"Key": {"FilterRules": [{"Name": "prefix", "Value": $sqs_prefix}]}}
        }]
    }')
aws s3api put-bucket-notification-configuration \
    --bucket "${E2E_TESTING_BUCKET_NAME}" \
    --notification-configuration "${NOTIFICATION_CONFIG}"

# Wait for notification config to propagate
sleep 15
