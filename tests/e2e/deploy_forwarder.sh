#!/bin/bash

# Deploy the dynatrace-aws-platform-monitoring-s3-log-forwarder for e2e validation.
# Usage: ./tests/e2e/deploy_forwarder.sh <layer|zip> [x86_64|arm64] [--upgrade]
#
# The build artifact must exist before running this script:
#   dist/lambda.zip  for zip deployments  — build with: ./scripts/build_docker.sh zip dist/lambda.zip [arch]
#   dist/layer.zip   for layer deployments — build with: ./scripts/build_docker.sh layer dist/layer.zip [arch]
#
# With --upgrade, the script targets a pre-existing stack: it tolerates an empty changeset and skips
# the stack-create-complete waiter, which would fail on an update. Parameters that are not overridden
# here keep the values already set on the stack.
#
# S3 notification configuration is handled separately by configure_notifications.sh.

set -e

DEPLOY_TYPE="${1:?Usage: $0 <layer|zip> [x86_64|arm64] [--upgrade]}"
shift

ARCH=x86_64
if [[ $# -gt 0 && "$1" != --* ]]; then
    ARCH="$1"
    shift
fi

UPGRADE=false
for arg in "$@"; do
    case "${arg}" in
        --upgrade) UPGRADE=true ;;
        *) echo "ERROR: unknown argument '${arg}'. Usage: $0 <layer|zip> [x86_64|arm64] [--upgrade]" >&2; exit 1 ;;
    esac
done

: "${E2E_TESTING_BUCKET_NAME:?E2E_TESTING_BUCKET_NAME must be set}"
: "${STACK_NAME:?STACK_NAME must be set}"

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
        : "${E2E_TEST_PREFIX:?E2E_TEST_PREFIX must be set}"

        log "dist/ contents: $(ls dist/ 2>/dev/null || echo '(empty or missing)')"
        [[ -f "dist/lambda.zip" ]] || { echo "ERROR: dist/lambda.zip not found" >&2; exit 1; }

        LAMBDA_ZIP_S3_KEY="${E2E_TEST_PREFIX}/lambda.zip"
        log "Uploading lambda.zip to s3://${E2E_TESTING_BUCKET_NAME}/${LAMBDA_ZIP_S3_KEY}"
        aws s3 cp dist/lambda.zip "s3://${E2E_TESTING_BUCKET_NAME}/${LAMBDA_ZIP_S3_KEY}"

        EXTRA_CFN_PARAMS+=(
            DeploymentPackageType=zip
            LambdaCodeS3Bucket="${E2E_TESTING_BUCKET_NAME}"
            LambdaCodeS3Key="${LAMBDA_ZIP_S3_KEY}"
        )
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

        EXTRA_CFN_PARAMS+=(
            DeploymentPackageType=layer
            DynatraceS3LogForwarderLayerArn="${LAYER_ARN}"
        )
        ;;

    *)
        echo "ERROR: unknown deploy type '${DEPLOY_TYPE}'. Use 'layer' or 'zip'." >&2
        exit 1
        ;;
esac

FORWARDER_DEPLOY_FLAGS=()
ACTION="Deploying"
if [[ "${UPGRADE}" == "true" ]]; then
    if ! aws cloudformation describe-stacks --stack-name "${STACK_NAME}" >/dev/null 2>&1; then
        echo "ERROR: stack '${STACK_NAME}' does not exist; cannot validate an upgrade" >&2
        exit 1
    fi
    # An upgrade may produce no changes at all, and the stack already exists.
    FORWARDER_DEPLOY_FLAGS+=(--no-fail-on-empty-changeset)
    ACTION="Upgrading"
fi

log "${ACTION} the log forwarder stack (${DEPLOY_TYPE} mode)"
aws cloudformation deploy --stack-name ${STACK_NAME} --parameter-overrides \
                DynatraceEnvironmentURL=${DT_TENANT_PLATFORM_URL} \
                EnableCrossRegionCrossAccountForwarding=true \
                Architecture="${ARCH}" \
                "${EXTRA_CFN_PARAMS[@]}" \
                --template-file deploy-template.yaml --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
                "${FORWARDER_DEPLOY_FLAGS[@]}" \
                --role-arn ${CFN_ROLE_ARN}

[[ "${UPGRADE}" == "true" ]] || aws cloudformation wait stack-create-complete --stack-name ${STACK_NAME}
