#!/bin/bash

# Deploy the dynatrace-aws-platform-monitoring-s3-log-forwarder for e2e validation.
# Usage: ./tests/e2e/deploy_forwarder.sh <layer|zip> [eventbridge|sns|sqs]
# Env: ARCH — target Lambda architecture, x86_64 (default) or arm64

set -e

DEPLOY_TYPE="${1:?Usage: $0 <layer|zip> [eventbridge|sns|sqs]}"
NOTIFICATION_TYPE="${2:-eventbridge}"
ARCH="${ARCH:-x86_64}"

: "${E2E_TESTING_BUCKET_NAME:?E2E_TESTING_BUCKET_NAME must be set}"
: "${STACK_NAME:?STACK_NAME must be set}"
: "${E2E_TEST_PREFIX:?E2E_TEST_PREFIX must be set}"
command -v jq &>/dev/null || { echo "ERROR: jq is required but not installed" >&2; exit 1; }

TIMESTAMP_FORMAT='+%Y-%m-%dT%H:%M:%SZ'
log() {
    echo "[$(date -u "${TIMESTAMP_FORMAT}")] $*"
    return
}

SSM_PARAMETER_NAME="/dynatrace/s3-log-forwarder/${STACK_NAME}/api-key"

log "Storing Dynatrace platform token in SSM Parameter Store"
aws ssm put-parameter \
    --name "${SSM_PARAMETER_NAME}" \
    --type SecureString \
    --value "${DT_TENANT_PLATFORM_TOKEN}" \
    --overwrite

case "${DEPLOY_TYPE}" in
    zip)
        log "dist/ contents: $(ls dist/ 2>/dev/null || echo '(empty or missing)')"
        [[ -f "dist/lambda.zip" ]] || { echo "ERROR: dist/lambda.zip not found" >&2; exit 1; }

        log "Deploying the log forwarder template"
        aws cloudformation deploy --stack-name ${STACK_NAME} --parameter-overrides \
                        DynatraceEnvironmentURL=${DT_TENANT_URL} \
                        DynatraceApiKeySSMParameter="${SSM_PARAMETER_NAME}" \
                        EnableCrossRegionCrossAccountForwarding=true \
                        DeploymentPackageType=zip \
                        Architecture="${ARCH}" \
                        $([ "${NOTIFICATION_TYPE}" = "sns" ] && echo "CreateS3NotificationsSNSTopic=true S3BucketNames=${E2E_TESTING_BUCKET_NAME}") \
                        $([ "${NOTIFICATION_TYPE}" = "sqs" ] && echo "S3BucketNames=${E2E_TESTING_BUCKET_NAME}") \
                        --template-file template.yaml --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
                        --role-arn ${CFN_ROLE_ARN}

        aws cloudformation wait stack-create-complete --stack-name ${STACK_NAME}

        FUNCTION_NAME=$(aws cloudformation describe-stacks --stack-name ${STACK_NAME} \
            --query 'Stacks[0].Outputs[?OutputKey==`QueueProcessingFunction`].OutputValue' \
            --output text | cut -d':' -f7)

        log "Updating Lambda function code for ${FUNCTION_NAME}"
        aws lambda update-function-code --function-name ${FUNCTION_NAME} \
            --zip-file "fileb://dist/lambda.zip"

        log "Waiting for function update to complete"
        aws lambda wait function-updated --function-name ${FUNCTION_NAME}
        ;;

    layer)
        LAYER_STACK_NAME="${STACK_NAME}-layer"

        log "dist/ contents: $(ls dist/ 2>/dev/null || echo '(empty or missing)')"
        [[ -f "dist/layer.zip" ]] || { echo "ERROR: dist/layer.zip not found" >&2; exit 1; }

        log "Packaging the Lambda Layer template"
        aws cloudformation package \
            --template-file dynatrace-aws-s3-log-forwarder-layer.yaml \
            --s3-bucket "${E2E_TESTING_BUCKET_NAME}" \
            --s3-prefix "test/${LAYER_STACK_NAME}" \
            --output-template-file packaged-layer.yaml

        log "Deploying the Lambda Layer template"
        aws cloudformation deploy \
            --template-file packaged-layer.yaml \
            --stack-name "${LAYER_STACK_NAME}" \
            --parameter-overrides \
                LayerName="dynatrace-aws-s3-log-forwarder-e2e-${ARCH}" \
                Architecture="${ARCH}" \
            --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
            --no-fail-on-empty-changeset \
            --role-arn ${CFN_ROLE_ARN}

        LAYER_ARN=$(aws cloudformation describe-stacks \
            --stack-name "${LAYER_STACK_NAME}" \
            --query "Stacks[0].Outputs[?OutputKey=='DynatraceS3LogForwarderLayerVersionArn'].OutputValue" \
            --output text)

        log "Layer ARN: ${LAYER_ARN}"

        log "Deploying the log forwarder template (layer mode)"
        aws cloudformation deploy --stack-name ${STACK_NAME} --parameter-overrides \
                        DynatraceEnvironmentURL=${DT_TENANT_URL} \
                        DynatraceApiKeySSMParameter="${SSM_PARAMETER_NAME}" \
                        EnableCrossRegionCrossAccountForwarding=true \
                        DeploymentPackageType=layer \
                        DynatraceS3LogForwarderLayerArn="${LAYER_ARN}" \
                        Architecture="${ARCH}" \
                        $([ "${NOTIFICATION_TYPE}" = "sns" ] && echo "CreateS3NotificationsSNSTopic=true S3BucketNames=${E2E_TESTING_BUCKET_NAME}") \
                        $([ "${NOTIFICATION_TYPE}" = "sqs" ] && echo "S3BucketNames=${E2E_TESTING_BUCKET_NAME}") \
                        --template-file template.yaml --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
                        --role-arn ${CFN_ROLE_ARN}

        aws cloudformation wait stack-create-complete --stack-name ${STACK_NAME}
        ;;

    *)
        echo "ERROR: unknown deploy type '${DEPLOY_TYPE}'. Use 'layer' or 'zip'." >&2
        exit 1
        ;;
esac

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

        aws cloudformation wait stack-create-complete --stack-name ${STACK_NAME}-s3-bucket-configuration
        ;;

    sns)
        SNS_TOPIC_ARN=$(aws cloudformation describe-stacks --stack-name "${STACK_NAME}" \
            --query 'Stacks[0].Outputs[?OutputKey==`S3NotificationsSNSTopic`].OutputValue' \
            --output text)
        [[ "${SNS_TOPIC_ARN}" =~ ^arn:aws:sns: ]] || { echo "ERROR: could not retrieve a valid SNS topic ARN from stack ${STACK_NAME} (got: '${SNS_TOPIC_ARN}')" >&2; exit 1; }

        NEW_CONFIG=$(jq -n --arg arn "${SNS_TOPIC_ARN}" --arg prefix "${E2E_TEST_PREFIX}/" \
            '{"TopicConfigurations":[{"TopicArn":$arn,"Events":["s3:ObjectCreated:*"],"Filter":{"Key":{"FilterRules":[{"Name":"prefix","Value":$prefix}]}}}]}')
        log "Configuring S3 SNS notification: topic=${SNS_TOPIC_ARN} prefix=${E2E_TEST_PREFIX}/"
        aws s3api put-bucket-notification-configuration \
            --bucket "${E2E_TESTING_BUCKET_NAME}" \
            --notification-configuration "${NEW_CONFIG}"
        ;;

    sqs)
        QUEUE_ARN=$(aws cloudformation describe-stacks --stack-name "${STACK_NAME}" \
            --query 'Stacks[0].Outputs[?OutputKey==`SQSProcessingQueue`].OutputValue' \
            --output text)
        [[ "${QUEUE_ARN}" =~ ^arn:aws:sqs: ]] || { echo "ERROR: could not retrieve a valid SQS queue ARN from stack ${STACK_NAME} (got: '${QUEUE_ARN}')" >&2; exit 1; }

        NEW_CONFIG=$(jq -n --arg arn "${QUEUE_ARN}" --arg prefix "${E2E_TEST_PREFIX}/" \
            '{"QueueConfigurations":[{"QueueArn":$arn,"Events":["s3:ObjectCreated:*"],"Filter":{"Key":{"FilterRules":[{"Name":"prefix","Value":$prefix}]}}}]}')
        log "Configuring S3 SQS notification: queue=${QUEUE_ARN} prefix=${E2E_TEST_PREFIX}/"
        aws s3api put-bucket-notification-configuration \
            --bucket "${E2E_TESTING_BUCKET_NAME}" \
            --notification-configuration "${NEW_CONFIG}"
        ;;

    *)
        echo "ERROR: unknown notification type '${NOTIFICATION_TYPE}'. Use 'eventbridge', 'sns' or 'sqs'." >&2
        exit 1
        ;;
esac

# Wait for notification config to propagate
sleep 15
