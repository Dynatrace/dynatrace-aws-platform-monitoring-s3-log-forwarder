# Resiliency

The `dynatrace-aws-platform-monitoring-s3-log-forwarder` will attempt up to 3 times to forward a log object to Dynatrace. In the scenario where a log file has failed to be processed more than 3 times, the SQS message with the object details will be redriven to the Dead Letter Queue, where it will be retained for up to 1 day.

The SAM template configures a CloudWatch alarm to trigger whenever messages make it to the Dead Letter Queue. When this happens, you'll receive a notification e-mail (you can change this for any valid Amazon SNS target).

You can take a look at the messages on the Dead Letter Queue, as well as the dynatrace-s3-log-forwarder logs to determine the cause of the error. If it's a retriable error due to a temporary situation, you can redrive the messages in the DLQ so they're re-processed by the log forwarder. More information [here](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-configure-dead-letter-queue-redrive.html).

You can customize the solution behavior using the following CloudFormation parameters when deploying or updating the stack:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MaximumSQSMessageRetries` | `3` | Maximum number of processing attempts before a message is sent to the DLQ |
| `SQSVisibilityTimeout` | `420` | Seconds a message is hidden after being received. Must be greater than `LambdaMaximumExecutionTime` |
| `SQSLongPollingMaxSeconds` | `20` | Maximum seconds to wait for messages during long polling |

```bash
aws cloudformation deploy --stack-name ${STACK_NAME} \
    --template-file template.yaml \
    --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
    --parameter-overrides \
        MaximumSQSMessageRetries=5 \
        SQSVisibilityTimeout=600
```

**Note:** `SQSVisibilityTimeout` must be greater than `LambdaMaximumExecutionTime` (default 300s) to avoid the same message being processed multiple times.
