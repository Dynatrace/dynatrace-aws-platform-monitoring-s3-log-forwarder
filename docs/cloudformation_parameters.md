# CloudFormation parameter reference

This page documents all parameters for the main `template.yaml` stack.

## Required

| Parameter | Type | Description |
|-----------|------|-------------|
| `DynatraceEnvironmentURL` | String | URL of your Dynatrace environment, e.g. `https://{your-environment-id}.apps.dynatrace.com`. |
| `DynatraceApiKeySecretsManagerSecret` | String | ARN of an AWS Secrets Manager secret storing the Dynatrace platform token (scope: `data-acquisition:logs:ingest`). The secret must be a JSON object with the key `dt.platform_token`, e.g. `{"dt.platform_token":"<token>"}`. Mutually exclusive with `DynatraceApiKeySSMParameter`. |
| `DynatraceApiKeySSMParameter` | String | Path of a SecureString parameter in AWS Systems Manager Parameter Store storing the Dynatrace platform token (scope: `data-acquisition:logs:ingest`), e.g. `/dynatrace/s3-log-forwarder/my-stack/api-key`. Mutually exclusive with `DynatraceApiKeySecretsManagerSecret`. |

> [!NOTE]
>
> Exactly one of `DynatraceApiKeySecretsManagerSecret` or `DynatraceApiKeySSMParameter` must be provided.

## Deployment

| Parameter | Type | Default                                                                                                | Allowed values | Description |
|-----------|------|--------------------------------------------------------------------------------------------------------|----------------|-------------|
| `DeploymentPackageType` | String | `layer`                                                                                                | `layer`, `zip` | How Lambda function code is delivered. `layer` uses a pre-built Lambda Layer published by Dynatrace. `zip` expects you to upload the function ZIP package yourself after stack creation. |
| `DynatraceS3LogForwarderLayerArn` | String | _(empty — layer ARN resolved from the template's built-in region mapping, based od deployment region)_ | Valid Lambda Layer ARN | ARN of a custom Lambda Layer to use instead of the Dynatrace-published layer. If not provided, the ARN is automatically selected from the template's region map. Only set this when building from source or using a self-hosted layer. Ignored when `DeploymentPackageType=zip`. |
| `Architecture` | String | `x86_64`                                                                                               | `x86_64`, `arm64` | Instruction set architecture for the Lambda function. |

## S3 bucket access

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `GrantReadPermissionToBuckets` | CommaDelimitedList | _(empty)_ | Comma-separated list of S3 bucket names to grant the Lambda function `s3:GetObject` access to and create an EventBridge routing rule for (e.g. `my-bucket,another-bucket`). Use the [per-bucket stack](../dynatrace-aws-s3-log-forwarder-s3-bucket-configuration.yaml) for prefix filtering or cross-account/region buckets. |
| `GrantDecryptToKmsKeyArns` | CommaDelimitedList | _(empty)_ | Comma-separated list of KMS Key ARNs to grant the Lambda function `kms:Decrypt` access to. Required when S3 objects are encrypted with a customer-managed KMS key (SSE-KMS). |
| `S3NotificationsSNSTopicArns` | CommaDelimitedList | _(empty)_ | Comma-separated list of existing SNS topic ARNs permitted to deliver S3 Object Created notifications to the SQS queue (e.g. `arn:aws:sns:us-east-1:123456789012:topic-a,arn:aws:sns:us-east-1:123456789012:topic-b`). When provided, only the listed topics are allowed; when empty, no SNS topic has permission. You are responsible for subscribing each topic to the SQS queue after deployment. See [Option C in the deployment guide](deployment_guide.md#option-c-sns-fan-out). |

## Rules configuration

| Parameter | Type | Default | Allowed values | Description |
|-----------|------|---------|----------------|-------------|
| `LogForwarderConfigurationLocation` | String | `local` | `local`, `aws-appconfig` | Source for log forwarding and processing rules. `local` uses rules bundled with the deployment package. `aws-appconfig` fetches rules from AWS AppConfig, enabling dynamic updates without redeploying Lambda. Requires the [AppConfig stack](../dynatrace-aws-s3-log-forwarder-appconfig.yaml) to be deployed first. |

## Lambda

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `LambdaFunctionMemorySize` | Number | `256` | Memory allocated to the Lambda function in MB (128–10240). Higher memory also allocates more CPU and network bandwidth. |
| `LambdaMaximumExecutionTime` | Number | `300` | Maximum execution time in seconds for the Lambda function (up to 900). Increase for large log files or large batch sizes. |
| `MaximumLambdaConcurrency` | Number | `30` | Maximum number of concurrently executing Lambda functions. Concurrency is reserved, guaranteeing capacity. |
| `LambdaLoggingLevel` | String | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | Logging verbosity of the Lambda function. |
| `LambdaSubnetIds` | CommaDelimitedList | _(empty)_ | Comma-separated list of subnet IDs to run the Lambda function inside a VPC. Required when the Dynatrace ingest endpoint is only reachable via a private network. Select at least two subnets in different Availability Zones for HA. |
| `LambdaSecurityGroupId` | String | _(empty)_ | Security group ID to assign to the Lambda function when running inside a VPC. Must allow outbound access to the Dynatrace ingest endpoint. Required when `LambdaSubnetIds` is set. |

## SQS

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `LambdaSQSMessageBatchSize` | Number | `4` | Number of SQS messages processed per Lambda execution (max 10). Decrease for very large log files; increase for small files to improve throughput. |
| `SQSVisibilityTimeout` | Number | `420` | Seconds an SQS message is hidden from other consumers after being received. Must be greater than `LambdaMaximumExecutionTime` to prevent duplicate processing. |
| `SQSLongPollingMaxSeconds` | Number | `20` | Maximum seconds to wait for messages during a long-poll `ReceiveMessage` call (max 20). |
| `MaximumSQSMessageRetries` | Number | `3` | Number of times a failed S3 Object Created notification is retried before being sent to the Dead Letter Queue. |

## Cross-region and cross-account forwarding

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `EnableCrossRegionCrossAccountForwarding` | String | `false` | Set to `true` to create a dedicated EventBridge event bus for receiving cross-region and cross-account S3 Object Created notifications. |
| `AwsAccountsToReceiveLogsFrom` | CommaDelimitedList | _(empty)_ | Comma-separated list of AWS account IDs permitted to send cross-account S3 Object Created notifications to the event bus. Requires `EnableCrossRegionCrossAccountForwarding=true`. |

## Notifications and monitoring

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `NotificationsEmail` | String | _(empty)_ | Email address to receive CloudWatch alarm notifications (e.g. Dead Letter Queue alerts). |
| `CreateS3NotificationsSNSTopic` | String | `false` | Set to `true` to create an SNS topic for S3 Object Created notifications, enabling fan-out to multiple consumers. |
| `DeployCloudWatchMonitoringDashboard` | String | `true` | Set to `false` to skip deploying the CloudWatch monitoring dashboard. |

## Advanced

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `DynatraceLogIngestContentMaxLength` | Number | `65536` | Maximum log entry content size in bytes (8192–1048576). Entries exceeding this limit are truncated. |
| `VerifyLogEndpointSSLCerts` | String | `true` | Set to `false` to disable SSL certificate verification when posting logs to the Dynatrace endpoint. Only disable when routing traffic through an intercepting proxy with a custom CA. |
| `IamRolePath` | String | `/` | IAM path for the Lambda execution role, e.g. `/engineering/platform/`. Must start and end with `/`. Use when your organization requires IAM roles under a specific path. |
