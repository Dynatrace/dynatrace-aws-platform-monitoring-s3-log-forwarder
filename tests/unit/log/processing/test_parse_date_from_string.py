# Copyright 2026 Dynatrace LLC

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#      https://www.apache.org/licenses/LICENSE-2.0

#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import os
import unittest

os.environ['LOG_FORWARDER_CONFIGURATION_LOCATION'] = 'local'
os.environ['DEPLOYMENT_NAME'] = 'test'

from log.processing.log_processing_rule import parse_date_from_string


class TestParseDateFromStringEpoch(unittest.TestCase):

    def test_epoch_seconds_valid(self):
        result = parse_date_from_string("1677665646")
        self.assertIsNotNone(result)
        self.assertIn("2023-03-01", result)

    def test_epoch_milliseconds_valid(self):
        result = parse_date_from_string("1677665646000")
        self.assertIsNotNone(result)
        self.assertIn("2023-03-01", result)

    def test_epoch_protocol_field_6(self):
        # Protocol number 6 (TCP) — epoch 1970-01-01T00:00:06Z → outside plausibility window
        self.assertIsNone(parse_date_from_string("6"))

    def test_epoch_port_field_443(self):
        # Destination port 443 — epoch 1970-01-01T00:07:23Z → outside plausibility window
        self.assertIsNone(parse_date_from_string("443"))

    def test_epoch_account_id_012345678901(self):
        # 12-digit AWS account ID treated as epoch seconds → year ~2361 → outside plausibility window
        self.assertIsNone(parse_date_from_string("012345678901"))

    def test_epoch_20_digit_string_no_exception(self):
        # Very large value causes OSError/OverflowError in fromtimestamp — must not propagate
        self.assertIsNone(parse_date_from_string("12345678901234567890"))

    def test_epoch_zero(self):
        # Unix epoch zero → 1970 → outside plausibility window
        self.assertIsNone(parse_date_from_string("0"))


class TestParseDateFromStringISO(unittest.TestCase):

    def test_iso_with_tz(self):
        result = parse_date_from_string("2022-09-08T08:26:04Z")
        self.assertIsNotNone(result)
        self.assertIn("2022-09-08", result)

    def test_iso_without_tz(self):
        result = parse_date_from_string("2022-09-27T17:10:23")
        self.assertIsNotNone(result)
        self.assertIn("2022-09-27", result)

    def test_iso_with_microseconds(self):
        result = parse_date_from_string("2022-09-27T15:28:18.612792Z")
        self.assertIsNotNone(result)
        self.assertIn("2022-09-27", result)

    def test_s3_access_log_timestamp(self):
        result = parse_date_from_string("06/Feb/2019:00:00:38 +0000")
        self.assertIsNotNone(result)
        self.assertIn("2019-02-06", result)

    def test_msk_timestamp_with_comma_milliseconds(self):
        result = parse_date_from_string("2023-02-20 17:10:36,845")
        self.assertIsNotNone(result)
        self.assertIn("2023-02-20", result)


class TestParseDateFromStringRedshift(unittest.TestCase):

    def test_redshift_iso_format(self):
        result = parse_date_from_string("2026-06-01T08:59:05Z")
        self.assertIsNotNone(result)
        self.assertIn("2026-06-01", result)

    def test_redshift_legacy_format(self):
        # RFC 2822-style without timezone; assumed UTC by the plausibility check
        result = parse_date_from_string("Tue, 21 Feb 2023 16:58:20")
        self.assertIsNotNone(result)
        self.assertIn("2023", result)


class TestParseDateFromStringUnparseable(unittest.TestCase):

    def test_dash(self):
        # Common AWS placeholder for missing fields
        self.assertIsNone(parse_date_from_string("-"))

    def test_tcp(self):
        # Protocol name string
        self.assertIsNone(parse_date_from_string("tcp"))

    def test_ip_address(self):
        self.assertIsNone(parse_date_from_string("10.0.1.5"))

    def test_eni_id(self):
        # ENI id — fuzzy parsing extracts implausible year 456 → outside window
        self.assertIsNone(parse_date_from_string("eni-0abc123def456"))

    def test_empty_string(self):
        self.assertIsNone(parse_date_from_string(""))

    def test_accept_string(self):
        self.assertIsNone(parse_date_from_string("ACCEPT"))


if __name__ == '__main__':
    unittest.main()
