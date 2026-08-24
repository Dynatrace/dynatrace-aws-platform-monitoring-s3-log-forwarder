# Log Forwarding rules

The `dynatrace-aws-platform-monitoring-s3-log-forwarder` uses log forwarding rules to determine how to process log files. By default, rules are bundled locally inside the Lambda package — a catch-all rule forwards all objects from any bucket using built-in AWS log processing. No additional setup is required for the default behaviour.

For runtime rule customisation without redeploying Lambda, you can optionally deploy the `dynatrace-aws-s3-log-forwarder-appconfig.yaml` template, which creates an [AWS AppConfig](https://docs.aws.amazon.com/appconfig/latest/userguide/what-is-appconfig.html) application with two configuration profiles:

* `log-forwarding-rules`: stores log forwarding rules.
* `log-processing-rules`: stores custom log processing rules. For more information, check the [log_processing.md](log_processing.md) documentation.

Once deployed, redeploy the main stack with `LogForwarderConfigurationLocation=aws-appconfig`.

The section below outlines how to configure custom log forwarding rules.

## Configuring log forwarding rules

The anatomy of the `log-forwarding-rules` configuration profile is the following:

  ```yaml
  ---
  bucket_name: your_s3_bucket_1
  log_forwarding_rules:
    - name: Required[str]           # --> Name that identifies the rule
      prefix: Required[str]          # --> Regular expression that will be matched against each S3 Key name to determine whether the rule applies to it
      source: Required[str]          # --> valid values are 'aws', 'generic' or 'custom'
      source_name: Optional[str]     # --> this field is only required and used for 'custom' rules. 
      annotations: Optional[dict]    # --> contains user-defined key/value data to be added as attribute to the log entries
        key1: value
        key2: value
    - name: Required[str]       
      prefix: Required[str]     
      source: Required[str]     
      source_name: Optional[str]
      annotations: Optional[dict
        key1: value
        key2: value
  ---
  bucket_name: your_s3_bucket_2
  log_forwarding_rules:
    - name: Required[str]           
      prefix: Required[str]         
      source: Required[str]         
      source_name: Optional[str]    
      annotations: Optional[dict]   
        key1: value
        key2: value
  ```

If you define a rule set using `default` as bucket name, that rule set will be used for log objects from any S3 bucket that doesn't have explicit log forwarding rules set up.

Without a `default` rule, each Amazon S3 bucket from which you want to forward logs from to Dynatrace requires explicit log forwarding rules. If the Lambda function receives an S3 Object created notification and there are no explicit rules for the S3 bucket, or the object S3 Key doesn't match any of the prefix regular expressions defined on the rules for the bucket, the object is not forwarded to Dynatrace and just discarded.

You can use explicit log forwarding rule sets for some buckets, and fallback to a default rule for other buckets; or simply delete the default rule, so only explicit rules are applied.

The prefix field allows you to define a regular expression to match against the S3 key name of your log objects to determine whether a rule applies to it or not. Rules are evaluated in order, meaning that if an S3 key matches multiple rules, the first rule that matches in the order they're defined will apply. If you want to define a generic rule that applies to any object within a bucket, you can use `'.*'` as prefix. Or you can define explicit rules, and a final rule with prefix `'.*'` that will apply to any objects that didn't match any prior rules.

Log forwarding rules allow you to add custom annotations to your logs (e.g team: x, environment: dev) as well as tell the log forwarding function how to process your AWS, application/3rd party logs: AWS-vended logs (source:aws), generic text logs (source: generic) or other logs that you've defined log processing rules for (source: custom). All forwarded logs are automatically annotated with the following context attributes:

* dt.da.aws.s3.bucket.name: name of the S3 bucket the log was forwarded from
* dt.da.aws.s3.key.name: key name of the S3 object that the log entry belongs to
* dt.da.aws.forwarder.arn: AWS ARN of the forwarder lambda function

The `dynatrace-aws-platform-monitoring-s3-log-forwarder` automatically annotates logs and extracts relevant attributes for [supported AWS services](../README.md#supported-aws-services) with fields like `aws.account.id`, `aws.region`...

For any other logs you may want to ingest from S3, you can just ingest any text-based logs as `generic` logs (source: generic) and stream of JSON entries logs as `generic_json_stream` (source: generic, source_name: generic_json_stream). Then, you can [configure Dynatrace to process the logs at ingestion time](https://www.dynatrace.com/support/help/how-to-use-dynatrace/log-monitoring/acquire-log-data/log-processing) to enrich them or parse them at query time with [DQL](https://www.dynatrace.com/support/help/how-to-use-dynatrace/log-monitoring/acquire-log-data/log-processing/log-processing-commands). Optionally, you can do custom processing on the Lambda function (e.g. extract log entries from a list in a JSON key) defining your own log processing rules. For more information, visit the [log_processing](log_processing.md) documentation.

### Example log-forwarding-rules rule sets

Let's take as example an S3 bucket called `my_bucket` where we're consolisating logs from multiple sources:

* Amazon ELB and Amazon CloudTrail logs (log prefix format is pre-defined by AWS)
* Nginx access logs

The log-forwarding-rules set for the S3 bucket could look like the following:

```yaml
---
bucket_name: my_bucket
log_forwarding_rules:
  - name: fwd_ctral_and_elb_logs         
    prefix: "^AWSLogs/.*/(CloudTrail|elasticloadbalancing)/.*"      
    source: aws
    annotations:
      environment: dev
  - name: fwd_nginx_logs
    prefix: ^nginx/.*(\\.log)"
    source: generic
    annotations: 
      log.source: nginx
```
  
With the above configuration, any Cloudtrail and ELB logs will be shipped to Dynatrace parsed and with an added 'environment: dev' attribute. The second rule is telling the forwarder to forward any logs coming from S3 keys prefixed with `nginx/` and ending with `.log` as generic text logs and add an annotation `log.source`: `nginx`. With that, you can then use [Dynatrace log processing](https://www.dynatrace.com/support/help/how-to-use-dynatrace/log-monitoring/acquire-log-data/log-processing) and define a rule that parses any logs with the attribute log.source: nginx at ingest time.

## Forwarding large log files to Dynatrace

The `dynatrace-aws-platform-monitoring-s3-log-forwarder` solution is able to handle large log files as data is streamed in chunks from Amazon S3 and then processed and forwarded to Dynatrace. Even if the solution is able to do this with very low memory footprint, allocating low memory to the function means also low CPU and bandwidth resources and your Lambda function. Depending on the size and volume of logs you're forwarding, Lambda execution may timeout while processing (the default configured Lambda execution timeout configuration is 300 seconds). For more information on how AWS Lambda allocates compute power, refer to the AWS Lambda [documentation](https://docs.aws.amazon.com/lambda/latest/operatorguide/computing-power.html).

The SAM template deploys the forwarder with the following default parameters that you can modify to suit your needs:

* `LambdaFunctionMemorySize`: 256 MB  --> At 1,769 MB, a function has the equivalent of one vCPU (one vCPU-second of credits per second).
* `MaximumLambdaConcurrency`: 30  --> Maximum number of Lambda functions executing concurrently
* `LambdaSQSMessageBatchSize`: 4  --> Number of log messages processed per Lambda execution (for smaller files you can increase it, for very large files you can decrease it)
* `LambdaMaximumExecutionTime`: 300  --> Maximum execution time in seconds of the AWS Lambda function, you can increase this up to 900
* `SQSVisibilityTimeout`: 420  --> SQS message invisibility time once received. This value should be larger than the LambdaMaximumExecutionTime to avoid more than one Lambda function processing the same log file (note however that SQS provides at-least-once delivery)
* `SQSLongPollingMaxSeconds`: 20  --> Time to wait while polling the SQS queue for messages
* `MaximumSQSMessageRetries`: 3  --> Maximum number of times the forwarder retries processing a log file if it fails before sending the S3 Object created notification to the DLQ
* `CreateS3NotificationsSNSTopic`: false --> Set to "true" to create an SNS topic for receiving S3 Object Created notifications (useful for fan-out architectures)
