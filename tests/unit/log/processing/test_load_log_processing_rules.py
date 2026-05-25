# Copyright 2022 Dynatrace LLC

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#      https://www.apache.org/licenses/LICENSE-2.0

#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import unittest
from unittest.mock import patch
import os

os.environ['DEPLOYMENT_NAME'] = 'test'

from log.processing import log_processing_rules
from utils import aws_appconfig_extension_helpers as aws_appconfig_helpers


class TestLoadCustomRules(unittest.TestCase):

    @patch("log.processing.log_processing_rules.load_custom_rules_from_aws_appconfig")
    def test_appconfig_error_at_cold_start_falls_back_to_empty_rules(self, mock_load):
        mock_load.side_effect = aws_appconfig_helpers.ErrorAccessingAppConfig

        os.environ["LOG_FORWARDER_CONFIGURATION_LOCATION"] = "aws-appconfig"
        try:
            with self.assertLogs(level="WARNING") as cm:
                rules, version = log_processing_rules.load_custom_rules()
        finally:
            del os.environ["LOG_FORWARDER_CONFIGURATION_LOCATION"]

        self.assertEqual(rules, {})
        self.assertEqual(version, 0)
        self.assertTrue(any("cold start" in msg for msg in cm.output))
