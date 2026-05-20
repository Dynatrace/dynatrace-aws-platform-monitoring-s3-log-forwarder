from datetime import datetime, timedelta
import random
import gzip
import os

entry = 'http {timestamp} app/k8s-fakealb-fakealbi-ffbc3dc280/82a34fae168ba1aa {clientip}:{client_port} {elbip}:9898 0.000 0.001 0.000 200 200 137 2886 "GET http://k8s-podinfo-podinfoi-ffbc3dc280-1325129400.us-east-1.elb.amazonaws.com:80/{path} HTTP/1.1" "curl/7.79.1" - - arn:aws:elasticloadbalancing:us-east-1:012345678910:targetgroup/k8s-fakealb-frontend-b634dbe3b4/c0bcccc5dfc7c29c "Root=1-634ea0af-3a9eec810c49366e7ba37d49" "-" "-" 1 {timestamp} "forward" "-" "-" "{backend_ip}:9898" "200" "-" "-"'

client_ips = [
    "79.156.252.12",
    "79.156.252.13",
    "79.156.12.56",
    "79.16.252.77",
    "80.1.124.12",
    "80.46.88.124",
    "156.156.52.176",
    "3.222.2.67",
    "3.23.57.13"
]

elb_ips = [
    "192.168.1.222",
    "192.168.4.56",
    "192.168.8.23"
]

backend_ips = [
    "192.168.3.12",
    "192.168.7.64",
    "192.168.9.78",
]

paths = [
    "",
    "env",
    "index.html",
    "fake/my-site.php",
    "about-us",
    "contact",
    "favicon.ico"
]


def generate_alb_log_file(output_path: str, record_count: int = 100000) -> None:
    """
    Generate a gzip-compressed ALB access log file.

    Args:
        output_path: Path where the .gz log file will be created.
        record_count: Number of log entries to generate (default: 100 000).
    """
    if os.path.dirname(output_path):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
    timestamp = datetime.utcnow()

    print(f"Generating ALB log file: {output_path} ({record_count} records)")
    with gzip.open(output_path, "wb") as f:
        for _ in range(record_count):
            timestamp += timedelta(milliseconds=random.randrange(1, 5))
            d = {
                "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "clientip": random.choice(client_ips),
                "elbip": random.choice(elb_ips),
                "backend_ip": random.choice(backend_ips),
                "client_port": random.randrange(1024, 65535),
                "path": random.choice(paths),
            }
            f.write((entry.format(**d) + "\n").encode())
    print(f"ALB log file created: {output_path}")

