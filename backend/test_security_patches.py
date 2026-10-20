"""Targeted validation tests for security patches."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure backend directory is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from cryptography.fernet import Fernet
import app.core.config as config
from app.core.security import _validate_cors_origin, _is_admin, get_client_ip


class TestSecurityPatches(unittest.TestCase):

    def test_cipher_suite_initialization(self):
        """Verify cipher_suite is a valid Fernet instance that encrypts and decrypts."""
        self.assertIsInstance(config.cipher_suite, Fernet)
        msg = b"secret data"
        encrypted = config.cipher_suite.encrypt(msg)
        decrypted = config.cipher_suite.decrypt(encrypted)
        self.assertEqual(decrypted, msg)

    def test_invalid_configured_fernet_key_fails_fast(self):
        """Verify misconfigured FERNET_KEY raises ValueError rather than generating silently."""
        with patch.dict(os.environ, {'FERNET_KEY': 'not-a-valid-fernet-key'}):
            with self.assertRaises(ValueError):
                config._ensure_fernet_cipher()

    def test_cors_origin_prefix_bypass_blocked(self):
        """Verify prefix spoofed origins (e.g. localhost:8080.evil.com) are rejected."""
        req_attack1 = MagicMock(method='POST', headers={'Origin': 'http://localhost:8080.evil.com'})
        req_attack2 = MagicMock(method='POST', headers={'Origin': 'http://localhost:8080evil.com'})
        req_attack3 = MagicMock(method='POST', headers={'Referer': 'http://localhost:8080.attacker.com/page'})
        req_legit = MagicMock(method='POST', headers={'Origin': 'http://localhost:8080'})

        self.assertFalse(_validate_cors_origin(req_attack1))
        self.assertFalse(_validate_cors_origin(req_attack2))
        self.assertFalse(_validate_cors_origin(req_attack3))
        self.assertTrue(_validate_cors_origin(req_legit))

    def test_is_admin_rejects_unauthenticated_even_in_debug(self):
        """Verify unauthenticated requests cannot gain admin privileges via DEBUG=true."""
        with patch.dict(os.environ, {'DEBUG': 'true'}):
            req_unauth = MagicMock(headers={})
            self.assertFalse(_is_admin(req_unauth))

            req_bad_auth = MagicMock(headers={'Authorization': 'Bearer invalid.token.payload'})
            self.assertFalse(_is_admin(req_bad_auth))

    def test_get_client_ip_anti_spoofing(self):
        """Verify X-Forwarded-For is ignored unless TRUST_PROXY=true."""
        req = MagicMock(remote='192.168.1.50', headers={'X-Forwarded-For': '1.2.3.4'})
        with patch.dict(os.environ, {'TRUST_PROXY': 'false'}):
            self.assertEqual(get_client_ip(req), '192.168.1.50')

        # When proxy trust is explicitly enabled
        with patch.dict(os.environ, {'TRUST_PROXY': 'true'}):
            self.assertEqual(get_client_ip(req), '1.2.3.4')

            # Multi-hop XFF parsing
            req_multi = MagicMock(remote='192.168.1.50', headers={'X-Forwarded-For': '203.0.113.195, 70.41.3.18'})
            self.assertEqual(get_client_ip(req_multi), '203.0.113.195')


class TestFileEndpointAuthorization(unittest.IsolatedAsyncioTestCase):

    async def test_get_file_unauthenticated_rejected(self):
        """Verify get_file rejects requests with no token."""
        from app.files.handlers import get_file
        req = MagicMock(match_info={'file_id': 'test-file-123'}, headers={}, query={})
        resp = await get_file(req)
        self.assertEqual(resp.status, 401)

    async def test_get_thumbnail_unauthenticated_rejected(self):
        """Verify get_thumbnail rejects requests with no token."""
        from app.files.handlers import get_thumbnail
        req = MagicMock(match_info={'file_id': 'test-thumb-123'}, headers={}, query={})
        resp = await get_thumbnail(req)
        self.assertEqual(resp.status, 401)

    async def test_serve_upload_unauthenticated_private_file_rejected(self):
        """Verify serve_upload rejects private documents without token."""
        from app.files.handlers import serve_upload
        req = MagicMock(match_info={'filename': 'documents/confidential.pdf'}, headers={}, query={})
        resp = await serve_upload(req)
        self.assertEqual(resp.status, 401)

    async def test_serve_upload_unauthenticated_chat_thumbnail_rejected(self):
        """Verify serve_upload rejects chat image thumbnails without token."""
        from app.files.handlers import serve_upload
        req = MagicMock(match_info={'filename': 'thumbnails/chat_pic_123_thumb.jpg'}, headers={}, query={})
        resp = await serve_upload(req)
        self.assertEqual(resp.status, 401)


if __name__ == '__main__':
    unittest.main()

