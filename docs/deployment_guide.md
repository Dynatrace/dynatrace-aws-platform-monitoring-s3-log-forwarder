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

All core infrastructure — Lambda, SQS queues, AppConfig, IAM role, EventBridge rules, and S3 bucket permissions — is deployed from a single `template.yaml`. For a high level view of what's deployed, look at the diagram below:

![single-region-deployment](images/single-region-deployment.jpg)

### Step 1. Define a name for your `dynatrace-aws-platform-monitoring-s3-log-forwarder` deployment.

Define a name for your `dynatrace-aws-platform-monitoring-s3-log-forwarder` deployment (e.g. mycompany-dynatrace-s3-log-forwarder) and your Dynatrace tenant UUID (e.g. `abc12345` if your Dynatrace environment url is `https://abc12345.live.dynatrace.com`) in environment variables that will be used along the deployment process.

```bash
export STACK_NAME=<replace-with-your-log-forwarder-stack-name>
export DYNATRACE_TENANT_UUID=<replace-with-your-dynatrace-tenant-uuid>
```

> [!IMPORTANT]
>
> Your stack name should have a maximum of 53 characters, otherwise deployment will fail.

### Step 2. Create an AWS SSM SecureString Parameter to store your Dynatrace access token to ingest logs.

Execute the following command to create an AWS SSM Parameter Store SecureString parameter to store your Dynatrace access token. The log forwarder Lambda function retrieves the access token from this parameter at runtime.

```bash
export PARAMETER_NAME="/dynatrace/s3-log-forwarder/$STACK_NAME/$DYNATRACE_TENANT_UUID/api-key"
# Configure HISTCONTROL to avoid storing on the bash history the commands containing API keys
export HISTCONTROL=ignorespace
 export PARAMETER_VALUE=<your_dynatrace-access-token-here>
 aws ssm put-parameter --name $PARAMETER_NAME --type SecureString --value $PARAMETER_VALUE
```

> [!NOTE]
>
> * HISTCONTROL is set here to avoid storing commands starting with a space on bash history.
> * It's important that your parameter name follows the structure above, as the solution grants permissions to AWS Lambda to the hierarchy `/dynatrace/s3-log-forwarder/your-stack-name/*`
> * Your API Key is stored encyrpted with the default AWS-managed key alias: `aws/ssm`. If you want to use a Customer-managed Key, you'll need to grant Decrypt permissions to the AWS Lambda IAM Role that's deployed within the CloudFormation template.

### Step 3. Download the CloudFormation templates and Lambda package

Download the templates and pre-built Lambda ZIP for the latest release:

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
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
    --parameter-overrides \
        DynatraceEnvironmentURL="https://$DYNATRACE_TENANT_UUID.live.dynatrace.com" \
        DynatraceApiKeyParameter=$PARAMETER_NAME \
        DynatraceS3LogForwarderLayerArn="$LAYER_ARN" \
        S3BucketNames="my-bucket,another-bucket"
```

> **Note:** When the publisher releases a new layer version, update the `DynatraceS3LogForwarderLayerArn` parameter with the new ARN and redeploy the stack to pick up the update.

---

> [!IMPORTANT]
> If you deployed using the default Lambda Layer option above, continue directly to [Step 5. Configure S3 buckets](#step-5-configure-s3-buckets-to-send-s3-object-created-notifications-to-the-log-forwarder).

---

#### Alternative option: ZIP deployment

1. Deploy the CloudFormation stack:

```bash
aws cloudformation deploy \
    --stack-name ${STACK_NAME} \
    --template-file template.yaml \
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
    --parameter-overrides \
        DynatraceEnvironmentURL="https://$DYNATRACE_TENANT_UUID.live.dynatrace.com" \
        DynatraceApiKeyParameter=$PARAMETER_NAME \
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
> * An Amazon SNS topic is created to receive monitoring alerts where you can subscribe HTTP endpoints to send the notification to your tools (e.g. PagerDuty, Service  Now...).
> * The template is deployed with a pre-defined set of default values to suit the majority of use cases. If you want to customize deployment values, you can find the parameter descriptions on the [template.yaml](../template.yaml) file. You'll find more information on the [docs/advanced_deployments](advanced_deployments.md) documentation.
> * To ingest logs into a Dynatrace Managed environment, the `DynatraceEnvironmentURL` parameter should be formatted like this: `https://{your-activegate-domain}:9999/e/{your-environment-id}`. Unless your environment Active Gate is public-facing, you'll need to configure Lambda to run on an Amazon VPC from where your Active Gate can be reached adding the parameters `LambdaSubnetIds` with the list of subnets where Lambda can run (for high availability, select at least 2 in different Availability Zones) and `LambdaSecurityGroupId` with the security group assigned to your Lambda function. The subnets where the Lambda function runs should allow outbound connectivity to the Internet. For more details, check the [AWS Lambda documentation](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc.htm). If your Active Gate uses a self-signed SSL certificate, set the parameter `VerifyLogEndpointSSLCerts` to `false`.
> * If ingesting logs into Dynatrace Managed environment, add the parameter `DynatraceLogIngestContentMaxLength`=`8192`, as it is default content length in Managed Dynatrace.

### Step 5. Configure S3 buckets to send "S3 Object created" notifications to the log forwarder.

At this point, you have successfully deployed the `dynatrace-aws-platform-monitoring-s3-log-forwarder`. Now you need to enable Amazon EventBridge notifications on each S3 bucket you listed in `S3BucketNames`.

#### Simple use case (same AWS account and region)

If you provided `S3BucketNames` in Step 4, the main stack has already:

* Created an Amazon EventBridge rule per bucket routing `Object Created` events to the SQS queue
* Granted the Lambda function `s3:GetObject` access to each bucket
* Configured the SQS queue policy to accept notifications from those buckets

The only remaining action is to enable EventBridge notifications on each S3 bucket:

```bash
for BUCKET in my-bucket another-bucket; do
  aws s3api put-bucket-notification-configuration \
    --bucket $BUCKET \
    --notification-configuration '{"EventBridgeConfiguration": {}}'
done
```

Or via the console: S3 bucket → **Properties** → **Amazon EventBridge** → **Send notifications to Amazon EventBridge** → **On**.

> [!NOTE]
>
> * This only works for buckets in the same AWS account and region as the log forwarder.
> * If your S3 objects are encrypted with a customer-managed KMS key, add `KmsKeyArns="arn:aws:kms:region:account:key/uuid,..."` to your Step 4 deploy command so the Lambda function can decrypt them.
> * `S3BucketNames` does not support prefix filtering. If you need to forward logs only from specific prefixes within a bucket, use the advanced option below instead.

---

#### Advanced option: per-bucket stack with prefix filtering or cross-account/region

Use the `dynatrace-aws-s3-log-forwarder-s3-bucket-configuration.yaml` template when you need:

* **Prefix filtering** — forward logs only from specific S3 key prefixes
* **Cross-region or cross-account** — buckets in a different AWS account or region than the log forwarder

Deploy once per bucket:

```bash
export BUCKET_NAME=your-bucket-name-here

aws cloudformation deploy \
    --template-file dynatrace-aws-s3-log-forwarder-s3-bucket-configuration.yaml \
    --stack-name dynatrace-aws-s3-log-forwarder-s3-bucket-configuration-$BUCKET_NAME \
    --parameter-overrides \
        DynatraceAwsS3LogForwarderStackName=$STACK_NAME \
        LogsBucketName=$BUCKET_NAME \
        LogsBucketPrefix1=my-prefix/ \
    --capabilities CAPABILITY_IAM
```

Then enable EventBridge notifications on the bucket as shown above.

> [!NOTE]
>
> * You can specify up to 10 prefix filters per bucket using `LogsBucketPrefix1` through `LogsBucketPrefix10`.
> * For cross-region or cross-account buckets, add `S3BucketIsCrossRegionOrCrossAccount=true` and deploy the `eventbridge-cross-region-or-account-forward-rules.yaml` template in the bucket's account/region. See the [log forwarding docs](log_forwarding.md#forward-logs-from-s3-buckets-on-different-aws-regions) for details.
> * When using this advanced option, do not also add the bucket to `S3BucketNames` in the main stack — the per-bucket stack already grants the necessary IAM permissions.

---

#### Other notification methods

The log forwarder also supports SNS fan-out and direct S3-to-SQS notifications. See [S3 notification source options](log_forwarding.md#s3-notification-source-options) for details.

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
