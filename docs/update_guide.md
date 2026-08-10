# Update instructions

## Prerequisites

The update instructions are written for Linux/MacOS. If you are running on Windows, use the Linux Subsystem for Windows, AWS CloudShell or an [AWS Cloud9](https://aws.amazon.com/cloud9/) instance.

You'll need the following software installed (already available in AWS CloudShell and AWS Cloud9):

* [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)

## Update the dynatrace-aws-platform-monitoring-s3-log-forwarder

### Step 1. Review the GitHub release notes

Review the GitHub release notes for any additional required steps specific to the version you are updating to.

### Step 2. Find your deployment stack name

Find a name for your `dynatrace-aws-platform-monitoring-s3-log-forwarder` deployment and store in the `STACK_NAME` environment variable. The deployment contains several CloudFormation stacks.

```bash
export STACK_NAME=<replace-with-your-log-forwarder-stack-name>
```

### Step 3. Set the version to update to

Set the `VERSION_TAG` environment variable to the latest release version tag of `dynatrace-aws-platform-monitoring-s3-log-forwarder`.

```bash
# Get the latest version
export VERSION_TAG=$(curl -s https://api.github.com/repos/dynatrace/dynatrace-aws-platform-monitoring-s3-log-forwarder/releases/latest | grep tag_name | cut -d'"' -f4)
```

> [!Note]
>
> If you want to update to specific version, set the `VERSION_TAG` variable to that version (e.g. `v1.2.3`).
>
> ```bash
> export VERSION_TAG=v1.2.3
> ```

### Step 4. Download the latest templates

Download the CloudFormation templates for the version you're updating to:

```bash
mkdir -p dynatrace-aws-s3-log-forwarder-templates && cd "$_"
wget https://github.com/dynatrace/dynatrace-aws-platform-monitoring-s3-log-forwarder/releases/download/${VERSION_TAG}/templates.zip
unzip -o templates.zip
```

### Step 5. Update the stack

#### Lambda Layer

Redeploy with the new `template.yaml` — the latest layer ARN for your region and architecture is embedded in the template's mappings.

```bash
aws cloudformation deploy --stack-name ${STACK_NAME} \
            --template-file template.yaml \
            --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
            --parameter-overrides \
                DeploymentPackageType="layer"
```

#### Lambda ZIP

Download the new ZIP for your architecture from the GitHub release, upload it to your S3 bucket, then redeploy:

```bash
export LAMBDA_CODE_BUCKET=<your-s3-bucket-name>
export LAMBDA_CODE_KEY=dynatrace-aws-platform-monitoring-s3-log-forwarder/lambda-x86_64.zip

wget https://github.com/dynatrace/dynatrace-aws-platform-monitoring-s3-log-forwarder/releases/download/${VERSION_TAG}/lambda-x86_64.zip
aws s3 cp lambda-x86_64.zip "s3://${LAMBDA_CODE_BUCKET}/${LAMBDA_CODE_KEY}"

aws cloudformation deploy --stack-name ${STACK_NAME} \
            --template-file template.yaml \
            --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
            --parameter-overrides \
                DeploymentPackageType="zip" \
                LambdaCodeS3Bucket="${LAMBDA_CODE_BUCKET}" \
                LambdaCodeS3Key="${LAMBDA_CODE_KEY}"
```

> [!NOTE]
 >
 > * See [CloudFormation parameter reference](cloudformation_parameters.md) for all available parameters.

If successful, you'll see a message similar to the below at the end of the execution:

```bash
Successfully created/updated stack - dynatrace-s3-log-forwarder in us-east-1
```

## Rollback procedure

If you need to roll back to the previous version, repeat entire update procedure, but use the previous version to set the `VERSION_TAG` environment variable in Step 3.
