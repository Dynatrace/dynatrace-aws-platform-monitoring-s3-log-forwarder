#!/usr/bin/env python3
"""Helper functions for generating JSON log files for load testing."""

import json
import secrets

# Lorem ipsum words for generating random content
LOREM_IPSUM_WORDS = [
    "lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing",
    "elit", "sed", "do", "eiusmod", "tempor", "incididunt", "ut", "labore",
    "et", "dolore", "magna", "aliqua", "enim", "ad", "minim", "veniam",
    "quis", "nostrud", "exercitation", "ullamco", "laboris", "nisi",
    "aliquip", "ex", "ea", "commodo", "consequat", "duis", "aute", "irure",
    "in", "reprehenderit", "voluptate", "velit", "esse", "cillum",
    "fugiat", "nulla", "pariatur", "excepteur", "sint", "occaecat",
    "cupidatat", "non", "proident", "sunt", "culpa", "qui", "officia",
    "deserunt", "mollit", "anim", "id", "est", "laborum", "test",
    "performance", "testing", "log", "message", "data", "processing",
]


LARGE_RECORD_SIZE_BYTES = 9900 * 1024  # 9900 kB
LARGE_RECORD_MIN_FILE_SIZE_MB = 10  # a file holding large records must fit at least one of them


def _generate_large_log_record() -> dict:
    """Generate a single log record of LARGE_RECORD_SIZE_BYTES (serialized with json.dumps defaults)."""
    record = {"content": "[s3-log-fwd perf test]", "large_payload": ""}
    filler_length = LARGE_RECORD_SIZE_BYTES - len(json.dumps(record))

    # Build one random chunk and repeat it, as picking millions of random words would be slow.
    chunk = " ".join(secrets.choice(LOREM_IPSUM_WORDS) for _ in range(1000))
    record["large_payload"] = (chunk * (filler_length // len(chunk) + 1))[:filler_length]
    return record


def generate_random_log_record(min_length: int = 40, max_length: int = 2048, large: bool = False) -> dict:
    """
    Generate a single log record with random attributes and content.

    Args:
        min_length: Minimum record length in bytes (default: 40)
        max_length: Maximum record length in bytes (default: 2048 = 2KB)
        large: If True, ignore min_length/max_length and generate a record of 9900 kB (default: False)

    Returns:
        A dictionary with "content" field set to "[s3-log-fwd perf test]" and up to 10 additional random attributes
        (or a single large "large_payload" attribute when large is True).
    """
    if large:
        return _generate_large_log_record()

    record = {"content": "[s3-log-fwd perf test]"}
    target_length = secrets.randbelow(max_length - min_length + 1) + min_length
    attribute_names = ["message", "data", "log_message", "details", "event_data", "context", "metadata", "info", "request", "response"]
    max_attributes = 10

    for _ in range(max_attributes):
        current_size = len(json.dumps(record, separators=(',', ':')).encode('utf-8'))

        if current_size >= target_length:
            break

        remaining_space = target_length - current_size - 50
        if remaining_space <= 10:
            break

        attr_name = "{}_{}".format(secrets.choice(attribute_names), secrets.randbelow(9999) + 1)
        word_count = min(secrets.randbelow(max(5, remaining_space // 20) - 3 + 1) + 3, 50)
        words = [secrets.choice(LOREM_IPSUM_WORDS) for _ in range(word_count)]
        record[attr_name] = " ".join(words)

    return record


def generate_jsonl_file(output_path: str, target_size_bytes: int, large_records: bool = False) -> int:
    """
    Generate a JSONL format log file.

    Args:
        output_path: Path where the log file will be created.
        target_size_bytes: Target file size in bytes.
        large_records: Use large (9900 kB) log records instead of small ones.

    Returns:
        Final size in bytes.
    """
    current_size = 0
    buffer = []
    buffer_size = 0
    max_buffer_size = 1024 * 1024  # 1MB buffer

    with open(output_path, 'w', encoding='utf-8') as f:
        while current_size < target_size_bytes:
            log_record = generate_random_log_record(large=large_records)
            json_line = json.dumps(log_record) + "\n"

            buffer.append(json_line)
            line_size = len(json_line.encode('utf-8'))
            buffer_size += line_size
            current_size += line_size

            if buffer_size >= max_buffer_size or current_size >= target_size_bytes:
                f.write(''.join(buffer))
                buffer.clear()
                buffer_size = 0

        if buffer:
            f.write(''.join(buffer))

    return current_size


def generate_json_array_file(output_path: str, target_size_bytes: int, large_records: bool = False) -> int:
    """
    Generate a JSON array format log file.

    Args:
        output_path: Path where the log file will be created.
        target_size_bytes: Target file size in bytes.
        large_records: Use large (9900 kB) log records instead of small ones.

    Returns:
        Final size in bytes.
    """
    wrapper_overhead = 14  # {"Records":[]} = 14 bytes
    current_size = wrapper_overhead
    record_separator_size = 1  # comma between records
    records = []

    while current_size < target_size_bytes:
        log_record = generate_random_log_record(large=large_records)
        record_json = json.dumps(log_record)
        record_size = len(record_json.encode('utf-8'))

        if records:
            record_size += record_separator_size

        if current_size + record_size > target_size_bytes and records:
            break

        records.append(log_record)
        current_size += record_size

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({"Records": records}, f)

    return current_size


def generate_log_file(output_path: str, size_mb: int = 1, format_type: str = 'jsonl', large_records: bool = False) -> None:
    """
    Generate a log file of specified size with JSON records.

    Args:
        output_path: Path where the log file will be created.
        size_mb: Size of the log file in megabytes (default: 1 MB).
        format_type: Output format - 'jsonl' or 'json_array' (default: 'jsonl').
        large_records: Use large (9900 kB) log records instead of small ones (default: False).
    """
    target_size_bytes = size_mb * 1024 * 1024

    if format_type == 'json_array':
        generate_json_array_file(output_path, target_size_bytes, large_records)
    else:
        generate_jsonl_file(output_path, target_size_bytes, large_records)
