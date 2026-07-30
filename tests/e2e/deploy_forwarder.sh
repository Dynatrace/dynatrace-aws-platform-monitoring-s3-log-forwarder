#!/bin/bash

# Deploy the dynatrace-aws-platform-monitoring-s3-log-forwarder for e2e validation.
# Usage: ./tests/e2e/deploy_forwarder.sh <layer|zip> [x86_64|arm64]
#
# The build artifact must exist before running this script:
#   dist/lambda.zip  for zip deployments  — build with: ./scripts/build_docker.sh zip dist/lambda.zip [arch]
#   dist/layer.zip   for layer deployments — build with: ./scripts/build_docker.sh layer dist/layer.zip [arch]
#
# S3 notification configuration is handled separately by configure_notifications.sh.

set -e

DEPLOY_TYPE="${1:?Usage: $0 <layer|zip> [x86_64|arm64]}"
ARCH="${2:-x86_64}"

: "${E2E_TESTING_BUCKET_NAME:?E2E_TESTING_BUCKET_NAME must be set}"
: "${STACK_NAME:?STACK_NAME must be set}"
command -v jq &>/dev/null || { echo "ERROR: jq is required but not installed" >&2; exit 1; }

TIMESTAMP_FORMAT='+%Y-%m-%dT%H:%M:%SZ'
log() {
    echo "[$(date -u "${TIMESTAMP_FORMAT}")] $*"
    return
}

SSM_PARAMETER_NAME="/dynatrace/s3-log-forwarder/${STACK_NAME}/api-key"

EXTRA_CFN_PARAMS=()
[[ -n "${KMS_KEY_ARNS:-}" ]]    && EXTRA_CFN_PARAMS+=(GrantDecryptToKmsKeyArns="${KMS_KEY_ARNS}")
[[ -n "${IAM_ROLE_PATH:-}" ]]   && EXTRA_CFN_PARAMS+=(IamRolePath="${IAM_ROLE_PATH}")
[[ -n "${S3_BUCKET_NAMES:-}" ]] && EXTRA_CFN_PARAMS+=(GrantReadPermissionToBuckets="${S3_BUCKET_NAMES}")

if [[ -n "${DT_TOKEN_SECRET_ARN:-}" && -n "${DT_TENANT_PLATFORM_TOKEN:-}" ]]; then
    echo "ERROR: DT_TOKEN_SECRET_ARN and DT_TENANT_PLATFORM_TOKEN are mutually exclusive — set exactly one" >&2; exit 1
elif [[ -n "${DT_TOKEN_SECRET_ARN:-}" ]]; then
    log "Using existing Secrets Manager secret for Dynatrace platform token"
    EXTRA_CFN_PARAMS+=(DynatraceApiKeySecretsManagerSecret="${DT_TOKEN_SECRET_ARN}")
elif [[ -n "${DT_TENANT_PLATFORM_TOKEN:-}" ]]; then
    log "Storing Dynatrace platform token in SSM Parameter Store"
    aws ssm put-parameter \
        --name "${SSM_PARAMETER_NAME}" \
        --type SecureString \
        --value "${DT_TENANT_PLATFORM_TOKEN}" \
        --overwrite
    EXTRA_CFN_PARAMS+=(DynatraceApiKeySSMParameter="${SSM_PARAMETER_NAME}")
else
    echo "ERROR: either DT_TOKEN_SECRET_ARN or DT_TENANT_PLATFORM_TOKEN must be set" >&2; exit 1
fi

log "Uploading nested monitoring dashboard template and rewriting TemplateURL"
aws s3 cp cloudwatch-monitoring-dashboard.yaml \
    "s3://${E2E_TESTING_BUCKET_NAME}/test/${STACK_NAME}/cloudwatch-monitoring-dashboard.yaml"
NESTED_DASHBOARD_URL="https://${E2E_TESTING_BUCKET_NAME}.s3.amazonaws.com/test/${STACK_NAME}/cloudwatch-monitoring-dashboard.yaml"
./scripts/rewrite_nested_template_url.sh "${NESTED_DASHBOARD_URL}" deploy-template.yaml

case "${DEPLOY_TYPE}" in
    zip)
        log "dist/ contents: $(ls dist/ 2>/dev/null || echo '(empty or missing)')"
        [[ -f "dist/lambda.zip" ]] || { echo "ERROR: dist/lambda.zip not found" >&2; exit 1; }

        log "Deploying the log forwarder template"
        aws cloudformation deploy --stack-name ${STACK_NAME} --parameter-overrides \
                        DynatraceEnvironmentURL=${DT_TENANT_PLATFORM_URL} \
                        EnableCrossRegionCrossAccountForwarding=true \
                        DeploymentPackageType=zip \
                        Architecture="${ARCH}" \
                        "${EXTRA_CFN_PARAMS[@]}" \
                        --template-file deploy-template.yaml --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
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
                        DynatraceEnvironmentURL=${DT_TENANT_PLATFORM_URL} \
                        EnableCrossRegionCrossAccountForwarding=true \
                        DeploymentPackageType=layer \
                        DynatraceS3LogForwarderLayerArn="${LAYER_ARN}" \
                        Architecture="${ARCH}" \
                        "${EXTRA_CFN_PARAMS[@]}" \
                        --template-file deploy-template.yaml --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
                        --role-arn ${CFN_ROLE_ARN}

        aws cloudformation wait stack-create-complete --stack-name ${STACK_NAME}
        ;;

    *)
        echo "ERROR: unknown deploy type '${DEPLOY_TYPE}'. Use 'layer' or 'zip'." >&2
        exit 1
        ;;
esac
