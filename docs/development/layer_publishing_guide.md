# Publishing the Lambda Layer

This guide covers how to build and publish the `dynatrace-aws-platform-monitoring-s3-log-forwarder` Lambda Layer, making it available for customers to use directly via a Layer ARN.

## Prerequisites

* [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
* Docker Engine

## Step 1. Build the Lambda Layer

From the project root directory, run:

```bash
./scripts/build_docker.sh layer dist/layer.zip          # x86_64 (default)
./scripts/build_docker.sh layer dist/layer.zip arm64    # arm64
```

## Step 2. Publish the Layer

Lambda Layers are regional — a layer must be published in each region where customers will deploy. The publish script handles this automatically and grants public access to each published layer version.

Both architectures must be published separately. Run the script once per architecture.

### Publish to all commercial regions

```bash
./scripts/publish_layer.sh dist/layer.zip               # x86_64 (default)
./scripts/publish_layer.sh dist/layer.zip --arch arm64  # arm64
```

### Publish to specific regions

```bash
./scripts/publish_layer.sh dist/layer.zip --regions us-east-1,eu-west-1,eu-central-1
./scripts/publish_layer.sh dist/layer.zip --arch arm64 --regions us-east-1,eu-west-1,eu-central-1
```

The script will output the `LayerVersionArn` for each region and automatically update the `Mappings.LayerArns` block in `template.yaml`.

### Skip automatic file updates

By default, after a successful publish the script automatically updates the `Mappings.LayerArns` block in `template.yaml`. To skip this update, pass `--no-update-files`:

```bash
./scripts/publish_layer.sh dist/layer.zip --no-update-files
```

### Manual publishing

Alternatively, you can publish manually:

```bash
# x86_64
aws lambda publish-layer-version \
    --layer-name dynatrace-aws-platform-monitoring-s3-log-forwarder \
    --zip-file fileb://dist/layer.zip \
    --compatible-runtimes python3.14 \
    --compatible-architectures x86_64 \
    --description "Dynatrace AWS S3 Log Forwarder (x86_64)"

# arm64
aws lambda publish-layer-version \
    --layer-name dynatrace-aws-platform-monitoring-s3-log-forwarder-arm64 \
    --zip-file fileb://dist/layer.zip \
    --compatible-runtimes python3.14 \
    --compatible-architectures arm64 \
    --description "Dynatrace AWS S3 Log Forwarder (arm64)"
```

Note the `LayerVersionArn` from the output — update `template.yaml` manually with this ARN.

## Step 3. Release the updated templates

The publish script has already updated `template.yaml` with the new Layer ARNs. Release these updated files so customers can update to the new version.

## Publishing a new version

When releasing an update:

1. Build x86_64: `./scripts/build_docker.sh layer dist/layer.zip`
2. Publish x86_64: `./scripts/publish_layer.sh dist/layer.zip`
3. Build arm64: `./scripts/build_docker.sh layer dist/layer.zip arm64`
4. Publish arm64: `./scripts/publish_layer.sh dist/layer.zip --arch arm64`
5. Release the updated YAML templates

> **Note:** Each `publish-layer-version` call creates a new immutable version. Previous versions remain available until explicitly deleted. Customers can pick up the new version by redeploying with the updated `template.yaml`.
