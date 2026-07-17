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

import os
import unittest
from datetime import datetime
import json
import logging
import sys
from math import ceil
from unittest.mock import patch
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import responses
import boto3
from moto import mock_aws
from requests.packages.urllib3.exceptions import MaxRetryError
import log.sinks.dynatrace as dynatrace

logging.getLogger().setLevel(logging.INFO)

mock_dt_url = 'https://test.live.dynatrace.com'
mock_dt_key_parameter = '/dynatrace-s3-log-forwarder/test/api-key'

class TestDynatraceSink(unittest.TestCase):

    def test_message_truncation(self):
        dynatrace_sink = dynatrace.DynatraceSink(mock_dt_url, mock_dt_key_parameter, token_source='ssm')

        test_message = {
            'content': "x" * (dynatrace.DYNATRACE_LOG_INGEST_CONTENT_MAX_LENGTH + 20),
            'timestamp': datetime.utcnow()
        }

        dynatrace_sink.check_log_message_size_and_truncate(test_message)
        
        truncated_message_size = len(test_message['content']) - len(dynatrace.DYNATRACE_LOG_INGEST_CONTENT_MARK_TRIMMED)
        expected_message = ("x" * truncated_message_size) + dynatrace.DYNATRACE_LOG_INGEST_CONTENT_MARK_TRIMMED
        self.assertEqual(test_message['content'],expected_message)
    
    @responses.activate
    def test_exceed_max_entries_on_payload(self):
        dynatrace_sink = dynatrace.DynatraceSink(mock_dt_url, mock_dt_key_parameter, token_source='ssm')
        test_log_messages = [{'content': 'test'}] * (dynatrace.DYNATRACE_LOG_INGEST_MAX_ENTRIES_COUNT + 1)
        
        responses.add(responses.POST, dynatrace_sink.get_environment_url() + dynatrace.GENERIC_LOGS_INGEST_API_URL_SUFFIX,
                      status=204)

        for message in test_log_messages:
            dynatrace_sink.push(message)

        self.assertEqual(dynatrace_sink.get_num_of_buffered_messages(),1)

    @responses.activate
    def test_exceed_payload_size(self):
        dynatrace_sink = dynatrace.DynatraceSink(mock_dt_url, mock_dt_key_parameter, token_source='ssm')

        log_message = {'content': 'a' * (dynatrace.DYNATRACE_LOG_INGEST_CONTENT_MAX_LENGTH - 100)}

        log_message_size = sys.getsizeof(
            json.dumps(log_message).encode(dynatrace.ENCODING)) + dynatrace.COMMA_SEPARATOR_LENGTH

        num_messages_to_push = ceil(
            (dynatrace.DYNATRACE_LOG_INGEST_PAYLOAD_MAX_SIZE - dynatrace.LIST_BRACKETS_LENGTH) / log_message_size) + 1
        
        responses.add(responses.POST, dynatrace_sink.get_environment_url() + dynatrace.GENERIC_LOGS_INGEST_API_URL_SUFFIX,
                      status=204)

        for _ in range(1,num_messages_to_push):
            dynatrace_sink.push(log_message)

        self.assertEqual(dynatrace.LIST_BRACKETS_LENGTH + log_message_size,
                         dynatrace_sink.get_size_of_buffered_messages())

    @responses.activate
    @mock_aws
    def test_dynatrace_throttling(self):
        ssm_client = boto3.client("ssm", region_name="us-east-1")
        ssm_client.put_parameter(Name=mock_dt_key_parameter,Value="fakeapikey",Type="SecureString")

        dynatrace_sink = dynatrace.DynatraceSink(mock_dt_url, mock_dt_key_parameter, token_source='ssm')

        test_log_entries = [{'content': 'test log'}]
        responses.add(responses.POST, dynatrace_sink.get_environment_url() + dynatrace.GENERIC_LOGS_INGEST_API_URL_SUFFIX,
                      body=json.dumps({'details': {'message': 'Too many requests','code': 429}}).encode(dynatrace.ENCODING), 
                      content_type="application/json",
                      status=429)

        retry_strategy = Retry(
            total = 3,
            status_forcelist = [429],
            allowed_methods =['POST'],
            raise_on_status = True,
            backoff_factor = .5
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)

        session = requests.Session()
        session.mount("https://", adapter)

        self.assertRaises(requests.exceptions.RetryError,dynatrace_sink.ingest_logs,test_log_entries,session=session)

    @responses.activate
    @patch('log.sinks.dynatrace.parameters.get_parameter', return_value='dt0s01.faketoken')
    def test_dt_tenant_header_and_bearer_auth(self, _mock_get_parameter):
        dynatrace_sink = dynatrace.DynatraceSink(mock_dt_url, mock_dt_key_parameter, token_source='ssm')
        responses.add(responses.POST, dynatrace_sink.get_environment_url() + dynatrace.GENERIC_LOGS_INGEST_API_URL_SUFFIX,
                      status=204)

        dynatrace_sink.ingest_logs([{'content': 'hello'}])

        sent = responses.calls[0].request
        self.assertEqual(sent.headers['Authorization'], 'Bearer dt0s01.faketoken')
        # Tenant ID extracted from https://test.live.dynatrace.com is "test"
        self.assertEqual(sent.headers['Dt-Tenant'], 'test')

    @responses.activate
    @patch('log.sinks.dynatrace.parameters.get_parameter', return_value='dt0s01.faketoken')
    def test_dynatrace_413_payload_too_large(self, _mock_get_parameter):
        dynatrace_sink = dynatrace.DynatraceSink(mock_dt_url, mock_dt_key_parameter, token_source='ssm')
        responses.add(responses.POST, dynatrace_sink.get_environment_url() + dynatrace.GENERIC_LOGS_INGEST_API_URL_SUFFIX,
                      body=json.dumps({'error': {'code': 413, 'message': 'Payload too large'}}).encode(dynatrace.ENCODING),
                      content_type="application/json",
                      status=413)

        self.assertRaises(dynatrace.DynatraceIngestionException,
                          dynatrace_sink.ingest_logs, [{'content': 'hello'}])


mock_dt_secret_arn = 'arn:aws:secretsmanager:us-east-1:123456789012:secret:dynatrace-s3-log-forwarder-test-api-key-AbCdEf'

class TestDynatraceSinkSecretsManager(unittest.TestCase):

    @responses.activate
    @patch('log.sinks.dynatrace.parameters.get_secret', return_value={'dt.platform_token': 'dt0s01.faketoken'})
    def test_token_fetched_from_secrets_manager(self, _mock_get_secret):
        dynatrace_sink = dynatrace.DynatraceSink(mock_dt_url, mock_dt_secret_arn,
                                                 token_source='secretsmanager')
        responses.add(responses.POST,
                      dynatrace_sink.get_environment_url() + dynatrace.GENERIC_LOGS_INGEST_API_URL_SUFFIX,
                      status=204)

        dynatrace_sink.ingest_logs([{'content': 'hello'}])

        sent = responses.calls[0].request
        self.assertEqual(sent.headers['Authorization'], 'Bearer dt0s01.faketoken')

    @responses.activate
    @patch('log.sinks.dynatrace.parameters.get_secret', return_value={'dt.platform_token': 'dt0s01.smtoken'})
    def test_load_sink_uses_secrets_manager_when_env_var_set(self, _mock_get_secret):
        os.environ['DYNATRACE_API_KEY_SECRETS_MANAGER'] = mock_dt_secret_arn
        os.environ['DYNATRACE_ENV_URL'] = mock_dt_url
        os.environ['VERIFY_DT_SSL_CERT'] = 'true'
        try:
            responses.add(responses.POST,
                          mock_dt_url + dynatrace.GENERIC_LOGS_INGEST_API_URL_SUFFIX,
                          status=204)
            sink = dynatrace.load_sink()
            self.assertEqual(sink._token_source, 'secretsmanager')
            self.assertEqual(sink._platform_token_parameter, mock_dt_secret_arn)
            sink.ingest_logs([{'content': 'hello'}])
            sent = responses.calls[0].request
            self.assertEqual(sent.headers['Authorization'], 'Bearer dt0s01.smtoken')
        finally:
            del os.environ['DYNATRACE_API_KEY_SECRETS_MANAGER']
            del os.environ['DYNATRACE_ENV_URL']
            del os.environ['VERIFY_DT_SSL_CERT']


if __name__ == '__main__':
    unittest.main()
