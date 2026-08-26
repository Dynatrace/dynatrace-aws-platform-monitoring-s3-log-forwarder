#!/usr/bin/env python3

# Copyright 2026 Dynatrace LLC
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#      https://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Update the per-region Lambda Layer ARNs in the Mappings.LayerArns block.

Reads ``region=layer_version_arn`` pairs on stdin (as emitted by
publish_layer.sh) and rewrites the entry for the given architecture in each of
those regions, leaving every other region untouched. Each ARN is checked against
its region key and the target architecture before anything is written.

Layer version numbers are a per-region, per-layer-name counter in AWS and are
not synchronized across regions, so each region must carry its own
fully-qualified ARN. Updating only the regions we actually published to is what
keeps the template honest when a publish partially fails or targets a subset of
regions via --regions.

Only the region entries are rewritten; the surrounding template, including the
comments above the LayerArns key, is preserved byte-for-byte.
"""

import argparse
import re
import sys

ARCH_KEYS = ("x86", "arm64")

# A published layer ARN, split on ":", has exactly these eight fields:
#   arn:<partition>:lambda:<region>:<account>:layer:<name>:<version>
ARN_FIELD_COUNT = 8
# The arm64 layer is published under a separate layer name carrying this suffix.
ARM64_LAYER_SUFFIX = "-arm64"
PARTITION_RE = re.compile(r"^aws[a-z-]*$")
ACCOUNT_RE = re.compile(r"^\d{12}$")
LAYER_VERSION_RE = re.compile(r"^[1-9]\d*$")

# Indentation, in spaces, of the template.yaml keys this script reads and
# writes. Patterns use explicit ` {N}` repetition rather than runs of literal
# spaces so the widths stay readable and stay in step with the renderer.
MAP_KEY_INDENT = 2   # "  LayerArns:"
REGION_INDENT = 4    # "    us-east-1:"
ARCH_INDENT = 6      # "      x86: arn:..."


def _at_indent(width, rest):
    """Compile a pattern anchoring `rest` at exactly `width` spaces of indent."""
    return re.compile(rf"^ {{{width}}}{rest}")


MAP_KEY_RE = _at_indent(MAP_KEY_INDENT, r"LayerArns:\s*$")
REGION_RE = _at_indent(REGION_INDENT, r"([a-z0-9-]+):\s*$")
# Restricted to the known architectures on purpose: any other key at this indent
# would be parsed but silently dropped by render(), so let it fall through to the
# "unexpected line" error in parse_regions() instead.
ARCH_RE = _at_indent(ARCH_INDENT, rf"({'|'.join(ARCH_KEYS)}):\s*(\S+)\s*$")


def parse_pairs(stream):
    """Parse ``region=arn`` lines, preserving last-wins on duplicates."""
    pairs = {}
    for raw in stream:
        line = raw.strip()
        if not line:
            continue
        if "=" not in line:
            sys.exit(f"error: malformed region=arn pair: {line!r}")
        region, arn = line.split("=", 1)
        region, arn = region.strip(), arn.strip()
        if not region or not arn:
            sys.exit(f"error: malformed region=arn pair: {line!r}")
        pairs[region] = arn
    return pairs


def validate_published_arns(pairs, arch_key):
    """Reject ARNs that are malformed, or that contradict their region or arch.

    The pairs describe a publish result and reach this script through a file
    handed between CI jobs, so a truncated, garbled or crossed-over file would
    otherwise be written into the template verbatim and only surface much later
    as a deployment failure. Every problem is collected before exiting so one run
    reports the full picture.
    """
    wants_arm64 = arch_key == "arm64"
    errors = []

    for region, arn in sorted(pairs.items()):
        fields = arn.split(":")
        if len(fields) != ARN_FIELD_COUNT:
            errors.append(f"{region}: expected {ARN_FIELD_COUNT} colon-separated "
                          f"ARN fields, got {len(fields)}: {arn}")
            continue

        prefix, partition, service, arn_region, account, kind, name, version = fields

        if prefix != "arn" or not PARTITION_RE.match(partition):
            errors.append(f"{region}: not a well-formed ARN: {arn}")
        if service != "lambda" or kind != "layer":
            errors.append(f"{region}: not a Lambda layer ARN: {arn}")
        if arn_region != region:
            errors.append(f"{region}: ARN belongs to region {arn_region!r}: {arn}")
        if not ACCOUNT_RE.match(account):
            errors.append(f"{region}: {account!r} is not a 12-digit account id: {arn}")
        if name.endswith(ARM64_LAYER_SUFFIX) is not wants_arm64:
            errors.append(f"{region}: layer name {name!r} does not match "
                          f"--arch-key {arch_key}: {arn}")
        if not LAYER_VERSION_RE.match(version):
            errors.append(f"{region}: version suffix must be a positive integer: {arn}")

    if errors:
        sys.exit("error: refusing to write invalid published layer ARNs:\n  "
                 + "\n  ".join(errors))


def find_block(lines):
    """Return (key_index, end_index) bounding the LayerArns region entries."""
    start = next((i for i, l in enumerate(lines) if MAP_KEY_RE.match(l)), None)
    if start is None:
        sys.exit("error: could not find 'LayerArns:' mapping in template")

    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        # A key at the mapping's own indent or shallower ends the block.
        if len(line) - len(line.lstrip()) <= MAP_KEY_INDENT:
            end = i
            break

    # Blank lines and comments trailing the last region entry belong to whatever
    # follows the mapping, so keep them outside the rewritten range.
    while end > start + 1 and (
        not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")
    ):
        end -= 1
    return start, end


def parse_regions(lines, start, end):
    """Parse existing region -> {arch: arn} entries from the block."""
    regions = {}
    current = None
    for i in range(start + 1, end):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = REGION_RE.match(line)
        if m:
            current = m.group(1)
            regions.setdefault(current, {})
            continue
        m = ARCH_RE.match(line)
        if m and current:
            regions[current][m.group(1)] = m.group(2)
            continue
        sys.exit(f"error: unexpected line {i + 1} in LayerArns block: {line!r}")
    return regions


def render(regions):
    out = []
    for region in sorted(regions):
        out.append(f"{' ' * REGION_INDENT}{region}:")
        for arch in ARCH_KEYS:
            arn = regions[region].get(arch)
            if arn is not None:
                out.append(f"{' ' * ARCH_INDENT}{arch}: {arn}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--template", required=True)
    ap.add_argument("--arch-key", required=True, choices=ARCH_KEYS)
    args = ap.parse_args()

    published = parse_pairs(sys.stdin)
    if not published:
        print("No published ARNs on stdin — template left unchanged.")
        return 0

    validate_published_arns(published, args.arch_key)

    with open(args.template) as fh:
        text = fh.read()
    trailing_newline = text.endswith("\n")
    lines = text.split("\n")
    if trailing_newline:
        lines.pop()

    start, end = find_block(lines)
    regions = parse_regions(lines, start, end)

    known = set(regions)
    added, changed, unchanged = [], [], []
    for region, arn in sorted(published.items()):
        previous = regions.setdefault(region, {}).get(args.arch_key)
        regions[region][args.arch_key] = arn
        if region not in known:
            added.append(region)
        elif previous != arn:
            changed.append(region)
        else:
            unchanged.append(region)

    lines[start + 1:end] = render(regions)
    with open(args.template, "w") as fh:
        fh.write("\n".join(lines) + ("\n" if trailing_newline else ""))

    print(f"Updated {args.arch_key} ARNs for {len(published)} region(s) "
          f"({len(changed)} changed, {len(added)} added, {len(unchanged)} already current).")

    if added:
        print(f"  Added regions not previously in the mapping: {', '.join(added)}")

    # Regions carrying a stale ARN for this architecture, i.e. present in the
    # mapping but not covered by this publish run. These will keep pointing at
    # whatever version they were last published with.
    stale = sorted(set(regions) - set(published))
    if stale:
        print(f"  WARNING: {len(stale)} region(s) not published to in this run and left "
              f"at their previous {args.arch_key} version: {', '.join(stale)}")

    incomplete = sorted(r for r, a in regions.items() if not all(k in a for k in ARCH_KEYS))
    if incomplete:
        print(f"  WARNING: {len(incomplete)} region(s) are missing an ARN for one architecture; "
              f"deployments there will fail until both architectures are published: "
              f"{', '.join(incomplete)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
