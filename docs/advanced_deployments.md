# Advanced Deployments

This page contains guidance and considerations for large deployments.

## IAM Role path

Some organizations enforce IAM governance policies that require roles to be created under a specific path (e.g. `/engineering/` or `/service-roles/`). Without the correct path, CloudFormation stack deployment will fail with an access denied error.

Use the `IamRolePath` parameter to set the path for the Lambda execution role:

```bash
aws cloudformation deploy \
    --stack-name ${STACK_NAME} \
    --template-file template.yaml \
    --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
    --parameter-overrides \
        DynatraceEnvironmentURL="https://$DYNATRACE_TENANT_UUID.live.dynatrace.com" \
        DynatraceApiKeyParameter=$PARAMETER_NAME \
        DynatraceS3LogForwarderLayerArn="$LAYER_ARN" \
        IamRolePath="/engineering/platform/"
```

The path must start and end with `/`. If not specified, the role is created at the root path `/`.

## Configuring S3 buckets with prefix filtering

The `S3BucketNames` parameter in `template.yaml` forwards logs from entire buckets. If you need to forward logs only from specific S3 key prefixes within a bucket, use the `dynatrace-aws-s3-log-forwarder-s3-bucket-configuration.yaml` template once per bucket instead.

Deploy the main stack without `S3BucketNames`:

```bash
aws cloudformation deploy \
    --stack-name ${STACK_NAME} \
    --template-file template.yaml \
    --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
    --parameter-overrides \
        DynatraceEnvironmentURL="https://$DYNATRACE_TENANT_UUID.live.dynatrace.com" \
        DynatraceApiKeyParameter=$PARAMETER_NAME \
        DynatraceS3LogForwarderLayerArn="$LAYER_ARN"
```

Then deploy the per-bucket stack for each bucket, specifying the prefixes to forward logs from:

```bash
export BUCKET_NAME=your-bucket-name

aws cloudformation deploy \
    --template-file dynatrace-aws-s3-log-forwarder-s3-bucket-configuration.yaml \
    --stack-name dynatrace-aws-s3-log-forwarder-s3-bucket-configuration-$BUCKET_NAME \
    --parameter-overrides \
        DynatraceAwsS3LogForwarderStackName=$STACK_NAME \
        LogsBucketName=$BUCKET_NAME \
        LogsBucketPrefix1=AWSLogs/123456789012/CloudTrail/ \
        LogsBucketPrefix2=AWSLogs/987654321098/CloudTrail/ \
    --capabilities CAPABILITY_IAM
```

You can specify up to 10 prefixes per bucket using `LogsBucketPrefix1` through `LogsBucketPrefix10`. Prefixes should end with `/` to match all objects under that path.

> [!WARNING]
>
> Do not add a bucket to both `S3BucketNames` in the main stack and a per-bucket configuration stack. The main stack's EventBridge rule matches all `Object Created` events from that bucket with no prefix filter, so objects in the prefix would be routed to SQS by both rules and ingested into Dynatrace twice.

> [!NOTE]
>
> * If your S3 objects are encrypted with a customer-managed KMS key, add `KmsKeyArns="arn:aws:kms:region:account:key/uuid"` to the main stack deploy command so the Lambda function can decrypt them.
> * For cross-region or cross-account buckets, add the `S3BucketIsCrossRegionOrCrossAccount=true` parameter and deploy the `eventbridge-cross-region-or-account-forward-rules.yaml` template in the bucket's account/region. See [log_forwarding.md](log_forwarding.md#forward-logs-from-s3-buckets-on-different-aws-regions) for details.
> * Each per-bucket stack adds an inline IAM policy statement to the Lambda execution role. See [IAM Role Policy size limit](#iam-role-policy-size-limit) below for scaling considerations.

## Log forwarding throughput

This solution has been tested to forward logs to Dynatrace at a throughput of 10 GB / min.

For high throughput scenarios you may need to adjust the `MaximumLambdaConcurrency` parameter. Look also at the [log_forwarding.md](log_forwarding.md#forwarding-large-log-files-to-dynatrace) documentation to understand how parameters influence the behavior of the log forwarding Lambda function.

## AWS Quotas to consider

### IAM Role Policy size limit

There's a hard-limit of the aggregate policy size of IAM policies in-line policies for an IAM role of 10,240 characters. The `dynatrace-aws-s3-log-forwarder-s3-bucket-configuration.yaml` CloudFormation template adds an in-line IAM policy to the IAM role used by AWS Lambda for each S3 bucket you configure to forward logs from. With the template provided as is, you can grant access to 20 - 25 Amazon S3 buckets (actual number will vary depending on bucket name size and whether or not you're restricting prefixes within the bucket(s)).

If you need to configure more S3 buckets, you may be able to optimize IAM policy space by building your own policy (the provided template is designed for ease of use, not scale). Also, if your buckets have common prefixes on their names, you can use wildcards on your policies to match multiple buckets with common prefix in the name.

For more details about this limit, check the IAM documentation [here](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_iam-quotas.html#reference_iam-quotas-entity-length).

### AWS AppConfig hosted configuration store size limit

By default, hosted configurations in AWS have a size limit of 1 MB. This limit can be adjusted upon request to AWS. For more information, visit the AWS AppConfig documentation [here](https://docs.aws.amazon.com/general/latest/gr/appconfig.html#limits_appconfig).

Note that, as we're managing the hosted configurations with CloudFormation passing configuration in-line, there's also [Cloudformation limits](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cloudformation-limits.html) to take into account:

* Template body size in a request: 51,200 bytes: To use a larger template body, upload your template to Amazon S3.
* Template body size in an Amazon S3 Object: 1 MB

If your configuration is bigger than the above limits, you'll have to use S3-backed configurations. For more information, check the AWS AppConfig documentation [here](https://docs.aws.amazon.com/appconfig/latest/userguide/appconfig-creating-configuration-and-profile.html#appconfig-creating-configuration-and-profile-S3-source).
