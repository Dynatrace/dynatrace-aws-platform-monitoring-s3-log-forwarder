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
those regions, leaving every other region untouched.

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

MAP_KEY_RE = re.compile(r"^  LayerArns:\s*$")
REGION_RE = re.compile(r"^    ([a-z0-9-]+):\s*$")
ARCH_RE = re.compile(r"^      ([a-z0-9]+):\s*(\S+)\s*$")


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
        if len(line) - len(line.lstrip()) <= 2:
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
        out.append(f"    {region}:")
        for arch in ARCH_KEYS:
            arn = regions[region].get(arch)
            if arn is not None:
                out.append(f"      {arch}: {arn}")
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
