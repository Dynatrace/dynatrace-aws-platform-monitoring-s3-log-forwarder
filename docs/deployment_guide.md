# Deployment instructions

## Prerequisites

The deployment instructions are written for Linux/MacOS. If you are running on Windows, use the Linux Subsystem for Windows, AWS CloudShell or an [AWS Cloud9](https://aws.amazon.com/cloud9/) instance.

You'll need the following software installed:

* [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)

You'll also need:

* A Dynatrace [platform token](https://docs.dynatrace.com/docs/manage/identity-access-management/access-tokens-and-oauth-clients/platform-tokens) for your tenant with the `data-acquisition:logs:ingest` scope (used to authenticate against the generic S3 logs ingest API).
* An AWS identity (user or role) with the required IAM permissions — see [Required AWS IAM permissions](iam_permissions.md).

## Deployment options

The `dynatrace-aws-platform-monitoring-s3-log-forwarder` supports two deployment package types:

| Option                         | Description                                                     |
|--------------------------------|-----------------------------------------------------------------|
| **Lambda Layer** (recommended) | Use a Lambda Layer provided by a maintainer (no build required) |
| **ZIP**                        | Lambda function code and dependencies packaged as a ZIP file    |

## Deploy the dynatrace-aws-platform-monitoring-s3-log-forwarder

All core infrastructure — Lambda, SQS queues, IAM role, EventBridge rules, and S3 bucket permissions — is deployed from a single `template.yaml`. For a high level view of what's deployed, look at the diagram below:

![single-region-deployment](images/single-region-deployment.jpg)

### Step 1. Define a name for your `dynatrace-aws-platform-monitoring-s3-log-forwarder` deployment.

Define a name for your `dynatrace-aws-platform-monitoring-s3-log-forwarder` deployment (e.g. mycompany-dynatrace-s3-log-forwarder) and your Dynatrace tenant UUID (e.g. `abc12345` if your Dynatrace environment url is `https://abc12345.apps.dynatrace.com`) in environment variables that will be used along the deployment process.

```bash
export STACK_NAME=<replace-with-your-log-forwarder-stack-name>
export DYNATRACE_TENANT_UUID=<replace-with-your-dynatrace-tenant-uuid>
```

> [!IMPORTANT]
>
> Your stack name should have a maximum of 47 characters, otherwise deployment will fail.

### Step 2. Provide the Dynatrace platform token

The Lambda function needs a Dynatrace platform token (scope `data-acquisition:logs:ingest`) to authenticate against the log ingest API. There are three mutually exclusive options — choose one:

---

#### Option A: Existing AWS Secrets Manager secret (recommended)

If you already have a Secrets Manager secret storing the token, reference it directly. The secret value must be the plain token string. #TODO: update

```bash
export DT_TOKEN_SECRET_ARN=<arn-of-your-existing-secrets-manager-secret>
```

---

#### Option B: AWS Systems Manager Parameter Store

Store the token as a SecureString parameter:

```bash
export HISTCONTROL=ignorespace
 aws ssm put-parameter \
     --name "/dynatrace/s3-log-forwarder/$STACK_NAME/api-key" \
     --type SecureString \
     --value "<your_dynatrace_platform_token_here>"
```

Pass `DynatraceApiKeySSMParameter="/dynatrace/s3-log-forwarder/$STACK_NAME/api-key"` in the deploy command in Step 4.

---

#### Option C: Plain text token (stack creates a Secrets Manager secret)

Pass the token directly in the deploy command — the stack creates a new Secrets Manager secret to store it securely.

Pass `DynatraceApiKey="<your_dynatrace_platform_token_here>"` in the deploy command in Step 4.

---

### Step 3. Download the CloudFormation templates

Download the CloudFormation templates for the latest release:

```bash
export VERSION_TAG=$(curl -s https://api.github.com/repos/dynatrace/dynatrace-aws-platform-monitoring-s3-log-forwarder/releases/latest | grep tag_name | cut -d'"' -f4)
mkdir dynatrace-aws-platform-monitoring-s3-log-forwarder && cd "$_"
wget https://dynatrace-aws-s3-log-forwarder-assets.s3.amazonaws.com/${VERSION_TAG}/templates.zip
unzip templates.zip
```

### Step 4. Deploy the Lambda function

Choose one of the deployment options below:

---

#### Lambda Layer (recommended)

1. Deploy the main forwarder stack:

    ```bash
    aws cloudformation deploy \
        --stack-name ${STACK_NAME} \
        --template-file template.yaml \
        --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
        --parameter-overrides \
            DynatraceEnvironmentURL="https://$DYNATRACE_TENANT_UUID.live.dynatrace.com" \
            DynatraceApiKeySecretsManagerSecret="$DT_TOKEN_SECRET_ARN" \
            Architecture="x86_64" \
            S3BucketNames="my-bucket,another-bucket"
    ```

    > [!NOTE]
    >
    > * Replace `DynatraceApiKeySecretsManagerSecret` with the token parameter that matches your choice in Step 2:
    >   `DynatraceApiKeySSMParameter="/dynatrace/s3-log-forwarder/$STACK_NAME/api-key"` (Option B) or
    >   `DynatraceApiKey="<your_dynatrace_platform_token_here>"` (Option C).
    > * Set `Architecture=arm64` to deploy on arm64. Make sure the Layer ARN you selected matches the architecture.
    > * If your S3 objects are encrypted with a customer-managed KMS key, add `KmsKeyArns="arn:aws:kms:region:account:key/uuid,..."` to  `--parameter-voerrides` in deploy command.
    > * When `S3BucketNames` is passed, no prefix filtering is supported. If you want more fine-grained control, see [Prefix filtering per bucket](#prefix-filtering-per-bucket) in the Advanced deployments section.

---

#### Zip deployment (alternative option)

1. Download the Lambda deployment package for your target architecture:

    ```bash
    wget https://dynatrace-aws-s3-log-forwarder-assets.s3.amazonaws.com/${VERSION_TAG}/lambda-x86_64.zip
    # or for arm64:
    # wget https://dynatrace-aws-s3-log-forwarder-assets.s3.amazonaws.com/${VERSION_TAG}/lambda-arm64.zip
    ```

2. Deploy the CloudFormation stack:

    ```bash
    aws cloudformation deploy \
        --stack-name ${STACK_NAME} \
        --template-file template.yaml \
        --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
        --parameter-overrides \
            DynatraceEnvironmentURL="https://$DYNATRACE_TENANT_UUID.apps.dynatrace.com" \
            DynatraceApiKeySecretsManagerSecret="$DT_TOKEN_SECRET_ARN" \
            DeploymentPackageType="zip" \
            Architecture="x86_64" \
            S3BucketNames="my-bucket,another-bucket"
    ```

    > [!NOTE]
    >
    > * Replace `DynatraceApiKeySecretsManagerSecret` with the token parameter that matches your choice in Step 2:
    >   `DynatraceApiKeySSMParameter="/dynatrace/s3-log-forwarder/$STACK_NAME/api-key"` (Option B) or
    >   `DynatraceApiKey="<your_dynatrace_platform_token_here>"` (Option C).
    > * Set `Architecture=arm64` for arm64 deployments.
    > * If your S3 objects are encrypted with a customer-managed KMS key, add `KmsKeyArns="arn:aws:kms:region:account:key/uuid,..."` to  `--parameter-voerrides` in deploy command.
    > * When `S3BucketNames` is passed, no prefix filtering is supported. If you want more fine-grained control, see [Prefix filtering per bucket](#prefix-filtering-per-bucket) in the Advanced deployments section.
    >
    > *
3. Update the Lambda function code with the deployment package:

    ```bash
    FUNCTION_NAME=$(aws cloudformation describe-stacks --stack-name ${STACK_NAME} \
        --query 'Stacks[0].Outputs[?OutputKey==`QueueProcessingFunction`].OutputValue' \
        --output text | rev | cut -d':' -f1 | rev)

    aws lambda update-function-code --function-name ${FUNCTION_NAME} \
        --zip-file fileb://lambda-x86_64.zip   # or lambda-arm64.zip
    ```

    If successful, you'll see a message similar to the below at the end of the execution:

    ```json
    {
        "FunctionName": "...",
        "LastUpdateStatus": "InProgress"
    }
    ```

---

> [!NOTE]
>
> * You can optionally configure notifications on your e-mail address to receive alerts when log files can't be processed and messages are arriving to the Dead Letter Queue. To do so, add the parameter `NotificationsEmail`=`your_email_address_here`.
> * An Amazon SNS topic named `<stack-name>-Alarms` is created to receive monitoring alerts where you can subscribe HTTP endpoints to send the notification to your tools. The topic ARN is available in the stack output as `SNSAlertsTopic`.
> * The template is deployed with a pre-defined set of default values to suit the majority of use cases. If you want to customize deployment values, you can find the parameter descriptions on the [template.yaml](../template.yaml) file.

### Step 5. Configure S3 buckets to send "S3 Object created" notifications to the log forwarder.

At this point, you have successfully deployed the `dynatrace-aws-platform-monitoring-s3-log-forwarder`. Now you need to configure each S3 bucket to send `Object Created` notifications to the log forwarder. There are three supported methods:

#### Option A: Amazon EventBridge (recommended)

If you provided `S3BucketNames` in Step 4, the main stack has already created an EventBridge rule routing `Object Created` events from the listed buckets to the SQS queue. Enable EventBridge notifications on each bucket:

```bash
for BUCKET in my-bucket another-bucket; do
  aws s3api put-bucket-notification-configuration \
    --bucket $BUCKET \
    --notification-configuration '{"EventBridgeConfiguration": {}}'
done
```

Or via the console: S3 bucket → **Properties** → **Amazon EventBridge** → **Send notifications to Amazon EventBridge** → **On**.

#### Option B: Direct S3 to SQS

Configure the S3 bucket to send `Object Created` notifications directly to the log forwarder's SQS queue. Retrieve the queue ARN first:

```bash
QUEUE_ARN=$(aws ssm get-parameter \
    --name "/dynatrace/s3-log-forwarder/${STACK_NAME}/sqs-queue-arn" \
    --query 'Parameter.Value' --output text)
```

Then configure the bucket notification ([AWS instructions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/ways-to-add-notification-config-to-bucket.html)). The SQS queue policy already allows the buckets listed in `S3BucketNames` to send notifications directly.

#### Option C: SNS fan-out

If you have an existing SNS topic receiving S3 Object Created notifications, subscribe the log forwarder's SQS queue to it:

```bash
aws sns subscribe \
    --topic-arn <your-sns-topic-arn> \
    --protocol sqs \
    --notification-endpoint $QUEUE_ARN
```

Alternatively, deploy the main stack with `CreateS3NotificationsSNSTopic=true` to create a dedicated SNS topic (`${StackName}-S3Notifications`) and subscribe your S3 buckets to it. This is useful for fan-out architectures where multiple consumers process the same S3 events.

> [!NOTE]
>
> * Options A and B only work for buckets in the same AWS account and region as the log forwarder. For cross-account or cross-region buckets, see [Advanced deployments](#advanced-deployments).

## Advanced deployments

For detailed instructions on each scenario, see [advanced_deployments.md](advanced_deployments.md).

### Prefix filtering per bucket

`S3BucketNames` forwards all objects from the listed buckets. To forward only from specific key prefixes, deploy the `dynatrace-aws-s3-log-forwarder-s3-bucket-configuration.yaml` template once per bucket — it supports up to 10 prefixes and uses EventBridge for routing.

See [Configuring S3 buckets with prefix filtering](advanced_deployments.md#configuring-s3-buckets-with-prefix-filtering).

### Custom log forwarding and processing rules

By default, the forwarder uses built-in rules (see: [src/log/processing/rules/aws/](../src/log/processing/rules/aws/)). To customize which logs are forwarded and how they are parsed at runtime without redeploying the main stack, deploy the optional `dynatrace-aws-s3-log-forwarder-appconfig.yaml` template.

See [Custom log forwarding and processing rules via AppConfig](advanced_deployments.md#custom-log-forwarding-and-processing-rules-via-appconfig).

### IAM role path

If your organization policies require IAM roles to be created under a specific path (e.g. `/engineering/platform/`), use the `IamRolePath` parameter.

See [IAM Role path](advanced_deployments.md#iam-role-path).

### Cross-region forwarding

Centralize log forwarding from S3 buckets in different AWS regions into a single forwarder deployment. Requires enabling a dedicated EventBridge event bus on the main stack and deploying the `eventbridge-cross-region-or-account-forward-rules.yaml` template in the bucket's region.

See [Forward logs from S3 buckets on different AWS regions](advanced_deployments.md#forward-logs-from-s3-buckets-on-different-aws-regions).

### Cross-account forwarding

Forward logs from S3 buckets in different AWS accounts into a single forwarder deployment. Requires enabling the cross-account event bus, granting permissions to source accounts, and configuring bucket policies to allow the forwarder's IAM role.

See [Forward logs from S3 buckets on different AWS accounts](advanced_deployments.md#forward-logs-from-s3-buckets-on-different-aws-accounts).

## Next steps

At this stage, you should see logs being ingested in Dynatrace as they're written to Amazon S3.

You can explore logs using the Dynatrace [Logs and events viewer](https://docs.dynatrace.com/docs/observe-and-explore/logs/log-management-and-analytics/lma-analysis/logs-and-events), as well as create metrics and alerts based on ingested logs (see [Log metrics](https://docs.dynatrace.com/docs/observe-and-explore/logs/log-management-and-analytics/lma-analysis/lma-log-metrics) and [Log events](https://docs.dynatrace.com/docs/observe-and-explore/logs/log-management-and-analytics/lma-analysis/lma-log-events) documentation).

You can also perform deep log analysis with [Dynatrace Notebooks](https://docs.dynatrace.com/docs/observe-and-explore/notebook). See some example Dynatrace Query Language (DQL) queries below:

### Query logs ingested from S3 Bucket "mybucket"

```custom
fetch logs
| filter log.source.aws.s3.bucket.name == "mybucket"
```

### Query AWS CloudTrail logs:

```custom
fetch logs
| filter aws.service == "cloudtrail"
```

### Get the number of log entries per AWS Service

```custom
fetch logs
| filter isNotNull(aws.service) 
| summarize {count(),alias:log_entries}, by: aws.service
```

### Extract attributes from JSON Logs: Add sourceInstanceId log attribute from VPC DNS Query Logs

```custom
fetch logs 
| filter matchesValue(aws.service, "route53")
| parse content, "JSON:record"
| fieldsAdd record[srcids][instance], alias:sourceInstanceId
```

### Flatten a JSON formatted log

```custom
fetch logs 
| filter matchesValue(aws.service, "route53")
| parse content, "JSON:record"
| fieldsFlatten record
```

To learn more, check our [DQL documentation](https://docs.dynatrace.com/docs/platform/grail/dynatrace-query-language/dql-guide). You can also find a set of provided patterns to extract attributes for common logs in the [DPL Architect](https://docs.dynatrace.com/docs/platform/grail/dynatrace-pattern-language/dpl-architect).

For more detailed information and advanced configuration details of the `dynatrace-aws-platform-monitoring-s3-log-forwarder`, visit the documentation in the `docs` folder.
