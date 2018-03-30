from __future__ import unicode_literals

import json
from base64 import b64encode
from datetime import datetime
from textwrap import dedent

from django.utils.timezone import utc
from mock import ANY

from anymail.exceptions import AnymailConfigurationError
from anymail.inbound import AnymailInboundMessage
from anymail.signals import AnymailInboundEvent
from anymail.webhooks.amazon_ses import AmazonSESInboundWebhookView

from .test_amazon_ses_webhooks import AmazonSESWebhookTestsMixin
from .webhook_cases import WebhookTestCase


class AmazonSESInboundTests(WebhookTestCase, AmazonSESWebhookTestsMixin):

    TEST_MIME_MESSAGE = dedent("""\
        Return-Path: <bounce-handler@mail.example.org>
        Received: from mail.example.org by inbound-smtp.us-east-1.amazonaws.com...
        MIME-Version: 1.0
        Received: by 10.1.1.1 with HTTP; Fri, 30 Mar 2018 10:21:49 -0700 (PDT)
        From: "Sender, Inc." <from@example.org>
        Date: Fri, 30 Mar 2018 10:21:50 -0700
        Message-ID: <CAEPk3RKsi@mail.example.org>
        Subject: Test inbound message
        To: Recipient <inbound@example.com>, someone-else@example.org
        Content-Type: multipart/alternative; boundary="94eb2c05e174adb140055b6339c5"

        --94eb2c05e174adb140055b6339c5
        Content-Type: text/plain; charset="UTF-8"
        Content-Transfer-Encoding: quoted-printable

        It's a body=E2=80=A6

        --94eb2c05e174adb140055b6339c5
        Content-Type: text/html; charset="UTF-8"
        Content-Transfer-Encoding: quoted-printable

        <div dir=3D"ltr">It's a body=E2=80=A6</div>

        --94eb2c05e174adb140055b6339c5--
        """).replace("\n", "\r\n")

    def test_inbound_sns_utf8(self):
        raw_ses_event = {
            "notificationType": "Received",
            "mail": {
                "timestamp": "2018-03-30T17:21:51.636Z",
                "source": "envelope-from@example.org",
                "messageId": "jili9m351il3gkburn7o2f0u6788stij94c8ld01",  # assigned by Amazon SES
                "destination": ["inbound@example.com", "someone-else@example.org"],
                "headersTruncated": False,
                "headers": [
                    # (omitting a few headers that Amazon SES adds on receipt)
                    {"name": "Return-Path", "value": "<bounce-handler@mail.example.org>"},
                    {"name": "Received", "value": "from mail.example.org by inbound-smtp.us-east-1.amazonaws.com..."},
                    {"name": "MIME-Version", "value": "1.0"},
                    {"name": "Received", "value": "by 10.1.1.1 with HTTP; Fri, 30 Mar 2018 10:21:49 -0700 (PDT)"},
                    {"name": "From", "value": '"Sender, Inc." <from@example.org>'},
                    {"name": "Date", "value": "Fri, 30 Mar 2018 10:21:50 -0700"},
                    {"name": "Message-ID", "value": "<CAEPk3RKsi@mail.example.org>"},
                    {"name": "Subject", "value": "Test inbound message"},
                    {"name": "To", "value": "Recipient <inbound@example.com>, someone-else@example.org"},
                    {"name": "Content-Type", "value": 'multipart/alternative; boundary="94eb2c05e174adb140055b6339c5"'},
                ],
                "commonHeaders": {
                    "returnPath": "bounce-handler@mail.example.org",
                    "from": ['"Sender, Inc." <from@example.org>'],
                    "date": "Fri, 30 Mar 2018 10:21:50 -0700",
                    "to": ["Recipient <inbound@example.com>", "someone-else@example.org"],
                    "messageId": "<CAEPk3RKsi@mail.example.org>",
                    "subject": "Test inbound message",
                },
            },
            "receipt": {
                "timestamp": "2018-03-30T17:21:51.636Z",
                "processingTimeMillis": 357,
                "recipients": ["inbound@example.com"],
                "spamVerdict": {"status": "PASS"},
                "virusVerdict": {"status": "PASS"},
                "spfVerdict": {"status": "PASS"},
                "dkimVerdict": {"status": "PASS"},
                "dmarcVerdict": {"status": "PASS"},
                "action": {
                    "type": "SNS",
                    "topicArn": "arn:aws:sns:us-east-1:111111111111:SES_Inbound",
                    "encoding": "UTF8",
                },
            },
            "content": self.TEST_MIME_MESSAGE,
        }

        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "8f6dee70-c885-558a-be7d-bd48bbf5335e",
            "TopicArn": "arn:aws:sns:us-east-1:111111111111:SES_Inbound",
            "Subject": "Amazon SES Email Receipt Notification",
            "Message": json.dumps(raw_ses_event),
            "Timestamp": "2018-03-30T17:17:36.516Z",
            "SignatureVersion": "1",
            "Signature": "EXAMPLE_SIGNATURE==",
            "SigningCertURL": "https://sns.us-east-1.amazonaws.com/SimpleNotificationService-12345abcde.pem",
            "UnsubscribeURL": "https://sns.us-east-1.amazonaws.com/?Action=Unsubscribe&SubscriptionArn=arn...",
        }

        response = self.post_from_sns('/anymail/amazon_ses/inbound/', raw_sns_message)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.inbound_handler, sender=AmazonSESInboundWebhookView,
                                                      event=ANY, esp_name='Amazon SES')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, 'inbound')
        self.assertEqual(event.timestamp, datetime(2018, 3, 30, 17, 21, 51, microsecond=636000, tzinfo=utc))
        self.assertEqual(event.event_id, "jili9m351il3gkburn7o2f0u6788stij94c8ld01")
        self.assertIsInstance(event.message, AnymailInboundMessage)
        self.assertEqual(event.esp_event, raw_ses_event)

        message = event.message
        self.assertIsInstance(message, AnymailInboundMessage)
        self.assertEqual(message.envelope_sender, 'envelope-from@example.org')
        self.assertEqual(message.envelope_recipient, 'inbound@example.com')
        self.assertEqual(str(message.from_email), '"Sender, Inc." <from@example.org>')
        self.assertEqual([str(to) for to in message.to],
                         ['Recipient <inbound@example.com>', 'someone-else@example.org'])
        self.assertEqual(message.subject, 'Test inbound message')
        self.assertEqual(message.text, "It's a body\N{HORIZONTAL ELLIPSIS}\r\n")
        self.assertEqual(message.html, """<div dir="ltr">It's a body\N{HORIZONTAL ELLIPSIS}</div>\r\n""")

    def test_inbound_sns_base64(self):
        """Should handle 'Base 64' content option on received email SNS action"""
        raw_ses_event = {
            # (omitting some fields that aren't used by Anymail)
            "notificationType": "Received",
            "mail": {
                "source": "envelope-from@example.org",
                "timestamp": "2018-03-30T17:21:51.636Z",
                "messageId": "jili9m351il3gkburn7o2f0u6788stij94c8ld01",  # assigned by Amazon SES
                "destination": ["inbound@example.com", "someone-else@example.org"],
            },
            "receipt": {
                "recipients": ["inbound@example.com"],
                "action": {
                    "type": "SNS",
                    "topicArn": "arn:aws:sns:us-east-1:111111111111:SES_Inbound",
                    "encoding": "BASE64",
                },
            },
            "content": b64encode(self.TEST_MIME_MESSAGE.encode('utf-8')).decode('ascii'),
        }

        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "8f6dee70-c885-558a-be7d-bd48bbf5335e",
            "TopicArn": "arn:aws:sns:us-east-1:111111111111:SES_Inbound",
            "Message": json.dumps(raw_ses_event),
        }

        response = self.post_from_sns('/anymail/amazon_ses/inbound/', raw_sns_message)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.inbound_handler, sender=AmazonSESInboundWebhookView,
                                                      event=ANY, esp_name='Amazon SES')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, 'inbound')
        self.assertEqual(event.timestamp, datetime(2018, 3, 30, 17, 21, 51, microsecond=636000, tzinfo=utc))
        self.assertEqual(event.event_id, "jili9m351il3gkburn7o2f0u6788stij94c8ld01")
        self.assertIsInstance(event.message, AnymailInboundMessage)
        self.assertEqual(event.esp_event, raw_ses_event)

        message = event.message
        self.assertIsInstance(message, AnymailInboundMessage)
        self.assertEqual(message.envelope_sender, 'envelope-from@example.org')
        self.assertEqual(message.envelope_recipient, 'inbound@example.com')
        self.assertEqual(str(message.from_email), '"Sender, Inc." <from@example.org>')
        self.assertEqual([str(to) for to in message.to],
                         ['Recipient <inbound@example.com>', 'someone-else@example.org'])
        self.assertEqual(message.subject, 'Test inbound message')
        self.assertEqual(message.text, "It's a body\N{HORIZONTAL ELLIPSIS}\r\n")
        self.assertEqual(message.html, """<div dir="ltr">It's a body\N{HORIZONTAL ELLIPSIS}</div>\r\n""")

    def test_incorrect_tracking_event(self):
        """The inbound webhook should warn if it receives tracking events"""
        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "8f6dee70-c885-558a-be7d-bd48bbf5335e",
            "TopicArn": "arn:...:111111111111:SES_Tracking",
            "Message": '{"notificationType": "Delivery"}',
        }

        with self.assertRaisesMessage(
            AnymailConfigurationError,
            "You seem to have set an Amazon SES *sending* event or notification to publish to an SNS Topic "
            "that posts to Anymail's *inbound* webhook URL. (SNS TopicArn arn:...:111111111111:SES_Tracking)"
        ):
            self.post_from_sns('/anymail/amazon_ses/inbound/', raw_sns_message)