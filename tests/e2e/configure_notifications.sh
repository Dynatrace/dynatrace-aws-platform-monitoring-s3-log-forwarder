#!/bin/bash

# Configure S3 notifications for a single notification type.
#
# Usage: ./tests/e2e/configure_notifications.sh <eventbridge|sns|sqs> <stack_name> <bucket> <prefix> <cfn_role_arn>

set -e

NOTIFICATION_TYPE="${1:?Usage: $0 <eventbridge|sns-sqs> <stack_name> <bucket> <prefix> <cfn_role_arn>}"
STACK_NAME="${2:?Usage: $0 <eventbridge|sns-sqs> <stack_name> <bucket> <prefix> <cfn_role_arn>}"
E2E_TESTING_BUCKET_NAME="${3:?Usage: $0 <eventbridge|sns-sqs> <stack_name> <bucket> <prefix> <cfn_role_arn>}"
E2E_TEST_PREFIX="${4:?Usage: $0 <eventbridge|sns-sqs> <stack_name> <bucket> <prefix> <cfn_role_arn>}"
CFN_ROLE_ARN="${5:?Usage: $0 <eventbridge|sns-sqs> <stack_name> <bucket> <prefix> <cfn_role_arn>}"
command -v jq &>/dev/null || { echo "ERROR: jq is required but not installed" >&2; exit 1; }

TIMESTAMP_FORMAT='+%Y-%m-%dT%H:%M:%SZ'
log() {
    echo "[$(date -u "${TIMESTAMP_FORMAT}")] $*"
}

case "${NOTIFICATION_TYPE}" in
    eventbridge)
        log "Enabling EventBridge notifications on bucket ${E2E_TESTING_BUCKET_NAME}"
        aws s3api put-bucket-notification-configuration \
            --bucket "${E2E_TESTING_BUCKET_NAME}" \
            --notification-configuration '{"EventBridgeConfiguration":{}}'

        log "Deploying the S3 bucket configuration template"
        aws cloudformation deploy --stack-name ${STACK_NAME}-s3-bucket-configuration --parameter-overrides \
                        DynatraceAwsS3LogForwarderStackName=${STACK_NAME} \
                        LogsBucketName=${E2E_TESTING_BUCKET_NAME} \
                        LogsBucketPrefix1=${E2E_TEST_PREFIX}/ \
                        --capabilities CAPABILITY_IAM \
                        --template-file dynatrace-aws-s3-log-forwarder-s3-bucket-configuration.yaml \
                        --role-arn ${CFN_ROLE_ARN}
        ;;

    sns-sqs)
        SNS_TOPIC_ARN=$(aws cloudformation describe-stacks --stack-name "${STACK_NAME}" \
            --query 'Stacks[0].Outputs[?OutputKey==`S3NotificationsSNSTopic`].OutputValue' \
            --output text)
        [[ "${SNS_TOPIC_ARN}" =~ ^arn:aws:sns: ]] || { echo "ERROR: could not retrieve a valid SNS topic ARN from stack ${STACK_NAME} (got: '${SNS_TOPIC_ARN}')" >&2; exit 1; }

        QUEUE_ARN=$(aws cloudformation describe-stacks --stack-name "${STACK_NAME}" \
            --query 'Stacks[0].Outputs[?OutputKey==`SQSProcessingQueue`].OutputValue' \
            --output text)
        [[ "${QUEUE_ARN}" =~ ^arn:aws:sqs: ]] || { echo "ERROR: could not retrieve a valid SQS queue ARN from stack ${STACK_NAME} (got: '${QUEUE_ARN}')" >&2; exit 1; }

        NEW_CONFIG=$(jq -n \
            --arg sns_arn "${SNS_TOPIC_ARN}" --arg sns_prefix "${E2E_TEST_PREFIX}/sns/" \
            --arg sqs_arn "${QUEUE_ARN}"     --arg sqs_prefix "${E2E_TEST_PREFIX}/sqs/" \
            '{"TopicConfigurations":[{"TopicArn":$sns_arn,"Events":["s3:ObjectCreated:*"],"Filter":{"Key":{"FilterRules":[{"Name":"prefix","Value":$sns_prefix}]}}}],
              "QueueConfigurations":[{"QueueArn":$sqs_arn,"Events":["s3:ObjectCreated:*"],"Filter":{"Key":{"FilterRules":[{"Name":"prefix","Value":$sqs_prefix}]}}}]}')
        log "Configuring S3 SNS+SQS notifications: sns=${E2E_TEST_PREFIX}/sns/ sqs=${E2E_TEST_PREFIX}/sqs/"
        aws s3api put-bucket-notification-configuration \
            --bucket "${E2E_TESTING_BUCKET_NAME}" \
            --notification-configuration "${NEW_CONFIG}"
        ;;

    *)
        echo "ERROR: unknown notification type '${NOTIFICATION_TYPE}'. Use 'eventbridge' or 'sns-sqs'." >&2
        exit 1
        ;;
esac

# Wait for notification config to propagate
sleep 15
