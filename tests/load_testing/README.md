# Load Testing

This package generates log files and uploads them to S3 to load test the S3 log forwarder pipeline (S3 → SQS → Lambda).

## Prerequisites

- Python 3.8+
- AWS credentials configured (e.g. via `aws configure`, environment variables, or an IAM role)
- An S3 bucket that triggers the forwarder pipeline

## Setup

Install dependencies from within the `load_testing` directory:

```bash
pip install -r requirements.txt
```

## Configuration

Edit `load_test_config.yaml`:

```yaml
duration-sec: 600               # Test duration in seconds
max-log-file-size-mb: 75        # Maximum size of each generated log file
upload-threads: 5               # Number of concurrent S3 upload threads
log-interval-sec: 60            # Time window length in seconds
files-per-interval: 10          # Number of files to upload per time window
file-types:                     # Which log formats to generate
  - jsonl
  - json_array
  - alb
tier-count: 8                   # Number of file-size tiers (tier 1 = max-log-file-size-mb, each tier halves the size)
tier-weights:                   # Sampling weight per tier (must have exactly tier-count entries)
  - 1
  - 2
  - 4
  - 6
  - 7
  - 20
  - 35
  - 25
```

| Key                     | Description                                                                                         | Default              |
|-------------------------|-----------------------------------------------------------------------------------------------------|----------------------|
| `duration-sec`          | Test duration in seconds                                                                            | `60`                 |
| `max-log-file-size-mb`  | Maximum size per log file in MB (tier 1)                                                            | `10`                 |
| `upload-threads`        | Number of concurrent S3 upload threads                                                              | `4`                  |
| `log-interval-sec`      | Time window length in seconds; the runner submits `files-per-interval` files then sleeps until the window ends | `1.0`   |
| `files-per-interval`    | Number of files to submit per `log-interval-sec` window                                             | `1`                  |
| `file-types`            | List of log formats to generate: `jsonl`, `json_array`, `alb`                                       | all three            |
| `tier-count`            | Number of file-size tiers; tier *n* has size `max-log-file-size-mb / 2^(n-1)`                      | `8`                  |
| `tier-weights`          | Relative sampling weight for each tier (largest first); must have exactly `tier-count` entries      | equal weights        |

## Running the Load Test

Run from within the `load_testing` directory:

```bash
cd tests/load_testing
python load_test_runner.py --s3-bucket <bucket-name> [options]
```

### Options

| Argument                | Description                                                                                                                             | Default       |
|-------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|---------------|
| `--s3-bucket`           | **(Required)** S3 bucket to upload log files to                                                                                        | —             |
| `--s3-prefix`           | S3 key prefix for uploaded files                                                                                                        | `load-test/`  |
| `--threads`             | Number of parallel upload threads                                                                                                       | from config   |
| `--files-per-interval`  | Number of files to upload per `log-interval-sec` window                                                                                 | from config   |
| `--dry-run`             | Skip S3 upload; save files locally instead                                                                                              | `False`       |
| `--dry-run-output-dir`  | Directory to save files in dry-run mode (default: auto-created temp dir)                                                               | —             |
| `--reuse-templates`     | Reuse existing template files from `log_templates/` if present; generate only missing ones. By default templates are always regenerated. | `False`      |

### Examples

**Basic run against a real S3 bucket** (uses duration from `load_test_config.yaml`):

```bash
python load_test_runner.py --s3-bucket my-log-bucket
```

**Custom S3 prefix:**

```bash
python load_test_runner.py --s3-bucket my-log-bucket --s3-prefix perf-tests/run1/
```

**Dry run — generate files locally without uploading:**

```bash
python load_test_runner.py --s3-bucket my-log-bucket --dry-run
```

**Reuse previously generated templates (faster startup):**

```bash
python load_test_runner.py --s3-bucket my-log-bucket --reuse-templates
```

**Dry run with a specific output directory:**

```bash
python load_test_runner.py --s3-bucket my-log-bucket --dry-run --dry-run-output-dir /tmp/load-test-output
```

## Log File Types

The runner cycles through the file types listed in `file-types` and uploads them with S3 keys that match the corresponding built-in Lambda processing rules:

| Type         | Format                        | Lambda rule triggered   |
|--------------|-------------------------------|-------------------------|
| `jsonl`      | Uncompressed JSON stream      | AppFabric rule          |
| `json_array` | Gzip-compressed JSON array    | CloudTrail rule         |
| `alb`        | Gzip-compressed ALB access log | ALB rule               |

Content is generated by `generate_log_files.py` (JSON types) and `simulate_alb_logs.py` (ALB).

## Output

At the end of the run a summary is printed:

```text
Load test complete.
  Files uploaded   : 60
  Total data       : 420.00 MB
  Duration         : 60.3s
  Actual throughput: 6.97 MB/s (0.408 GB/min)

  File type       Files    Total size    Avg size
  ------------  ------  ------------  ----------
  jsonl             20    140.00 MB     7.00 MB
  json_array        20    140.00 MB     7.00 MB
  alb               20    140.00 MB     7.00 MB
  ------------  ------  ------------  ----------
  Total             60    420.00 MB
```
