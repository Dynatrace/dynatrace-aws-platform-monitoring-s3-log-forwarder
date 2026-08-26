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

### How versions are tracked

Layer version numbers are a **per-region, per-layer-name counter** in AWS — they are not synchronized across regions. Publishing to 29 regions does not guarantee they all land on the same version number. Versions diverge whenever:

* a publish fails in some regions but succeeds in others;
* you re-publish to a subset of regions with `--regions`;
* AWS adds a region, which starts at version 1 while the others are further along.

`Mappings.LayerArns` in `template.yaml` therefore stores a **fully-qualified, versioned ARN per region and architecture**, and the publish script rewrites only the entries for the regions it actually published to. Regions left untouched keep their previous ARN.

The script reports this explicitly after each run, so watch for:

* `WARNING: N region(s) not published to in this run` — those regions still point at their previous version. Expected when using `--regions`; worth investigating otherwise.
* `WARNING: N region(s) are missing an ARN for one architecture` — deployments in those regions will fail until you publish the other architecture too.

### Skip automatic file updates

By default, after a successful publish the script automatically updates the `Mappings.LayerArns` block in `template.yaml`. To skip this update, pass `--no-update-files`:

```bash
./scripts/publish_layer.sh dist/layer.zip --no-update-files
```

### Export the published ARNs

`--arns-output <file>` writes one `region=arn` pair per line for every region successfully published to. This is how the release workflow hands results between jobs: `release-s3` runs on a fresh checkout and so does not inherit the template edits made by the publish jobs, and a single version number cannot represent a per-region result.

```bash
./scripts/publish_layer.sh dist/layer.zip --arns-output layer-arns-x86.txt
```

To apply such a file to a template later:

```bash
python3 scripts/update_layer_arns.py --template template.yaml --arch-key x86 < layer-arns-x86.txt
```

### ARN validation

Before writing anything, `update_layer_arns.py` checks every ARN it is given: the
ARN must be a well-formed Lambda layer ARN, its region must match the region it is
being filed under, its version suffix must be a positive integer, and its layer
name must carry the `-arm64` suffix if and only if `--arch-key arm64` was passed.
Any problem aborts the run with a non-zero exit and leaves the template untouched.

That last check is the one that matters most in CI: it catches the two
`layer-arns-*.txt` files being crossed, which would otherwise silently pin arm64
ARNs under `x86:` keys and only surface as a deployment failure.

### If granting public access fails

If `publish-layer-version` succeeds but `add-layer-version-permission` fails, the layer version **already exists** and has consumed a version number in that region. Do not re-run the publish for that region — that burns another version and pushes it further out of step. The script prints a ready-to-run `add-layer-version-permission` command for the exact version that was created; use that instead.

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

Note the `LayerVersionArn` from the output, then set it as the `x86` or `arm64` entry for that
region under `Mappings.LayerArns` in `template.yaml`. Each region has its own entry — update the
one for the region you published to, and remember to grant public access:

```bash
aws lambda add-layer-version-permission \
    --layer-name dynatrace-aws-platform-monitoring-s3-log-forwarder \
    --version-number <version> \
    --statement-id allow-all-accounts \
    --principal '*' \
    --action lambda:GetLayerVersion
```

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
