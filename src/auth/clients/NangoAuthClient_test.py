import unittest
import os
import json
from unittest.mock import patch, MagicMock
from .NangoAuthClient import NangoAuthClient

class TestNangoAuthClient(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.secret_key = "test-secret-key"
        self.host = "https://api.nango.dev"
        self.client = NangoAuthClient(secret_key=self.secret_key, host=self.host)
        
    def test_init_with_provided_values(self):
        """Test initialization with provided secret key and host."""
        client = NangoAuthClient(secret_key=self.secret_key, host=self.host)
        self.assertEqual(client.secret_key, self.secret_key)
        self.assertEqual(client.host, self.host)
        self.assertEqual(client.api_base_url, f"{self.host}/api/v1")
        
    def test_init_with_env_vars(self):
        """Test initialization with environment variables."""
        with patch.dict(os.environ, {
            "NANGO_SECRET_KEY": "env-secret-key",
            "NANGO_HOST": "https://env.nango.dev"
        }):
            client = NangoAuthClient()
            self.assertEqual(client.secret_key, "env-secret-key")
            self.assertEqual(client.host, "https://env.nango.dev")
            self.assertEqual(client.api_base_url, "https://env.nango.dev/api/v1")
            
    def test_init_without_secret_key(self):
        """Test initialization without secret key."""
        with patch.dict(os.environ, {}, clear=True):
            client = NangoAuthClient()
            self.assertIsNone(client.secret_key)
            
    @patch('requests.get')
    def test_get_user_credentials_success(self, mock_get):
        """Test successful retrieval of user credentials."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "test-token", "refresh_token": "test-refresh"}
        mock_get.return_value = mock_response
        
        # Call the method
        result = self.client.get_user_credentials("github", "user123")
        
        # Verify the result
        self.assertEqual(result, {"access_token": "test-token", "refresh_token": "test-refresh"})
        
        # Verify the request
        mock_get.assert_called_once_with(
            f"{self.host}/api/v1/connection/github/user123",
            headers={"Authorization": f"Bearer {self.secret_key}"}
        )
        
    @patch('requests.get')
    def test_get_user_credentials_not_found(self, mock_get):
        """Test when user credentials are not found."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response
        
        # Call the method
        result = self.client.get_user_credentials("github", "user123")
        
        # Verify the result
        self.assertIsNone(result)
        
    @patch('requests.get')
    def test_get_user_credentials_error(self, mock_get):
        """Test error handling when retrieving user credentials."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_get.return_value = mock_response
        
        # Call the method
        result = self.client.get_user_credentials("github", "user123")
        
        # Verify the result
        self.assertIsNone(result)
        
    @patch('requests.get')
    def test_get_user_credentials_without_secret_key(self, mock_get):
        """Test getting user credentials without a secret key."""
        # Create client without secret key
        client = NangoAuthClient()
        
        # Call the method
        result = client.get_user_credentials("github", "user123")
        
        # Verify the result
        self.assertIsNone(result)
        
        # Verify that no request was made
        mock_get.assert_not_called()
        
    @patch('requests.get')
    def test_get_oauth_config_success(self, mock_get):
        """Test successful retrieval of OAuth configuration."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "oauth_client_id": "test-client-id",
            "oauth_client_secret": "test-client-secret",
            "auth_url": "https://auth.example.com",
            "token_url": "https://token.example.com",
            "oauth_scopes": "read,write"
        }
        mock_get.return_value = mock_response
        
        # Call the method
        result = self.client.get_oauth_config("github")
        
        # Verify the result
        self.assertEqual(result["client_id"], "test-client-id")
        self.assertEqual(result["client_secret"], "test-client-secret")
        self.assertEqual(result["auth_url"], "https://auth.example.com")
        self.assertEqual(result["token_url"], "https://token.example.com")
        self.assertEqual(result["scopes"], ["read", "write"])
        
        # Verify the request
        mock_get.assert_called_once_with(
            f"{self.host}/api/v1/provider/github",
            headers={"Authorization": f"Bearer {self.secret_key}"}
        )
        
    @patch('requests.get')
    def test_get_oauth_config_error(self, mock_get):
        """Test error handling when retrieving OAuth configuration."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_get.return_value = mock_response
        
        # Call the method and expect an exception
        with self.assertRaises(ValueError):
            self.client.get_oauth_config("github")
            
    @patch('requests.get')
    def test_get_oauth_config_without_secret_key(self, mock_get):
        """Test getting OAuth configuration without a secret key."""
        # Create client without secret key
        client = NangoAuthClient()
        
        # Call the method and expect an exception
        with self.assertRaises(ValueError):
            client.get_oauth_config("github")
            
        # Verify that no request was made
        mock_get.assert_not_called()
        
    @patch('requests.put')
    def test_save_user_credentials_success(self, mock_put):
        """Test successful saving of user credentials."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_put.return_value = mock_response
        
        # Test data
        credentials = {"access_token": "test-token", "refresh_token": "test-refresh"}
        
        # Call the method
        self.client.save_user_credentials("github", "user123", credentials)
        
        # Verify the request
        mock_put.assert_called_once_with(
            f"{self.host}/api/v1/connection/github/user123",
            headers={
                "Authorization": f"Bearer {self.secret_key}",
                "Content-Type": "application/json"
            },
            json=credentials
        )
        
    @patch('requests.put')
    def test_save_user_credentials_error(self, mock_put):
        """Test error handling when saving user credentials."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_put.return_value = mock_response
        
        # Test data
        credentials = {"access_token": "test-token", "refresh_token": "test-refresh"}
        
        # Call the method
        self.client.save_user_credentials("github", "user123", credentials)
        
        # Verify the request was made
        mock_put.assert_called_once()
        
    @patch('requests.put')
    def test_save_user_credentials_without_secret_key(self, mock_put):
        """Test saving user credentials without a secret key."""
        # Create client without secret key
        client = NangoAuthClient()
        
        # Test data
        credentials = {"access_token": "test-token", "refresh_token": "test-refresh"}
        
        # Call the method
        client.save_user_credentials("github", "user123", credentials)
        
        # Verify that no request was made
        mock_put.assert_not_called()
        
    @patch('requests.put')
    def test_save_user_credentials_with_to_json_method(self, mock_put):
        """Test saving user credentials with an object that has a to_json method."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_put.return_value = mock_response
        
        # Create a mock object with to_json method
        class CredentialsObject:
            def to_json(self):
                return {"access_token": "test-token", "refresh_token": "test-refresh"}
                
        credentials = CredentialsObject()
        
        # Call the method
        self.client.save_user_credentials("github", "user123", credentials)
        
        # Verify the request
        mock_put.assert_called_once_with(
            f"{self.host}/api/v1/connection/github/user123",
            headers={
                "Authorization": f"Bearer {self.secret_key}",
                "Content-Type": "application/json"
            },
            json={"access_token": "test-token", "refresh_token": "test-refresh"}
        )

if __name__ == '__main__':
    unittest.main() 