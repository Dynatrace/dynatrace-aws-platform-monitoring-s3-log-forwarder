#!/usr/bin/env python3
import argparse
import gzip
import os
import random
import shutil
import string
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import boto3
import yaml

from generate_log_files import generate_log_file as _generate_log_file
from simulate_alb_logs import generate_alb_log_file


CONFIG_FILE_PATH = os.path.join(os.path.dirname(__file__), "load_test_config.yaml")
LOG_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "log_templates")

_thread_local = threading.local()

# Fake AWS identifiers used to construct S3 keys that match built-in Lambda processing rules.
_FAKE_ACCOUNT_ID = "012345678910"
_FAKE_REGION = "us-east-1"
_ALNUM = string.ascii_lowercase + string.digits


def _random_alnum(n: int) -> str:
    return "".join(random.choice(_ALNUM) for _ in range(n))


def _make_s3_key(prefix: str, file_type: str) -> str:
    """Return an S3 key whose path triggers the correct built-in Lambda processing rule.

    - alb       → ALB rule        (log_format: text,        gzip-compressed)
    - jsonl     → AppFabric rule  (log_format: json_stream, uncompressed)
    - json_array → CloudTrail rule (log_format: json,       gzip-compressed)
    """
    now = datetime.utcnow()
    y, m, d = now.strftime("%Y"), now.strftime("%m"), now.strftime("%d")
    hh, mi = now.strftime("%H"), now.strftime("%M")
    ymd = f"{y}{m}{d}"
    hhmm = f"{hh}{mi}"

    if file_type == "alb":
        return (
            f"{prefix}AWSLogs/{_FAKE_ACCOUNT_ID}/elasticloadbalancing/{_FAKE_REGION}/"
            f"{y}/{m}/{d}/"
            f"{_FAKE_ACCOUNT_ID}_elasticloadbalancing_{_FAKE_REGION}_"
            f"app.load-test-alb.{_random_alnum(16)}_"
            f"{ymd}T{hhmm}Z_10.0.0.1_{_random_alnum(8)}.log.gz"
        )
    elif file_type == "jsonl":
        ts_ms = int(time.time() * 1000)
        return (
            f"{prefix}AWSAppFabric/AuditLog/OCSF/JSON/LOADTEST/"
            f"{uuid.uuid4()}/{uuid.uuid4()}/"
            f"{y}{m}{d}/"
            f"AuditLog-{ts_ms}-{uuid.uuid4()}"
        )
    elif file_type == "json_array":
        return (
            f"{prefix}AWSLogs/{_FAKE_ACCOUNT_ID}/CloudTrail/{_FAKE_REGION}/"
            f"{y}/{m}/{d}/"
            f"{_FAKE_ACCOUNT_ID}_CloudTrail_{_FAKE_REGION}_"
            f"{ymd}T{hhmm}Z_{_random_alnum(16)}.json.gz"
        )
    else:
        raise ValueError(f"Unknown file type: {file_type!r}")


def _gzip_file(src: str, dst: str) -> None:
    """Compress src into dst as gzip, then remove src."""
    with open(src, "rb") as f_in, gzip.open(dst, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    os.remove(src)


def parse_args():
    parser = argparse.ArgumentParser(description="Load test runner for S3/SQS/Lambda pipeline")
    parser.add_argument("--s3-bucket", required=True, help="Target S3 bucket name")
    parser.add_argument("--s3-prefix", default="load-test/", help="S3 key prefix for uploaded files")
    parser.add_argument("--threads", type=int, default=None, help="Number of parallel upload threads (default: from config)")
    parser.add_argument("--dry-run", action="store_true", help="Save generated files to a local directory instead of uploading to S3")
    parser.add_argument("--dry-run-output-dir", default=None, help="Directory to save files in dry-run mode (default: a new temp directory)")
    parser.add_argument("--reuse-templates", action="store_true", help="Reuse existing template files from log_templates/ if present, generating only missing ones. By default, templates are always regenerated.")
    parser.add_argument("--files-per-interval", type=int, default=None, help="Number of files to upload per log-interval-sec window (default: from config)")
    return parser.parse_args()


def load_config() -> dict:
    with open(CONFIG_FILE_PATH, "r") as f:
        return yaml.safe_load(f)


def _get_s3_client():
    """Return a thread-local boto3 S3 client, creating one on first use per thread."""
    if not hasattr(_thread_local, "s3_client"):
        _thread_local.s3_client = boto3.client("s3")
    return _thread_local.s3_client


def generate_alb_log_file_for_test(output_path: str, size_mb: float):
    """Generate a gzip-compressed ALB access log file scaled to size_mb."""
    alb_path = output_path if output_path.endswith(".gz") else output_path + ".gz"
    # Each ALB log entry is ~350 bytes compressed; scale record count to hit the target compressed size.
    record_count = max(1, int(size_mb * 1024 * 1024 / 350))
    generate_alb_log_file(alb_path, record_count=record_count)


def upload_to_s3(local_path: str, bucket: str, prefix: str, file_type: str) -> str:
    s3_client = _get_s3_client()
    filename = os.path.basename(local_path)
    key = _make_s3_key(prefix, file_type)
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"  [{ts}] Uploading {filename:<23}  {os.path.getsize(local_path) / 1024 / 1024:.2f} MB  → s3://{bucket}/{key}")
    s3_client.upload_file(local_path, bucket, key)
    return key


def _output_dir_context(dry_run: bool, dry_run_output_dir: str):
    if dry_run:
        if dry_run_output_dir:
            os.makedirs(dry_run_output_dir, exist_ok=True)
            return dry_run_output_dir, lambda: None
        tmp = tempfile.mkdtemp()
        print(f"  Dry-run output   : {tmp}")
        return tmp, lambda: None
    ctx = tempfile.TemporaryDirectory()
    return ctx.name, ctx.cleanup


_ALL_FILE_TYPES = ["jsonl", "json_array", "alb"]


def _generate_template(tier: int, tier_count: int, size_mb: float, reuse: bool, file_types: list) -> dict:
    """Generate or reuse template files for the requested file types for a single tier.

    Returns a dict mapping file_type -> path for each type in file_types.
    """
    paths = {}

    if "jsonl" in file_types:
        path = os.path.join(LOG_TEMPLATES_DIR, f"template_jsonl_tier{tier}.log")
        if reuse and os.path.exists(path):
            print(f"  [{tier}/{tier_count}] JSONL       {size_mb:.1f} MB — reusing existing template")
        else:
            print(f"  [{tier}/{tier_count}] JSONL       {size_mb:.1f} MB — generating...")
            _generate_log_file(path, size_mb=int(max(1, round(size_mb))), format_type="jsonl")
        paths["jsonl"] = path

    if "json_array" in file_types:
        path = os.path.join(LOG_TEMPLATES_DIR, f"template_json_array_tier{tier}.json.gz")
        if reuse and os.path.exists(path):
            print(f"  [{tier}/{tier_count}] JSON Array  {size_mb:.1f} MB — reusing existing template")
        else:
            print(f"  [{tier}/{tier_count}] JSON Array  {size_mb:.1f} MB — generating...")
            tmp = path + ".tmp"
            _generate_log_file(tmp, size_mb=int(max(1, round(size_mb))), format_type="json_array")
            _gzip_file(tmp, path)
        paths["json_array"] = path

    if "alb" in file_types:
        path = os.path.join(LOG_TEMPLATES_DIR, f"template_alb_tier{tier}.log.gz")
        if reuse and os.path.exists(path):
            print(f"  [{tier}/{tier_count}] ALB        {size_mb:.1f} MB — reusing existing template")
        else:
            print(f"  [{tier}/{tier_count}] ALB        {size_mb:.1f} MB — generating...")
            generate_alb_log_file_for_test(path, size_mb)
        paths["alb"] = path

    return paths


def _pregen_templates(max_file_size_mb: float, reuse_templates: bool, file_types: list, tier_count: int) -> dict:
    """Build a dict mapping (tier, type) → path for the requested file types."""
    os.makedirs(LOG_TEMPLATES_DIR, exist_ok=True)
    print("Loading/generating template files...")
    templates = {}
    for tier in range(1, tier_count + 1):
        tier_paths = _generate_template(tier, tier_count, max_file_size_mb / (2 ** (tier - 1)), reuse_templates, file_types)
        for ft, path in tier_paths.items():
            templates[(tier, ft)] = path
    print("Templates ready.\n")
    return templates


def _generate_file(i: int, workdir: str, templates: dict, file_types: list, tier_count: int, tier_weights: list) -> tuple:
    """Copy a pre-generated template and return (path, file_type) of the copy.

    File type cycles through the enabled file_types list.
    """
    tier = random.choices(range(1, tier_count + 1), weights=tier_weights, k=1)[0]
    file_type = file_types[i % len(file_types)]
    src = templates[(tier, file_type)]
    if file_type == "json_array":
        ext = ".json.gz"
    elif file_type == "jsonl":
        ext = ".log"
    else:
        ext = ".log.gz"
    dst = os.path.join(workdir, f"load_test_{i:05d}{ext}")
    shutil.copy2(src, dst)
    return dst, file_type


def _upload_or_save(actual_path: str, file_type: str, dry_run: bool, bucket: str, prefix: str):
    """Upload to S3 or save locally (dry-run). Runs in a worker thread."""
    size_mb = os.path.getsize(actual_path) / 1024 / 1024
    if dry_run:
        ts = datetime.utcnow().strftime("%H:%M:%S")
        filename = os.path.basename(actual_path)
        print(f"  [{ts}] [DRY RUN] Saved: {filename:<23}  {size_mb:.2f} MB  ({file_type})")
    else:
        upload_to_s3(actual_path, bucket, prefix, file_type)


def _print_config(max_file_size_mb, duration_seconds, log_interval_sec, dry_run, num_threads, file_types, tier_count, tier_weights, files_per_interval):
    print("Load test configuration:")
    print(f"  Max file size    : {max_file_size_mb} MB")
    print(f"  Duration         : {duration_seconds}s")
    print(f"  Log interval     : {log_interval_sec}s ({files_per_interval} file(s) every {log_interval_sec}s)")
    print(f"  Upload threads   : {num_threads}")
    print(f"  File types       : {', '.join(file_types)}")
    print(f"  Tiers            : {tier_count}  weights: {tier_weights}")
    if dry_run:
        print(f"  Mode             : DRY RUN (files saved locally)")
    print()


def _print_summary(uploaded: int, total_mb: float, total_elapsed: float, type_stats: dict):
    actual_throughput_mb_s = total_mb / total_elapsed if total_elapsed > 0 else 0
    print()
    print("Load test complete.")
    print(f"  Files uploaded   : {uploaded}")
    print(f"  Total data       : {total_mb:.2f} MB")
    print(f"  Duration         : {total_elapsed:.1f}s")
    print(f"  Actual throughput: {actual_throughput_mb_s:.2f} MB/s ({actual_throughput_mb_s * 60 / 1024:.3f} GB/min)")
    print()
    print(f"  {'File type':<12}  {'Files':>6}  {'Total size':>12}  {'Avg size':>10}")
    print(f"  {'-'*12}  {'-'*6}  {'-'*12}  {'-'*10}")
    for file_type, stats in type_stats.items():
        count = stats["count"]
        tmb = stats["total_mb"]
        avg = tmb / count if count else 0.0
        print(f"  {file_type:<12}  {count:>6}  {tmb:>9.2f} MB  {avg:>7.2f} MB")
    print(f"  {'-'*12}  {'-'*6}  {'-'*12}  {'-'*10}")
    print(f"  {'Total':<12}  {uploaded:>6}  {total_mb:>9.2f} MB")


def _run_loop(duration_seconds, log_interval_sec, workdir, templates, dry_run, bucket, prefix, num_threads, file_types, tier_count, tier_weights, files_per_interval):
    """Main upload loop. Returns (total_mb, uploaded, total_elapsed, type_stats)."""
    total_mb = 0.0
    uploaded = 0
    i = 0
    start_time = time.time()
    pending_futures = []  # list of (future, file_mb, file_type)
    type_stats = {ft: {"count": 0, "total_mb": 0.0} for ft in file_types}

    executor = ThreadPoolExecutor(max_workers=num_threads)
    try:
        while True:
            elapsed = time.time() - start_time
            if elapsed >= duration_seconds:
                break

            loop_start = time.time()

            for _ in range(files_per_interval):
                try:
                    path, file_type = _generate_file(i, workdir, templates, file_types, tier_count, tier_weights)
                    file_mb = os.path.getsize(path) / 1024 / 1024
                    future = executor.submit(_upload_or_save, path, file_type, dry_run, bucket, prefix)
                    pending_futures.append((future, file_mb, file_type))
                except Exception as e:
                    print(f"[ERROR] File {i}: {e}", file=sys.stderr)
                i += 1

            # Harvest any futures that have already completed (non-blocking)
            remaining = []
            for f, mb, ft in pending_futures:
                if f.done():
                    try:
                        f.result()
                        total_mb += mb
                        uploaded += 1
                        type_stats[ft]["count"] += 1
                        type_stats[ft]["total_mb"] += mb
                    except Exception as e:
                        print(f"[ERROR] Upload failed: {e}", file=sys.stderr)
                else:
                    remaining.append((f, mb, ft))
            pending_futures = remaining

            sleep_time = log_interval_sec - (time.time() - loop_start)
            if sleep_time > 0:
                time.sleep(sleep_time)

        if pending_futures:
            for f, _, _ in pending_futures:
                f.cancel()
            print(f"\nCancelled {len(pending_futures)} in-flight upload(s).")
    finally:
        executor.shutdown(wait=False)

    total_elapsed = time.time() - start_time
    return total_mb, uploaded, total_elapsed, type_stats


def run_load_test(bucket: str, prefix: str, config: dict, dry_run: bool = False, dry_run_output_dir: str = None, reuse_templates: bool = False, num_threads: int = None, files_per_interval: int = None):
    max_file_size_mb = config.get("max-log-file-size-mb", 10)
    duration_seconds = config.get("duration-sec", 60)
    log_interval_sec = config.get("log-interval-sec", 1.0)
    if num_threads is None:
        num_threads = config.get("upload-threads", 4)
    if files_per_interval is None:
        files_per_interval = config.get("files-per-interval", 1)
    file_types = config.get("file-types", _ALL_FILE_TYPES)
    invalid = [ft for ft in file_types if ft not in _ALL_FILE_TYPES]
    if invalid:
        raise ValueError(f"Unknown file type(s) in config: {invalid}. Valid types: {_ALL_FILE_TYPES}")
    if not file_types:
        raise ValueError("file-types must not be empty")
    tier_count = config.get("tier-count", 8)
    tier_weights = config.get("tier-weights", [1] * tier_count)
    if len(tier_weights) != tier_count:
        raise ValueError(f"tier-weights has {len(tier_weights)} entries but tier-count is {tier_count}; they must match")
    _print_config(max_file_size_mb, duration_seconds, log_interval_sec, dry_run, num_threads, file_types, tier_count, tier_weights, files_per_interval)

    workdir, cleanup = _output_dir_context(dry_run, dry_run_output_dir)
    try:
        templates = _pregen_templates(max_file_size_mb, reuse_templates, file_types, tier_count)
        total_mb, uploaded, total_elapsed, type_stats = _run_loop(duration_seconds, log_interval_sec, workdir, templates, dry_run, bucket, prefix, num_threads, file_types, tier_count, tier_weights, files_per_interval)
    finally:
        cleanup()

    _print_summary(uploaded, total_mb, total_elapsed, type_stats)


def main():
    args = parse_args()
    config = load_config()
    run_load_test(
        bucket=args.s3_bucket,
        prefix=args.s3_prefix,
        config=config,
        dry_run=args.dry_run,
        dry_run_output_dir=args.dry_run_output_dir,
        reuse_templates=args.reuse_templates,
        num_threads=args.threads,
        files_per_interval=args.files_per_interval,
    )


if __name__ == "__main__":
    main()
