# -*- coding: utf-8 -*-
from collective.volto.formsupport.testing import (  # noqa: E501,
    VOLTO_FORMSUPPORT_API_FUNCTIONAL_TESTING,
)
from plone import api
from plone.app.testing import setRoles
from plone.app.testing import SITE_OWNER_NAME
from plone.app.testing import SITE_OWNER_PASSWORD
from plone.app.testing import TEST_USER_ID
from plone.formwidget.recaptcha.interfaces import IReCaptchaSettings
from plone.formwidget.hcaptcha.interfaces import IHCaptchaSettings
from plone.registry.interfaces import IRegistry
from plone.restapi.testing import RelativeSession
from Products.MailHost.interfaces import IMailHost
import transaction
import unittest
from unittest.mock import Mock
from unittest.mock import patch
from zope.component import getUtility


class TestCaptcha(unittest.TestCase):

    layer = VOLTO_FORMSUPPORT_API_FUNCTIONAL_TESTING

    def setUp(self):
        self.app = self.layer["app"]
        self.portal = self.layer["portal"]
        self.portal_url = self.portal.absolute_url()
        setRoles(self.portal, TEST_USER_ID, ["Manager"])

        self.mailhost = getUtility(IMailHost)

        self.registry = getUtility(IRegistry)
        self.registry["plone.email_from_address"] = "site_addr@plone.com"
        self.registry["plone.email_from_name"] = "Plone test site"

        self.api_session = RelativeSession(self.portal_url)
        self.api_session.headers.update({"Accept": "application/json"})
        self.api_session.auth = (SITE_OWNER_NAME, SITE_OWNER_PASSWORD)
        self.anon_api_session = RelativeSession(self.portal_url)
        self.anon_api_session.headers.update({"Accept": "application/json"})

        self.document = api.content.create(
            type="Document",
            title="Example context",
            container=self.portal,
        )
        self.document.blocks = {
            "text-id": {"@type": "text"},
            "form-id": {"@type": "form"},
        }
        self.document_url = self.document.absolute_url()
        transaction.commit()

    def tearDown(self):
        self.api_session.close()
        self.anon_api_session.close()

        # set default block
        self.document.blocks = {
            "text-id": {"@type": "text"},
            "form-id": {"@type": "form"},
        }
        transaction.commit()

    def submit_form(self, data):
        url = "{}/@submit-form".format(self.document_url)
        response = self.api_session.post(
            url,
            json=data,
        )
        # transaction.commit()
        return response

    def test_recaptcha_no_settings(self):
        self.document.blocks = {
            "text-id": {"@type": "text"},
            "form-id": {
                "@type": "form",
                "default_subject": "block subject",
                "default_from": "john@doe.com",
                "send": True,
                "subblocks": [
                    {
                        "field_id": "contact",
                        "field_type": "from",
                        "use_as_bcc": True,
                    },
                ],
                "captcha": "recaptcha",
            },
        }
        transaction.commit()
        response = self.submit_form(
            data={
                "data": [
                    {"label": "Message", "value": "just want to say hi"},
                ],
                "block_id": "form-id",
            },
        )
        transaction.commit()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["message"],
            "'Interface `plone.formwidget.recaptcha.interfaces.IReCaptchaSettings` "
            "defines a field `public_key`, for which there is no record.'"
        )
        self.assertEqual(
            response.json()["type"],
            "KeyError"
        )

        self.registry.registerInterface(IReCaptchaSettings)
        transaction.commit()
        response = self.submit_form(
            data={
                "data": [
                    {"label": "Message", "value": "just want to say hi"},
                ],
                "block_id": "form-id",
            },
        )
        transaction.commit()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["message"],
            "No recaptcha private key configured. Go to path/to/site/@@recaptcha-settings "
            "to configure."
        )

    def test_recaptcha(self):
        self.registry.registerInterface(IReCaptchaSettings)
        settings = self.registry.forInterface(IReCaptchaSettings)
        settings.public_key = "public"
        settings.private_key = "private"

        self.document.blocks = {
            "text-id": {"@type": "text"},
            "form-id": {
                "@type": "form",
                "default_subject": "block subject",
                "default_from": "john@doe.com",
                "send": True,
                "subblocks": [
                    {
                        "field_id": "contact",
                        "field_type": "from",
                        "use_as_bcc": True,
                    },
                ],
                "captcha": "recaptcha",
            },
        }
        transaction.commit()

        response = self.submit_form(
            data={
                "data": [
                    {"label": "Message", "value": "just want to say hi"},
                ],
                "block_id": "form-id",
            },
        )
        transaction.commit()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["message"],
            "No captcha token provided."
        )

        with patch("collective.volto.formsupport.captcha.recaptcha.submit") as mock_submit:
            mock_submit.return_value = Mock(is_valid=False)
            response = self.submit_form(
                data={
                    "data": [
                        {"label": "Message", "value": "just want to say hi"},
                    ],
                    "block_id": "form-id",
                    "captcha": {"token": "12345"},
                },
            )
            transaction.commit()
            mock_submit.assert_called_once_with('12345', 'private', '127.0.0.1')
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                response.json()["message"],
                "The code you entered was wrong, please enter the new one."
            )

        with patch("collective.volto.formsupport.captcha.recaptcha.submit") as mock_submit:
            mock_submit.return_value = Mock(is_valid=True)
            response = self.submit_form(
                data={
                    "data": [
                        {"label": "Message", "value": "just want to say hi"},
                    ],
                    "block_id": "form-id",
                    "captcha": {"token": "12345"},
                },
            )
            transaction.commit()
            mock_submit.assert_called_once_with('12345', 'private', '127.0.0.1')
            self.assertEqual(response.status_code, 204)

    def test_hcaptcha(
        self,
    ):
        self.registry.registerInterface(IHCaptchaSettings)
        settings = self.registry.forInterface(IHCaptchaSettings)
        settings.public_key = "public"
        settings.private_key = "private"

        self.document.blocks = {
            "text-id": {"@type": "text"},
            "form-id": {
                "@type": "form",
                "default_subject": "block subject",
                "default_from": "john@doe.com",
                "send": True,
                "subblocks": [
                    {
                        "field_id": "contact",
                        "field_type": "from",
                        "use_as_bcc": True,
                    },
                ],
                "captcha": "hcaptcha",
            },
        }
        transaction.commit()

        response = self.submit_form(
            data={
                "data": [
                    {"label": "Message", "value": "just want to say hi"},
                ],
                "block_id": "form-id",
            },
        )
        transaction.commit()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["message"],
            "No captcha token provided."
        )

        with patch("collective.volto.formsupport.captcha.hcaptcha.submit") as mock_submit:
            mock_submit.return_value = Mock(is_valid=False)
            response = self.submit_form(
                data={
                    "data": [
                        {"label": "Message", "value": "just want to say hi"},
                    ],
                    "block_id": "form-id",
                    "captcha": {"token": "12345"},
                },
            )
            transaction.commit()
            mock_submit.assert_called_once_with('12345', 'private', '127.0.0.1')
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                response.json()["message"],
                "The code you entered was wrong, please enter the new one."
            )

        with patch("collective.volto.formsupport.captcha.hcaptcha.submit") as mock_submit:
            mock_submit.return_value = Mock(is_valid=True)
            response = self.submit_form(
                data={
                    "data": [
                        {"label": "Message", "value": "just want to say hi"},
                    ],
                    "block_id": "form-id",
                    "captcha": {"token": "12345"},
                },
            )
            transaction.commit()
            mock_submit.assert_called_once_with('12345', 'private', '127.0.0.1')
            self.assertEqual(response.status_code, 204)