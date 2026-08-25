# Required AWS IAM permissions

This page lists the AWS IAM permissions your identity (user or role) must hold to deploy and manage the `dynatrace-aws-platform-monitoring-s3-log-forwarder`.

The ARN patterns below use the following placeholders:

- `<stack-name>` — the value you set for `STACK_NAME` in Step 1 of the deployment guide
- `<region>` — the AWS region you deploy to (e.g. `us-east-1`)
- `<account-id>` — your 12-digit AWS account ID

## Main stack (`template.yaml`)

### Always required

**CloudFormation** — `arn:aws:cloudformation:<region>:<account-id>:stack/<stack-name>*`

```text
cloudformation:CreateStack
cloudformation:UpdateStack
cloudformation:DeleteStack
cloudformation:DescribeStacks
cloudformation:DescribeStackEvents
cloudformation:DescribeStackResource
cloudformation:DescribeStackResources
cloudformation:ListStackResources
cloudformation:GetTemplate
cloudformation:GetTemplateSummary
cloudformation:CreateChangeSet
cloudformation:DescribeChangeSet
cloudformation:ExecuteChangeSet
cloudformation:DeleteChangeSet
```

**CloudFormation SAM transform** — `arn:aws:cloudformation:*:aws:transform/Serverless-2016-10-31`

```text
cloudformation:CreateChangeSet
```

**Lambda function** — `arn:aws:lambda:<region>:<account-id>:function:<stack-name>-QueueProcessingFunction-*`

```text
lambda:CreateFunction
lambda:GetFunction
lambda:UpdateFunctionConfiguration
lambda:DeleteFunction
lambda:TagResource
lambda:ListTags
lambda:PutFunctionConcurrency
```

**Lambda event source mapping** — `*`

```text
lambda:CreateEventSourceMapping
lambda:GetEventSourceMapping
lambda:ListEventSourceMappings
lambda:UpdateEventSourceMapping
lambda:DeleteEventSourceMapping
```

**SQS** — `arn:aws:sqs:<region>:<account-id>:<stack-name>-S3NotificationsQueue` and `arn:aws:sqs:<region>:<account-id>:<stack-name>-S3NotificationsDLQ`

```text
sqs:CreateQueue
sqs:GetQueueUrl
sqs:GetQueueAttributes
sqs:SetQueueAttributes
sqs:DeleteQueue
sqs:ListQueueTags
```

**SNS** — `arn:aws:sns:<region>:<account-id>:<stack-name>-Alarms`

```text
sns:CreateTopic
sns:GetTopicAttributes
sns:SetTopicAttributes
sns:DeleteTopic
sns:Subscribe
sns:GetSubscriptionAttributes
sns:Unsubscribe
sns:TagResource
sns:ListTagsForResource
```

**EventBridge rule** — `arn:aws:events:<region>:<account-id>:rule/<stack-name>-s3-notifications`

```text
events:PutRule
events:DescribeRule
events:DeleteRule
events:PutTargets
events:RemoveTargets
events:ListTargetsByRule
events:TagResource
events:ListTagsForResource
```

**CloudWatch alarms** — `arn:aws:cloudwatch:<region>:<account-id>:alarm:<stack-name>-MessagesInDLQ`

```text
cloudwatch:PutMetricAlarm
cloudwatch:DescribeAlarms
cloudwatch:DeleteAlarms
cloudwatch:TagResource
cloudwatch:ListTagsForResource
```

**CloudWatch dashboard** — `arn:aws:cloudwatch:<region>:<account-id>:dashboard/<stack-name>-monitoring-dashboard-<region>`

```text
cloudwatch:PutDashboard
cloudwatch:GetDashboard
cloudwatch:DeleteDashboards
```

**IAM role** — `arn:aws:iam::<account-id>:role/<stack-name>-QueueProcessingFunctionRole-*` or (if you use `IamRolePath`) `arn:aws:iam::<account-id>:role/<iam-role-path>/<stack-name>-QueueProcessingFunctionRole-*`

```text
iam:CreateRole
iam:GetRole
iam:DeleteRole
iam:AttachRolePolicy
iam:DetachRolePolicy
iam:PutRolePolicy
iam:GetRolePolicy
iam:DeleteRolePolicy
iam:ListRolePolicies
iam:ListAttachedRolePolicies
iam:TagRole
iam:ListRoleTags
iam:PassRole  # condition: iam:PassedToService = lambda.amazonaws.com
```

**SSM Parameter Store** — `arn:aws:ssm:<region>:<account-id>:parameter/dynatrace/s3-log-forwarder/<stack-name>/*`

```text
ssm:PutParameter
ssm:DeleteParameter
```

### Conditional permissions

| Parameter | Required permissions | Resource |
|-----------|---------------------|----------|
| `DynatraceApiKey` | `secretsmanager:CreateSecret` `secretsmanager:DescribeSecret` `secretsmanager:PutSecretValue` `secretsmanager:DeleteSecret` `secretsmanager:TagResource` | `arn:aws:secretsmanager:<region>:<account-id>:secret:dynatrace/s3-log-forwarder/<stack-name>/api-key*` |
| `CreateS3NotificationsSNSTopic=true` | `kms:CreateKey` `kms:DescribeKey` `kms:EnableKeyRotation` `kms:GetKeyPolicy` `kms:GetKeyRotationStatus` `kms:ListResourceTags` `kms:PutKeyPolicy` `kms:ScheduleKeyDeletion` `kms:TagResource` | `*` |
| `CreateS3NotificationsSNSTopic=true` | `sns:CreateTopic` `sns:GetTopicAttributes` `sns:SetTopicAttributes` `sns:DeleteTopic` `sns:Subscribe` `sns:GetSubscriptionAttributes` `sns:Unsubscribe` `sns:TagResource` `sns:ListTagsForResource` | `arn:aws:sns:<region>:<account-id>:<stack-name>-S3Notifications` |
| `EnableCrossRegionCrossAccountForwarding=true` | `events:CreateEventBus` `events:DescribeEventBus` `events:DeleteEventBus` `events:PutPermission` `events:RemovePermission` | `arn:aws:events:<region>:<account-id>:event-bus/<stack-name>-cross-region-cross-account-s3-events` |

## Per-bucket stack (`dynatrace-aws-s3-log-forwarder-s3-bucket-configuration.yaml`)

Deploy this template once per S3 bucket when you need prefix-level filtering. It creates an EventBridge rule and attaches an inline IAM policy to the Lambda execution role created by the main stack.

> [!NOTE]
>
> `<main-stack-name>` below refers to the `STACK_NAME` you used when deploying `template.yaml` — the value passed to the `DynatraceAwsS3LogForwarderStackName` parameter.

**EventBridge rule** — `arn:aws:events:<region>:<account-id>:rule/<main-stack-name>-*`

```text
events:PutRule
events:DescribeRule
events:DeleteRule
events:PutTargets
events:RemoveTargets
events:ListTargetsByRule
events:TagResource
events:ListTagsForResource
```

**IAM role** — `arn:aws:iam::<account-id>:role/<main-stack-name>-QueueProcessingFunctionRole-*`

```text
iam:GetRole
iam:GetRolePolicy
iam:PutRolePolicy
iam:DeleteRolePolicy
```

## AppConfig stack (`dynatrace-aws-s3-log-forwarder-appconfig.yaml`)

Deploy this template when you want to manage log forwarding and processing rules at runtime via AWS AppConfig without redeploying Lambda.

**AppConfig** — `arn:aws:appconfig:<region>:<account-id>:application/*`

```text
appconfig:CreateApplication
appconfig:GetApplication
appconfig:DeleteApplication
appconfig:CreateConfigurationProfile
appconfig:GetConfigurationProfile
appconfig:DeleteConfigurationProfile
appconfig:CreateDeploymentStrategy
appconfig:GetDeploymentStrategy
appconfig:DeleteDeploymentStrategy
appconfig:CreateEnvironment
appconfig:GetEnvironment
appconfig:DeleteEnvironment
appconfig:CreateHostedConfigurationVersion
appconfig:GetHostedConfigurationVersion
appconfig:DeleteHostedConfigurationVersion
appconfig:StartDeployment
appconfig:GetDeployment
appconfig:TagResource
appconfig:ListTagsForResource
```

**IAM role** — `arn:aws:iam::<account-id>:role/<main-stack-name>-QueueProcessingFunctionRole-*`

```text
iam:GetRole
iam:GetRolePolicy
iam:PutRolePolicy
iam:DeleteRolePolicy
```

**SSM Parameter Store** — `arn:aws:ssm:<region>:<account-id>:parameter/dynatrace/s3-log-forwarder/<main-stack-name>/*`

```text
ssm:PutParameter
ssm:DeleteParameter
```

## Cross-region/account EventBridge stack (`eventbridge-cross-region-or-account-forward-rules.yaml`)

Deploy this template in each source region or account when centralizing log forwarding across regions or accounts. It creates an EventBridge rule and an IAM role that EventBridge assumes to forward events to the main stack's event bus.

**EventBridge rule** — `arn:aws:events:<source-region>:<source-account-id>:rule/dt-s3-log-fwd-to-*`

```text
events:PutRule
events:DescribeRule
events:DeleteRule
events:PutTargets
events:RemoveTargets
events:ListTargetsByRule
events:TagResource
events:ListTagsForResource
```

**IAM role** — `arn:aws:iam::<source-account-id>:role/<cross-region-stack-name>*`

```text
iam:CreateRole
iam:GetRole
iam:DeleteRole
iam:PutRolePolicy
iam:GetRolePolicy
iam:DeleteRolePolicy
iam:TagRole
iam:ListRoleTags
iam:PassRole  # condition: iam:PassedToService = events.amazonaws.com
```
