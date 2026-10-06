# Dynatrace AWS Platform Monitoring S3 Log Forwarder — Customer Self-Service Runbook

Self-diagnosable and self-fixable issues for the `dynatrace-aws-platform-monitoring-s3-log-forwarder` (Lambda + SQS, deployed with CloudFormation). Work through the section that matches your symptom before raising a support ticket.

Throughout this runbook, `<STACK_NAME>` is the name of your main forwarder CloudFormation stack.

---

## 1. CloudFormation Deployment Fails

### 1a. Missing `iam:PassRole` permission

**Symptom:** CloudFormation stack creation fails with an error mentioning `iam:PassRole`.

**Cause:** The IAM role used to run the deployment does not have `iam:PassRole` permission, required to pass an execution role to the Lambda function.

**Fix:** Add to the IAM role/user running the deployment, scoped to the forwarder's Lambda execution role:

```json
{
  "Effect": "Allow",
  "Action": "iam:PassRole",
  "Resource": "arn:aws:iam::<account-id>:role/<stack-name>-QueueProcessingFunctionRole-*",
  "Condition": {
    "StringEquals": { "iam:PassedToService": "lambda.amazonaws.com" }
  }
}
```

If you deploy with the `IamRolePath` parameter, include the path in the role ARN (`role/<iam-role-path>/<stack-name>-QueueProcessingFunctionRole-*`). The deploying identity needs the other IAM, Lambda, SQS, SSM and related permissions too — see [iam_permissions.md](iam_permissions.md) for the complete list.

---

### 1b. "Already exists" errors (SQS queues, event source mapping)

**Symptom:** Stack creation fails with an error saying a resource already exists — for example the queue `<STACK_NAME>-S3NotificationsQueue` or `<STACK_NAME>-S3NotificationsDLQ`, or a Lambda event source mapping.

**Cause:** The queues have fixed names derived from the stack name. A queue with that name left over from an earlier deployment blocks stack creation, and AWS does not allow re-using a deleted queue name for about a minute. A manually created event source mapping for the forwarder's queue and function causes the same kind of error.

**Fix:**

1. **AWS Console → SQS** — look for `<STACK_NAME>-S3NotificationsQueue` and `<STACK_NAME>-S3NotificationsDLQ`. If they belong to a deleted or failed deployment and you no longer need them, delete them. If you deleted them just now, wait about 60 seconds
2. **AWS Console → Lambda → Additional Resources → Event Source Mappings** — delete mappings that point to the `<STACK_NAME>-S3NotificationsQueue` queue and were not created by the stack
3. Wait until the resources are fully deleted, then re-run the CloudFormation deployment

---

### 1c. Other deployment errors — check CloudFormation events

**Symptom:** Stack creation or update fails (`CREATE_FAILED`, `UPDATE_FAILED`, `ROLLBACK_COMPLETE`) with an error not covered above.

**Fix:** The failure reason is in the stack events. Check it before raising a support ticket.

**AWS Console:**

1. **CloudFormation → Stacks → your stack → Events**
2. Look for the event labeled **Likely root cause** (the label is shown in the console only) and read its **Status reason**. See [Determine the root cause for CloudFormation stack failures](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/determine-root-cause-for-stack-failures.html)
3. The forwarder deploys several stacks — check the failed stack itself and any nested stack it reports

**AWS CLI:**

List only the failed events of the latest operation (requires a recent AWS CLI v2):

```bash
aws cloudformation describe-events \
  --stack-name <STACK_NAME> \
  --filters FailedEvents=true \
  --query 'OperationEvents[].{Time:Timestamp,Resource:LogicalResourceId,Type:ResourceType,Status:ResourceStatus,Reason:ResourceStatusReason}' \
  --output table
```

Alternatively, list failed events with `describe-stack-events`. This includes failures from earlier operations: identify the time window of the failed create/update in the stack events and consider only failures in that window. Within that operation, read from the oldest failure (the CLI has no root cause label; later failures are usually rollback side effects).

```bash
aws cloudformation describe-stack-events \
  --stack-name <STACK_NAME> \
  --query 'reverse(StackEvents[?contains(ResourceStatus, `FAILED`)].{Time:Timestamp,Resource:LogicalResourceId,Status:ResourceStatus,Reason:ResourceStatusReason})' \
  --output table
```

If a stack was already deleted, use its stack ID (`arn:aws:cloudformation:...`) instead of the name. Include the failed event's resource, status and reason when you raise a support ticket.

---

### 1d. Deployment is rejected before resources are created

| Error | Cause and fix |
|-------|---------------|
| `InsufficientCapabilities` / "requires capabilities" | The deploy command must include `--capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND` (the template uses the SAM transform). Use the exact command from [deployment_guide.md](deployment_guide.md). |
| Resource or role names too long | The stack name must be **at most 47 characters** (see the note in the deployment guide). Use a shorter `<STACK_NAME>`. |
| Parameter validation error on `DynatraceEnvironmentURL` | Use `https://<tenant-id>.apps.dynatrace.com` — `https://` followed by the host name only, no path or trailing `/`. |
| Parameter validation error on the token parameters | Provide **exactly one** of `DynatraceApiKeySecretsManagerSecret` (a full secret ARN) or `DynatraceApiKeySSMParameter` (a path starting with `/`). See section 3. |
| Access denied when creating the IAM role | If your organization requires roles under a path, set `IamRolePath` (must start and end with `/`) — see [advanced_deployments.md](advanced_deployments.md#iam-role-path). |
| `AccessDenied` on other actions | The deploying identity lacks permissions — compare with [iam_permissions.md](iam_permissions.md). |

---

## 2. Lambda Errors / No Logs Ingested

The notification flow is: S3 object created → EventBridge rule, SNS topic or direct S3 notification → SQS queue `<STACK_NAME>-S3NotificationsQueue` → Lambda. Start with the [Lambda logs](#lambda-logs) and the SQS queue metrics (section 7). If the queue never receives messages, the problem is in the notification wiring (2b, 2c). If messages arrive but nothing is ingested, check 2a and 2d–2g, then sections 3–5.

### 2a. Messages are dropped: unsupported message format or extra triggers

**Symptom:** The [Lambda logs](#lambda-logs) show one of:

- `Dropping message <id>, unsupported notification type`
- `Dropping message, body is not valid JSON`
- `Dropping message <id>, no S3 object creation notifications found`
- `Received invalid event (missing or invalid "Records" field)`

**Cause:** The Lambda must be fed only by its SQS queue, with messages in one of the three supported formats: S3 → EventBridge → SQS, S3 → SNS → SQS, or S3 → SQS directly. Typical causes are an extra trigger added to the Lambda function (for example a direct S3 trigger — its events carry no SQS message body), non-S3 messages sent to the queue, or an EventBridge rule/target that rewrites the event (for example with an input transformer).

**Fix:**

1. **AWS Console → Lambda → your function → Configuration → Triggers** — only the SQS trigger for `<STACK_NAME>-S3NotificationsQueue` should be present. Remove any other trigger
2. Make sure nothing else sends messages to the queue, and that the notification setup follows [deployment_guide.md](deployment_guide.md#step-6-wire-up-s3-bucket-notifications) without modified event payloads

---

### 2b. S3 notifications do not reach the SQS queue

**Symptom:** No logs forwarded; the SQS queue `<STACK_NAME>-S3NotificationsQueue` receives no messages.

**Fix:** Check the `NotificationType` parameter of your stack (**CloudFormation → your stack → Parameters**) and verify the matching setup. Details: [deployment_guide.md](deployment_guide.md#step-6-wire-up-s3-bucket-notifications).

| `NotificationType` | What to check |
|--------------------|---------------|
| `EventBridge` (default) | **EventBridge notifications are enabled on the bucket** (**S3 → your bucket → Properties → Amazon EventBridge → Edit → On**), and the bucket is listed in `GrantReadPermissionToBuckets` or has a per-bucket configuration stack deployed (the stack's EventBridge rule only matches those buckets). Repeat for every source bucket |
| `SNS` | The topic ARN is in `S3NotificationsSNSTopicArns`; the topic policy allows `s3.amazonaws.com` to publish; the topic is subscribed to the SQS queue; bucket `Object Created` notifications publish to the topic; if the topic uses a customer-managed KMS key, its key policy allows S3 |
| `Direct SQS` | The bucket's `Object Created` notification targets the queue ARN, the bucket is listed in `GrantReadPermissionToBuckets` (the queue policy only allows those buckets) and is in the **same region** as the forwarder |
| `None` | No notification is wired — configure one and redeploy |

The queue ARN is in the stack outputs and in SSM Parameter Store at `/dynatrace/s3-log-forwarder/<STACK_NAME>/sqs-queue-arn`.

---

### 2c. S3 bucket in a different region or AWS account

**Symptom:** No logs from buckets that are not in the forwarder's own region and account.

**Cause:** A standard deployment handles buckets in the forwarder's own region and account. `Direct SQS` supports same-region buckets only, and the standard EventBridge setup does not support cross-account buckets.

**Fix:** Set up cross-region/cross-account forwarding — [advanced_deployments.md](advanced_deployments.md). Checklist:

1. Main stack: `EnableCrossRegionCrossAccountForwarding=true`; for other accounts also `AwsAccountsToReceiveLogsFrom` — the list **replaces** the previous value, so include all accounts
2. Deploy `eventbridge-cross-region-or-account-forward-rules.yaml` in the bucket's region/account and enable EventBridge notifications on the bucket
3. Deploy `dynatrace-aws-s3-log-forwarder-s3-bucket-configuration.yaml` in the forwarder's region with `S3BucketIsCrossRegionOrCrossAccount=true`
4. Cross-account only: the bucket policy allows the forwarder's Lambda role `s3:GetObject`, and the bucket has ACLs disabled
5. Add an explicit log forwarding rule for the bucket unless a `default` rule exists — see 2e

---

### 2d. Lambda cannot read the S3 objects (AccessDenied, KMS)

**Symptom:** The [Lambda logs](#lambda-logs) show `Error processing message <id>` with `AccessDenied` for S3 `GetObject`, or a KMS access denied / decryption error. The message is retried and eventually lands in the DLQ (section 5).

**Fix:**

1. The bucket must be listed in `GrantReadPermissionToBuckets`, or have a per-bucket configuration stack deployed — both grant the Lambda role `s3:GetObject`. Cross-account buckets also need the bucket policy from 2c
2. If objects are encrypted with a customer-managed KMS key (SSE-KMS), add the key ARN to the `GrantDecryptToKmsKeyArns` stack parameter (grants the Lambda role `kms:Decrypt`), and make sure the key policy allows the Lambda role to use the key. Update the stack — see [update_guide.md](update_guide.md) and [cloudformation_parameters.md](cloudformation_parameters.md)

---

### 2e. Objects are dropped: no matching log forwarding rule

**Symptom:** The [Lambda logs](#lambda-logs) show `Dropping object. s3://<bucket>/<key> doesn't match any forwarding rule`; the metric `DroppedObjectsNotMatchingFwdRules` is above 0.

**Cause:** By default a catch-all `default` rule forwards every object. With custom forwarding rules, objects are discarded if their bucket has no explicit rule set and no matching `default` rule, or if their key matches none of their bucket's explicit rules. The `default` rule set is considered only for buckets without explicit rules. The rule `prefix` is a **regular expression** matched from the start of the S3 key (it need not match the entire key), and rules are evaluated in order (the first match wins).

**Fix:** For AppConfig-managed rules, add or correct the rule in `LogForwardingRulesHostedConfiguration` in `dynatrace-aws-s3-log-forwarder-appconfig.yaml` and redeploy the AppConfig stack. If the bucket has explicit rules, correct those rules or add a catch-all with `prefix: .*` to that bucket's rule set; a `default` catch-all only covers buckets without explicit rules. Do not edit the rules in the AppConfig console (the next CloudFormation deployment overwrites them). The change applies within about a minute. See [log_forwarding.md](log_forwarding.md) and [advanced_deployments.md](advanced_deployments.md#custom-log-forwarding-and-processing-rules-via-appconfig).

---

### 2f. Logs are ingested twice

**Cause:** When `NotificationType=EventBridge`, a bucket listed in `GrantReadPermissionToBuckets` is matched by the main stack's EventBridge rule. If that bucket also has a per-bucket configuration stack, both rules can send the same notification to the queue. More than one notification path configured on the same bucket has the same effect.

**Fix:** Use one notification path per bucket. For `EventBridge` prefix filtering, leave the bucket out of `GrantReadPermissionToBuckets` and use the per-bucket stack. For `Direct SQS` or `SNS`, use native prefix/suffix filters on the bucket notifications and retain the required read permissions (and, for `Direct SQS`, the bucket's entry in `GrantReadPermissionToBuckets` for the queue policy). See [advanced_deployments.md](advanced_deployments.md#configuring-s3-buckets-with-prefix-filtering).

---

### 2g. Objects are dropped: not readable as UTF-8 text

**Symptom:** The [Lambda logs](#lambda-logs) show `Error decoding log object. Log contains non-UTF-8 characters. Dropping object s3://<bucket>/<key>`; the metric `DroppedObjectsDecodingErrors` is above 0.

**Cause:** The forwarder processes UTF-8 text and JSON logs. Gzipped logs are supported only if the key ends in `.gz` or the object has `Content-Encoding: gzip` metadata. Binary formats are not text logs.

**Fix:** Have the log source deliver plain text/JSON (or gzip with a `.gz` extension), see [log_processing.md](log_processing.md). For AWS services, choose a supported output format (see 4b).

---

## 3. Dynatrace Token Issues (Secrets Manager or SSM Parameter Store)

The forwarder authenticates to Dynatrace with a **platform token** (scope `data-acquisition:logs:ingest`). The token is stored in **one** of two places, chosen at deployment:

| Option | Stack parameter | What it must contain |
|--------|-----------------|----------------------|
| AWS Secrets Manager | `DynatraceApiKeySecretsManagerSecret` | The full **ARN** of a secret whose value is JSON: `{"dt.platform_token":"<token>"}` |
| SSM Parameter Store | `DynatraceApiKeySSMParameter` | The **path** (starting with `/`) of a `SecureString` parameter whose value is the token, e.g. `/dynatrace/s3-log-forwarder/<STACK_NAME>/api-key` |

Check which one your stack uses: **CloudFormation → your stack → Parameters** — exactly one of the two is set. Follow the matching steps below. The Lambda reads the token with a cache of up to 2 minutes, so after changing it, wait about 2 minutes (or until the next Lambda invocation after that) before re-testing. See [deployment_guide.md](deployment_guide.md#step-2-provide-the-dynatrace-platform-token) for the original setup steps.

---

### 3a. Wrong secret ARN / parameter path, wrong format, or no access

**Symptom:** The [Lambda logs](#lambda-logs) show one of:

- Secrets Manager: `AccessDeniedException ... secretsmanager:GetSecretValue`, `ResourceNotFoundException`, or `KeyError: 'dt.platform_token'`
- SSM: `AccessDeniedException ... ssm:GetParameter` or `ParameterNotFound`

**Cause:** Common mistakes:

- **Secrets Manager:** the stack parameter is the secret *name* or the token itself instead of the full **ARN**; the secret is plain text instead of JSON; or the JSON key is not exactly `dt.platform_token`.
- **SSM:** the parameter path is missing the leading `/`, the stack parameter holds the raw token instead of the path, or the parameter is `String` instead of `SecureString`.
- The Lambda role can read only the one secret/parameter given in the stack parameter. If you moved or recreated the token elsewhere, the stack parameter must be updated to match.

**Fix — Secrets Manager:**

```bash
# Verify the secret exists and the JSON has the key dt.platform_token (prints key names only, not the token)
aws secretsmanager get-secret-value --secret-id "<SECRET_ARN>" \
  --query SecretString --output text | jq 'keys'

# Create or correct the secret value
aws secretsmanager put-secret-value --secret-id "<SECRET_ARN>" \
  --secret-string '{"dt.platform_token":"<your-dynatrace-platform-token>"}'
```

**Fix — SSM Parameter Store:**

```bash
aws ssm put-parameter \
  --name "/dynatrace/s3-log-forwarder/<STACK_NAME>/api-key" \
  --type SecureString \
  --value "<your-dynatrace-platform-token>" \
  --overwrite
```

If the ARN or path itself was wrong, update the stack with the correct value of the parameter you use, keeping all other parameters unchanged and the other token parameter empty (the two are mutually exclusive) — see [update_guide.md](update_guide.md).

---

### 3b. Token invalid, expired, revoked, or missing the required scope

**Symptom:** The [Lambda logs](#lambda-logs) show `There was a HTTP 401 error posting batch ...` or `HTTP 403 ...` (the response text from Dynatrace follows), and logs stop arriving in Dynatrace.

**Fix:**

1. In Dynatrace, check that the platform token is still valid (not expired or revoked) and has the **`data-acquisition:logs:ingest`** scope — see [platform tokens](https://docs.dynatrace.com/docs/manage/identity-access-management/access-tokens-and-oauth-clients/platform-tokens)
2. If not, create a new platform token with that scope
3. Store the new token in the place your stack uses (no redeploy needed):
   - Secrets Manager: `aws secretsmanager put-secret-value` as shown in 3a
   - SSM: `aws ssm put-parameter ... --overwrite` as shown in 3a
4. Wait about 2 minutes for the token cache to expire, then check the Lambda logs again

---

### 3c. Secret or parameter encrypted with a customer-managed KMS key

**Symptom:** Lambda cannot read the secret or parameter; a KMS-related access error (`kms:Decrypt`, `AccessDeniedException`) appears in the [Lambda logs](#lambda-logs).

**Fix:** Grant the Lambda execution role `kms:Decrypt` on the KMS key that encrypts the secret (Secrets Manager) or the parameter (SSM). Make sure the key policy also allows the role to use the key.

---

### 3d. Lambda cannot reach Dynatrace (network)

**Symptom:** The [Lambda logs](#lambda-logs) show connection timeouts or SSL/TLS errors when posting to Dynatrace, or timeouts when reading the token from Secrets Manager/SSM.

**Fix:**

1. Verify `DynatraceEnvironmentURL` (format in 1d)
2. If the Lambda runs in a VPC (`LambdaSubnetIds` / `LambdaSecurityGroupId` are set), the security group must allow outbound access to the Dynatrace ingest endpoint, and the subnets need a route to it (for example a NAT gateway). The Lambda also needs to reach AWS APIs (S3, SQS, SSM or Secrets Manager), for example through NAT or VPC endpoints
3. If a TLS-inspecting proxy with a custom CA sits in the path, see `VerifyLogEndpointSSLCerts` in [cloudformation_parameters.md](cloudformation_parameters.md) (only for this case)

---

## 4. Log Processing Rules Misconfiguration

### 4a. Custom processing rule is invalid or not applied

**Symptom:** Logs arrive without the expected parsing/enrichment. The [Lambda logs](#lambda-logs) show `Log processing rule N is invalid` (N is the position of the rule in the configuration, counting from 0), or `No matching log processing rule for custom.<name>. Defaulting to 'generic' log ingestion.`

**Cause:**

- An invalid rule (for example a missing required field or an invalid `source`) is skipped and logged; the other rules still load. Malformed YAML syntax aborts loading of the whole custom rule set.
- AppConfig-hosted processing rules require `LogForwarderConfigurationLocation=aws-appconfig`; bundled local custom rules also load when it is `local`. A processing rule with `source: custom` is selected by a forwarding rule with `source: custom` whose `source_name` equals the processing rule `name`. Custom configuration can also supplement or override `aws` and `generic` processing rules — see [log_processing.md](log_processing.md) for the supported sources.

**Fix:**

1. Edit the rules in `LogProcessingRulesHostedConfiguration` in `dynatrace-aws-s3-log-forwarder-appconfig.yaml`, then redeploy the AppConfig stack (not in the AppConfig console — direct edits are overwritten). The change applies within about a minute
2. Start with a minimal valid rule and add fields incrementally. Required fields are `name`, `source`, `known_key_path_pattern` and `log_format`:

   ```yaml
   ---
   name: my-rule
   source: custom
   known_key_path_pattern: "^.*$"
   log_format: text
   ```

3. Reference it from a forwarding rule with `source: custom` and `source_name: my-rule`

See [log_processing.md](log_processing.md) for the full rule reference and [log_forwarding.md](log_forwarding.md) for forwarding rules.

---

### 4b. AWS service logs arrive without AWS attributes (ingested as generic)

**Symptom:** Logs arrive in Dynatrace but without parsed fields or attributes such as `aws.account.id` or `aws.arn`. The [Lambda logs](#lambda-logs) show `Couldn't find a matching aws processing rule for <key>. Defaulting to generic ingestion.`

**Cause:** The forwarder recognizes AWS services from service-specific S3 key patterns. Many use `AWSLogs/...`, while AppFabric uses `AWSAppFabric/...` and S3 server access logs use date-prefixed filenames. Many built-in rules, including CloudTrail and ALB, support custom prefixes. Keys that match no built-in rule fall back to generic ingestion; unsupported output formats may instead match a rule but fail processing or attribute extraction. For example, CloudFront v2 JSON/Parquet fall back to generic handling, while `Raw` still matches the v2 rule and produces unreliable parsing. Some attributes cannot be extracted by design (for example `aws.arn` for CloudTrail and AppFabric, `aws.account.id` and `aws.arn` for legacy CloudFront logs, `aws.account.id` for S3 server access logs). CloudFront standard logging (v2) requires the **W3C / Plain** output format, no custom bucket prefix, and the default `recordFields` with `date` and `time` first.

**Fix:**

1. Deliver logs with a key layout and output format supported by the service's built-in rule. For CloudFront v2 specifically, do not configure a custom bucket prefix — see [log_processing.md](log_processing.md#cloudfront-standard-logging-v2-requirements)
2. Check the list of supported AWS services in the [README](../README.md#supported-aws-services); support for additional services and formats arrives with new releases, so update to the latest release ([update_guide.md](update_guide.md))
3. For layouts the built-in rules do not cover, ingest as `generic` and parse in Dynatrace, or add a custom processing rule with `attribute_extraction_from_key_name` (see 4a and [log_processing.md](log_processing.md))

---

## 5. Throttling, Timeouts and the Dead Letter Queue

Each S3 notification is attempted up to `MaximumSQSMessageRetries` times (default 3). After that the message moves to the dead letter queue `<STACK_NAME>-S3NotificationsDLQ`. See [resiliency.md](resiliency.md).

### 5a. Dynatrace rejects or throttles requests

**Symptom:** One of these entries in the [Lambda logs](#lambda-logs), with the matching metric (section 7):

| Log message | Metric | What to do |
|-------------|--------|------------|
| `Throttled by Dynatrace. Exhausted retry attempts...` (`DynatraceThrottlingException`) | `DynatraceHTTP429Throttled` | Lower `MaximumLambdaConcurrency` (default 30) and reduce the volume forwarded (forwarding rules / prefix filtering, sections 2e and 2f). Transient throttling clears on its own — the messages are retried or redriven (5c) |
| `Batch ... rejected by Dynatrace (payload too large)` | `DynatraceHTTP413PayloadTooLarge` | Payload limits are set by `DynatraceLogIngestPayloadMaxLength` and `DynatraceLogIngestContentMaxLength` ([cloudformation_parameters.md](cloudformation_parameters.md)) |
| `There was a HTTP 401/403 error posting batch...` | `DynatraceHTTPErrors` | Token problem — section 3 |

If it persists after these steps, raise a support ticket with the log excerpt.

### 5b. Lambda runs out of time on large files

**Symptom:** The [Lambda logs](#lambda-logs) show `Unable to process log file s3://... with remaining Lambda execution time`; the metric `NotEnoughExecutionTimeRemainingErrors` is above 0.

**Fix:** Update the stack parameters ([cloudformation_parameters.md](cloudformation_parameters.md), [log_forwarding.md](log_forwarding.md#forwarding-large-log-files-to-dynatrace)):

- Increase `LambdaMaximumExecutionTime` (default 300 s, maximum 900 s) and `LambdaFunctionMemorySize` (more memory also means more CPU and network bandwidth)
- Decrease `LambdaSQSMessageBatchSize` (default 4) for very large files
- Keep `SQSVisibilityTimeout` (default 420 s) greater than `LambdaMaximumExecutionTime`

### 5c. Messages in the dead letter queue

**Symptom:** You receive an e-mail from the CloudWatch alarm `<STACK_NAME>-MessagesInDLQ` (sent only if `NotificationsEmail` is set), or the DLQ shows messages.

**Fix:**

1. Find the cause in the [Lambda logs](#lambda-logs) — search for `Error processing message` — and fix it (sections 2–5)
2. **AWS Console → SQS → `<STACK_NAME>-S3NotificationsDLQ` → Start DLQ redrive** to the source queue, so the forwarder re-processes the messages — see [Configuring a dead-letter queue redrive](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-configure-dead-letter-queue-redrive.html)

The DLQ keeps messages for **1 day**, and the main queue keeps unprocessed notifications for **12 hours**. Expired messages cannot be redriven, so fix problems promptly.

---

## 6. Security Vulnerabilities (CVEs)

Before raising a support ticket:

1. Check [security.dynatrace.com](https://security.dynatrace.com) — the CVE may already be documented
2. Check [GitHub releases](https://github.com/dynatrace/dynatrace-aws-platform-monitoring-s3-log-forwarder/releases) for a patched version
3. Update to the latest release by following [update_guide.md](update_guide.md)

---

## 7. General Debugging Tips

<!-- markdownlint-disable-next-line MD033 -->
**<a id="lambda-logs"></a>Where to find the Lambda logs:**

The forwarder's Lambda function (`QueueProcessingFunction` in the stack) writes its logs to **Amazon CloudWatch Logs**, in the log group `/aws/lambda/<function-name>` in the same AWS account and region as the stack. The function name is generated by CloudFormation (it looks like `<STACK_NAME>-QueueProcessingFunction-<random suffix>`).

1. **AWS Console → CloudFormation → your stack → Resources → `QueueProcessingFunction`** — the *Physical ID* is the function name
2. **AWS Console → CloudWatch → Logs → Log groups** → open `/aws/lambda/<function-name>` (or use the **Monitoring** tab of the Lambda function → **View CloudWatch logs**)
3. Open the most recent log stream, or use **Search all log streams** / **Logs Insights** to filter for `ERROR`, `Exception` or a specific S3 object key

From the CLI:

```bash
# Get the function name
FUNCTION_NAME=$(aws cloudformation describe-stack-resource \
  --stack-name <STACK_NAME> \
  --logical-resource-id QueueProcessingFunction \
  --query 'StackResourceDetail.PhysicalResourceId' --output text)

# Show the last hour of logs and keep following new entries
aws logs tail "/aws/lambda/${FUNCTION_NAME}" --since 1h --follow

# Show only errors from the last 24 hours
aws logs tail "/aws/lambda/${FUNCTION_NAME}" --since 24h --filter-pattern "?ERROR ?Exception"
```

If the log group does not exist, the function has not run yet (no messages reached the SQS queue — see section 2) or the Lambda execution role cannot write to CloudWatch Logs.

**Enable debug logging:**

1. **AWS Console → Lambda → your function → Configuration → Environment variables**
2. Set `LOGGING_LEVEL` to `DEBUG` (or set the `LambdaLoggingLevel` CloudFormation parameter, so a redeploy doesn't reset it)
3. Reproduce the problem and read the new entries in the [Lambda log group](#lambda-logs); reset to `INFO` afterwards to avoid extra CloudWatch Logs costs

**Use the CloudWatch monitoring dashboard:**

The forwarder can deploy a CloudWatch dashboard named `<STACK_NAME>-monitoring-dashboard-<REGION>`. It shows log files processed, Dynatrace API responses (including throttling), processing and ingestion times, SQS queue and DLQ message counts, Lambda executions, and Lambda logs, which makes it the quickest way to see where logs stop flowing.

1. Find the dashboard link in the **Outputs** tab of the main stack (`CloudWatchDashboardURL`), or open **AWS Console → CloudWatch → Dashboards**
2. Or get the link from the CLI:

```bash
aws cloudformation describe-stacks \
  --stack-name <STACK_NAME> \
  --query 'Stacks[0].Outputs[?OutputKey==`CloudWatchDashboardURL`].OutputValue' \
  --output text
```

**The dashboard may be disabled.** It is deployed only when the `DeployCloudWatchMonitoringDashboard` CloudFormation parameter is `true` (the default). If it is `false`, the `CloudWatchDashboardURL` output is missing and no dashboard exists.

- To enable it, update the stack with `DeployCloudWatchMonitoringDashboard=true` (see [update_guide.md](update_guide.md) and [cloudformation_parameters.md](cloudformation_parameters.md)). Keep all other parameter values unchanged.
- Without the dashboard you can still see the same data: the forwarder publishes its metrics to the CloudWatch namespace `dynatrace-aws-platform-monitoring-s3-log-forwarder` (dimension `deployment` = your stack name) regardless of this setting. Browse them in **CloudWatch → Metrics**, and check the SQS queue and DLQ metrics directly. See [function_metrics.md](function_metrics.md) for the metric list.

**Metrics worth checking** (namespace `dynatrace-aws-platform-monitoring-s3-log-forwarder`, dimension `deployment` = `<STACK_NAME>`):

| Metric | Meaning | See |
|--------|---------|-----|
| `LogFilesProcessed` | Files ingested successfully | — |
| `LogProcessingFailures` | Processing failures (retried, then DLQ) | 5c |
| `DroppedObjectsNotMatchingFwdRules` | Objects with no matching forwarding rule | 2e |
| `DroppedObjectsDecodingErrors` | Objects that are not valid UTF-8 text | 2g |
| `NotEnoughExecutionTimeRemainingErrors` | Lambda timed out on a file | 5b |
| `DynatraceHTTP429Throttled`, `DynatraceHTTPErrors` | Dynatrace rejected requests | 5a, 3b |

For the SQS queue `<STACK_NAME>-S3NotificationsQueue` and the DLQ, look at `NumberOfMessagesSent` and `ApproximateNumberOfMessagesVisible`.

**Verify end-to-end flow:**

1. Upload a test file to a source S3 bucket that is configured for forwarding
2. Check SQS queue metrics — message count should rise then drop (processed)
3. Check the [Lambda log group](#lambda-logs) in CloudWatch Logs (`/aws/lambda/<function-name>`) for the invocation
4. Search Dynatrace for logs from that file, for example in a Notebook:

```text
fetch logs
| filter dt.da.aws.s3.bucket.name == "<BUCKET_NAME>"
| filter dt.da.aws.s3.key.name == "<OBJECT_KEY>"
```

---
