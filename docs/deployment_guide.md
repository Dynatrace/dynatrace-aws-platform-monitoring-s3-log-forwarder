# Deployment instructions

## Prerequisites

The deployment instructions are written for Linux/MacOS. If you are running on Windows, use the Linux Subsystem for Windows, AWS CloudShell or an [AWS Cloud9](https://aws.amazon.com/cloud9/) instance.

You'll need the following software installed:

* [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)

You'll also need:

* A [Dynatrace access token](https://www.dynatrace.com/support/help/dynatrace-api/basics/dynatrace-api-authentication) for your tenant with the `logs.ingest` APIv2 scope.

## Deployment options

The `dynatrace-aws-platform-monitoring-s3-log-forwarder` supports two deployment package types:

| Option | Description |
|--------|-------------|
| **Lambda Layer** (default) | Use a Layer ARN provided by a maintainer (no build required) |
| **ZIP** | Lambda function code and dependencies packaged as a ZIP file |

## Deploy the dynatrace-aws-platform-monitoring-s3-log-forwarder

All core infrastructure — Lambda, SQS queues, IAM role, EventBridge rules, and S3 bucket permissions — is deployed from a single `template.yaml`. For a high level view of what's deployed, look at the diagram below:

![single-region-deployment](images/single-region-deployment.jpg)

### Step 1. Define a name for your `dynatrace-aws-platform-monitoring-s3-log-forwarder` deployment.

Define a name for your `dynatrace-aws-platform-monitoring-s3-log-forwarder` deployment (e.g. mycompany-dynatrace-s3-log-forwarder) and your Dynatrace tenant UUID (e.g. `abc12345` if your Dynatrace environment url is `https://abc12345.live.dynatrace.com`) in environment variables that will be used along the deployment process.

```bash
export STACK_NAME=<replace-with-your-log-forwarder-stack-name>
export DYNATRACE_TENANT_UUID=<replace-with-your-dynatrace-tenant-uuid>
```

> [!IMPORTANT]
>
> Your stack name should have a maximum of 47 characters, otherwise deployment will fail.

### Step 2. Store the Dynatrace API key in AWS Systems Manager Parameter Store

Store the Dynatrace API key as a SecureString parameter so the Lambda function can retrieve it at runtime:

```bash
export HISTCONTROL=ignorespace
 aws ssm put-parameter \
     --name "/dynatrace/s3-log-forwarder/$STACK_NAME/api-key" \
     --type SecureString \
     --value "<your_dynatrace-access-token-here>"
```

> [!NOTE]
>
> **Alternative:** If your security requirements are less strict, you can skip this step and pass the API key directly via `DynatraceApiKey` in the deploy command. The template will store it in an SSM Parameter (String type) and the Lambda reads from it. Note that the key will not be encrypted at rest — use `DynatraceApiKeySSMParameter` with a SecureString parameter as shown above if that is a requirement.

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

#### Default option: Lambda Layer

This is the simplest option — no build tools, SAM CLI, or Python required.

1. Set the Layer ARN:

```bash
export LAYER_ARN=<layer-version-arn-provided-by-publisher>
```

1. Deploy the main forwarder stack:

```bash
aws cloudformation deploy \
    --stack-name ${STACK_NAME} \
    --template-file template.yaml \
    --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
    --parameter-overrides \
        DynatraceEnvironmentURL="https://$DYNATRACE_TENANT_UUID.live.dynatrace.com" \
        DynatraceApiKeySSMParameter="/dynatrace/s3-log-forwarder/$STACK_NAME/api-key" \
        DynatraceS3LogForwarderLayerArn="$LAYER_ARN" \
        S3BucketNames="my-bucket,another-bucket"
```

> [!NOTE]
>
> When the publisher releases a new layer version, update the `DynatraceS3LogForwarderLayerArn` parameter with the new ARN and redeploy the stack to pick up the update.

---

#### Alternative option: ZIP deployment

1. Download the Lambda deployment package:

    ```bash
    wget https://dynatrace-aws-s3-log-forwarder-assets.s3.amazonaws.com/${VERSION_TAG}/lambda.zip
    ```

1. Deploy the CloudFormation stack:

    ```bash
    aws cloudformation deploy \
        --stack-name ${STACK_NAME} \
        --template-file template.yaml \
        --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
        --parameter-overrides \
            DynatraceEnvironmentURL="https://$DYNATRACE_TENANT_UUID.live.dynatrace.com" \
            DynatraceApiKeySSMParameter="/dynatrace/s3-log-forwarder/$STACK_NAME/api-key" \
            DeploymentPackageType="zip" \
            S3BucketNames="my-bucket,another-bucket"
    ```

1. Update the Lambda function code with the deployment package:

    ```bash
    FUNCTION_NAME=$(aws cloudformation describe-stacks --stack-name ${STACK_NAME} \
        --query 'Stacks[0].Outputs[?OutputKey==`QueueProcessingFunction`].OutputValue' \
        --output text | rev | cut -d':' -f1 | rev)

    aws lambda update-function-code --function-name ${FUNCTION_NAME} \
        --zip-file fileb://lambda.zip
    ```

    If successfull, you'll see a message similar to the below at the end of the execution:

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
> * An Amazon SNS topic is created to receive monitoring alerts where you can subscribe HTTP endpoints to send the notification to your tools (e.g. PagerDuty, Service Now...).
> * The template is deployed with a pre-defined set of default values to suit the majority of use cases. If you want to customize deployment values, you can find the parameter descriptions on the [template.yaml](../template.yaml) file.
> * To ingest logs into a Dynatrace Managed environment, the `DynatraceEnvironmentURL` parameter should be formatted like this: `https://{your-activegate-domain}:9999/e/{your-environment-id}`. Unless your environment Active Gate is public-facing, you'll need to configure Lambda to run on an Amazon VPC from where your Active Gate can be reached adding the parameters `LambdaSubnetIds` with the list of subnets where Lambda can run (for high availability, select at least 2 in different Availability Zones) and `LambdaSecurityGroupId` with the security group assigned to your Lambda function. The subnets where the Lambda function runs should allow outbound connectivity to the Internet. For more details, check the [AWS Lambda documentation](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc.htm). If your Active Gate uses a self-signed SSL certificate, set the parameter `VerifyLogEndpointSSLCerts` to `false`.
> * If ingesting logs into a Dynatrace Managed environment, add the parameter `DynatraceLogIngestContentMaxLength`=`8192`, as it is the default content length in Managed Dynatrace.

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

> [!NOTE]
> Direct S3 to SQS only works for buckets in the same AWS region as the log forwarder.

#### Option C: SNS fan-out

If you have an existing SNS topic receiving S3 Object Created notifications, subscribe the log forwarder's SQS queue to it:

```bash
aws sns subscribe \
    --topic-arn <your-sns-topic-arn> \
    --protocol sqs \
    --notification-endpoint $QUEUE_ARN
```

Alternatively, deploy the main stack with `CreateS3NotificationsSNSTopic=true` to create a dedicated SNS topic (`${StackName}-S3Notifications`) and subscribe your S3 buckets to it. This is useful for fan-out architectures where multiple consumers process the same S3 events.

For more details on all notification methods see [log_forwarding.md](log_forwarding.md).

> [!NOTE]
>
> * Options A and B only work for buckets in the same AWS account and region as the log forwarder. For cross-account or cross-region buckets, see [Advanced deployments](#advanced-deployments).
> * If your S3 objects are encrypted with a customer-managed KMS key, add `KmsKeyArns="arn:aws:kms:region:account:key/uuid,..."` to your Step 3 deploy command so the Lambda function can decrypt them.
> * `S3BucketNames` does not support prefix filtering. If you need to forward logs only from specific prefixes within a bucket, use the advanced option below instead.

## Advanced deployments

For detailed instructions on each scenario, see [advanced_deployments.md](advanced_deployments.md).

### Prefix filtering per bucket

`S3BucketNames` forwards all objects from the listed buckets. To forward only from specific key prefixes (e.g. `AWSLogs/123456789012/CloudTrail/`), deploy the `dynatrace-aws-s3-log-forwarder-s3-bucket-configuration.yaml` template once per bucket — it supports up to 10 prefixes and uses EventBridge for routing.

See [Configuring S3 buckets with prefix filtering](advanced_deployments.md#configuring-s3-buckets-with-prefix-filtering).

### Custom log forwarding and processing rules

By default the forwarder uses built-in rules. To customise which logs are forwarded and how they are parsed at runtime without redeploying Lambda, deploy the optional `dynatrace-aws-s3-log-forwarder-appconfig.yaml` template.

See [Custom log forwarding and processing rules via AppConfig](advanced_deployments.md#custom-log-forwarding-and-processing-rules-via-appconfig).

### IAM role path

If your organization requires IAM roles to be created under a specific path (e.g. `/engineering/platform/`), use the `IamRolePath` parameter.

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

To learn more, check our [DQL documentation](https://docs.dynatrace.com/docs/platform/grail/dynatrace-query-language/dql-guide). You can also find a set of provided patterns to extract attributes for common logs in the [DPL Architect](https://docs.dynatrace.com/docs/platform/grail/dynatrace-pattern-language/dpl-architect). If you use Dynatrace Managed Cluster or a Dynatrace tenant without Grail enabled, check the [Log Monitoring Classic docs](https://docs.dynatrace.com/docs/observe-and-explore/logs/log-monitoring/analyze-log-data).

For more detailed information and advanced configuration details of the `dynatrace-aws-platform-monitoring-s3-log-forwarder`, visit the documentation in the `docs` folder.
