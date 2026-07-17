# Build

If you're contributing to the project or if you want to build and deploy from source, the following sections cover how to build and deploy the `dynatrace-aws-platform-monitoring-s3-log-forwarder`.

There are two build options:

* **Lambda Layer**
* **Lambda ZIP**

Both options are built inside a Docker container for binary compatibility. See `scripts/build_docker.sh`.

> [!NOTE]
>
> The build runs inside a Docker container. Make sure Docker is running before executing the build script.

## Prerequisites

The deployment instructions are written for Linux/MacOS. If you are running on Windows, use the Linux Subsystem for Windows or use an [AWS Cloud9](https://aws.amazon.com/cloud9/) instance.

You'll need the following software installed:

* [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
* [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
* Git
* Docker Engine

You'll also need:

* A Dynatrace [platform token](https://docs.dynatrace.com/docs/manage/identity-access-management/access-tokens-and-oauth-clients/platform-tokens) for your tenant with the `data-acquisition:logs:ingest` scope (used to authenticate against the generic S3 logs ingest API).

## Setup

Before deploying either option, complete the following steps.

1. Clone the `dynatrace-aws-platform-monitoring-s3-log-forwarder` repository and checkout the latest version tag:

    ```bash
    export VERSION_TAG=$(curl -s https://api.github.com/repos/dynatrace/dynatrace-aws-platform-monitoring-s3-log-forwarder/releases/latest | grep tag_name | cut -d'"' -f4)
    git clone https://github.com/dynatrace/dynatrace-aws-platform-monitoring-s3-log-forwarder.git
    cd dynatrace-aws-platform-monitoring-s3-log-forwarder
    git checkout $VERSION_TAG
    ```

1. Define a name for your `dynatrace-aws-platform-monitoring-s3-log-forwarder` deployment (e.g. mycompany-dynatrace-s3-log-forwarder) and your Dynatrace tenant UUID (e.g. `abc12345` if your Dynatrace environment url is `https://abc12345.apps.dynatrace.com`) in environment variables that will be used along the deployment process.

    ```bash
    export STACK_NAME=replace_with_your_log_forwarder_stack_name
    export DYNATRACE_TENANT_UUID=replace_with_your_dynatrace_tenant_uuid
    ```

    > [!IMPORTANT]
    >
    > Your stack name should have a maximum of 47 characters, otherwise deployment will fail.

1. Provide the Dynatrace platform token.

    The Lambda function needs a Dynatrace platform token (scope `data-acquisition:logs:ingest`) to authenticate against the log ingest API. There are three mutually exclusive options — choose one:

    **Option A: Existing AWS Secrets Manager secret (recommended)**

    If you already have a Secrets Manager secret storing the token, reference it directly. The secret value must be the plain token string.

    ```bash
    export DT_TOKEN_SECRET_ARN=<arn-of-your-existing-secrets-manager-secret>
    ```

    **Option B: AWS Systems Manager Parameter Store**

    Store the token as a SecureString parameter:

    ```bash
    export HISTCONTROL=ignorespace
     aws ssm put-parameter \
         --name "/dynatrace/s3-log-forwarder/$STACK_NAME/api-key" \
         --type SecureString \
         --value "<your_dynatrace_platform_token_here>"
    ```

    Pass `DynatraceApiKeySSMParameter="/dynatrace/s3-log-forwarder/$STACK_NAME/api-key"` in the deploy command later.

    **Option C: Plain text token (stack creates a Secrets Manager secret)**

    Pass the token directly in the deploy command — the stack creates a new Secrets Manager secret to store it securely.

    Pass `DynatraceApiKey="<your_dynatrace_platform_token_here>"` in the deploy command later.

## Building and deploying a Lambda Layer from source

If you want to build the Lambda Layer from source instead of using a pre-published Layer ARN, follow the steps below.

### Lambda Layer build details

From the project root directory:

```bash
./scripts/build_docker.sh layer dist/layer.zip          # x86_64 (default)
./scripts/build_docker.sh layer dist/layer.zip arm64    # arm64
```

This will:

* Install pip dependencies for the target platform into `build/layer/python/`
* Copy the application source code and license files
* Bundle the `libyajl.so.2` native library (required by the `ijson` `yajl2_c` backend for high-performance JSON streaming)
* Produce a layer ZIP at the specified output path

### Lambda Layer deployment instructions

1. Deploy the layer template as its own CloudFormation stack. SAM will automatically create and manage an S3 bucket for the artifact upload.

    ```bash
    # Note: template assumes that the layer.zip is available in `dist/layer.zip`
    sam deploy \
        --template-file dynatrace-aws-s3-log-forwarder-layer.yaml \
        --stack-name "${STACK_NAME}-layer" \
        --resolve-s3 \
        --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
        --parameter-overrides Architecture=x86_64  # or arm64
    ```

1. Retrieve the deployed Layer ARN:

    ```bash
    export LAYER_ARN=$(aws cloudformation describe-stacks \
        --stack-name "${STACK_NAME}-layer" \
        --query "Stacks[0].Outputs[?OutputKey=='DynatraceS3LogForwarderLayerVersionArn'].OutputValue" \
        --output text)

    echo "Layer ARN: $LAYER_ARN"
    ```

1. Deploy the main forwarder stack.

    Continue with the standard deployment from [the deployment guide](deployment_guide.md#step-4-deploy-the-lambda-function), passing `DynatraceS3LogForwarderLayerArn="$LAYER_ARN"` in `--parameter-overrides` to use the layer you just built.

### Updating the layer after code changes

After making source code changes, repeat steps 1-3 above to rebuild and redeploy the layer, then update the main stack with the new Layer ARN.

## Building and deploying a Lambda ZIP from source

### Lambda ZIP build details

From the project root directory:

```bash
./scripts/build_docker.sh zip dist/lambda.zip           # x86_64 (default)
./scripts/build_docker.sh zip dist/lambda.zip arm64     # arm64
```

This will:

* Install Python dependencies from `requirements.txt`
* Copy application source code, configuration files, and license files
* Bundle the `libyajl.so.2` native library (required by the `ijson` `yajl2_c` backend for high-performance JSON streaming)
* Produce a ready-to-deploy Lambda ZIP at `dist/lambda.zip`

> [!NOTE]
>
> At runtime, the `LD_LIBRARY_PATH` environment variable must be set to `/var/task/lib` so the yajl library is found.

### Lambda ZIP deployment instructions

1. From the project root directory, build the Lambda deployment package:

    ```bash
    ./scripts/build_docker.sh zip dist/lambda.zip
    ```

1. Upload the nested dashboard template and rewrite its `TemplateURL` in `template.yaml`. `template.yaml` references `cloudwatch-monitoring-dashboard.yaml` via a local path, which CloudFormation can't resolve — it needs an absolute S3 URL:

    ```bash
    export CFN_ARTIFACTS_BUCKET=<your-s3-bucket-for-cfn-artifacts>

    aws s3 cp cloudwatch-monitoring-dashboard.yaml \
        "s3://${CFN_ARTIFACTS_BUCKET}/${STACK_NAME}/cloudwatch-monitoring-dashboard.yaml"

    NESTED_DASHBOARD_URL="https://${CFN_ARTIFACTS_BUCKET}.s3.amazonaws.com/${STACK_NAME}/cloudwatch-monitoring-dashboard.yaml"
    ./scripts/rewrite_nested_template_url.sh "${NESTED_DASHBOARD_URL}" deploy-template.yaml
    ```

1. Follow the [ZIP deployment instructions in the deployment guide](deployment_guide.md#zip-deployment-alternative-option), using `deploy-template.yaml` (generated above) instead of `template.yaml`, and `dist/lambda.zip` as the deployment package.
