"""
CyberArk Conjur Client for RPA Orchestration System
==================================================
Secure credential retrieval from CyberArk Conjur vault.
"""
import os
import sys
import requests
import logging
import time
from typing import Optional, Dict, Any
from pathlib import Path
import urllib.parse

# Disable SSL warnings for development (remove in production)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

class ConjurClient:
    """CyberArk Conjur client for secure credential management."""
    
    def __init__(self, 
                 conjur_url: str = "http://localhost:8080",
                 account: str = "myConjurAccount", 
                 host_id: str = "host/BotApp/myDemoApp",
                 api_key: str = None,
                 verify_ssl: bool = False):
        """
        Initialize Conjur client.
        
        Args:
            conjur_url: Conjur server URL
            account: Conjur account name
            host_id: Host identity (URL encoded)
            api_key: API key for authentication
            verify_ssl: Whether to verify SSL certificates
        """
        self.conjur_url = conjur_url.rstrip('/')
        self.account = account
        self.host_id = host_id
        self.api_key = api_key or os.getenv("CONJUR_API_KEY", "1rmxf8watvpsf1j9f72y1a482t62a6dxjr2aedrx2259sy8f11rb5wy")
        self.verify_ssl = verify_ssl
        
        # Token management
        self._token = None
        self._token_expiry = 0
        self._token_file = "/tmp/conjur_token"
        
        # Cache for secrets to reduce API calls
        self._secret_cache = {}
        self._cache_duration = 300  # 5 minutes
        
        logger.info(f"Conjur client initialized for account: {account}")
    
    def _authenticate(self) -> bool:
        """
        Authenticate with Conjur and get access token.
        
        Returns:
            bool: True if authentication successful
        """
        try:
            # URL encode the host ID for the API call
            encoded_host_id = urllib.parse.quote(self.host_id, safe='')
            auth_url = f"{self.conjur_url}/authn/{self.account}/{encoded_host_id}/authenticate"
            
            logger.debug(f"Authenticating with Conjur at: {auth_url}")
            
            response = requests.post(
                auth_url,
                data=self.api_key,
                verify=self.verify_ssl,
                timeout=10
            )
            
            if response.status_code == 200:
                self._token = response.text.strip()
                self._token_expiry = time.time() + 3600  # Token valid for 1 hour
                
                # Save token to file for debugging
                try:
                    with open(self._token_file, 'w') as f:
                        f.write(self._token)
                except Exception as e:
                    logger.warning(f"Could not save token to file: {e}")
                
                logger.info("Successfully authenticated with Conjur")
                return True
            else:
                logger.error(f"Conjur authentication failed: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during Conjur authentication: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during authentication: {e}")
            return False
    
    def _ensure_authenticated(self) -> bool:
        """
        Ensure we have a valid authentication token.
        
        Returns:
            bool: True if we have a valid token
        """
        # Check if we need to authenticate or re-authenticate
        if not self._token or time.time() >= self._token_expiry - 60:  # Refresh 1 min before expiry
            return self._authenticate()
        return True
    
    def get_secret(self, secret_path: str, use_cache: bool = True) -> Optional[str]:
        """
        Retrieve a secret from Conjur.
        
        Args:
            secret_path: Path to the secret (e.g., "BotApp/auth/jwt_secret")
            use_cache: Whether to use cached value if available
            
        Returns:
            str: Secret value or None if not found
        """
        # Check cache first
        if use_cache and secret_path in self._secret_cache:
            cached_data = self._secret_cache[secret_path]
            if time.time() - cached_data['timestamp'] < self._cache_duration:
                logger.debug(f"Using cached secret: {secret_path}")
                return cached_data['value']
        
        # Ensure we're authenticated
        if not self._ensure_authenticated():
            logger.error("Failed to authenticate with Conjur")
            return None
        
        try:
            # URL encode the secret path
            encoded_path = urllib.parse.quote(secret_path, safe='')
            secret_url = f"{self.conjur_url}/secrets/{self.account}/variable/{encoded_path}"
            
            headers = {
                "Authorization": f"Token token=\"{self._token}\""
            }
            
            logger.debug(f"Retrieving secret: {secret_path}")
            
            response = requests.get(
                secret_url,
                headers=headers,
                verify=self.verify_ssl,
                timeout=10
            )
            
            if response.status_code == 200:
                secret_value = response.text
                
                # Cache the secret
                if use_cache:
                    self._secret_cache[secret_path] = {
                        'value': secret_value,
                        'timestamp': time.time()
                    }
                
                logger.debug(f"Successfully retrieved secret: {secret_path}")
                return secret_value
            elif response.status_code == 404:
                logger.warning(f"Secret not found: {secret_path}")
                return None
            else:
                logger.error(f"Error retrieving secret {secret_path}: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error retrieving secret {secret_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error retrieving secret {secret_path}: {e}")
            return None
    
    def get_secrets_batch(self, secret_paths: list) -> Dict[str, str]:
        """
        Retrieve multiple secrets efficiently.
        
        Args:
            secret_paths: List of secret paths to retrieve
            
        Returns:
            dict: Dictionary mapping secret paths to values
        """
        results = {}
        for path in secret_paths:
            value = self.get_secret(path)
            if value is not None:
                results[path] = value
        return results
    
    def clear_cache(self):
        """Clear the secret cache."""
        self._secret_cache.clear()
        logger.info("Secret cache cleared")
    
    def health_check(self) -> bool:
        """
        Check if Conjur is accessible and authentication works.
        
        Returns:
            bool: True if healthy
        """
        try:
            return self._authenticate()
        except Exception as e:
            logger.error(f"Conjur health check failed: {e}")
            return False


# Global Conjur client instance
_conjur_client = None

def get_conjur_client() -> ConjurClient:
    """Get or create the global Conjur client instance."""
    global _conjur_client
    if _conjur_client is None:
        _conjur_client = ConjurClient()
    return _conjur_client

def get_secret_with_fallback(secret_path: str, env_var: str, default: str = None) -> str:
    """
    Get secret from Conjur with environment variable fallback.
    
    Args:
        secret_path: Conjur secret path
        env_var: Environment variable name as fallback
        default: Default value if neither source available
        
    Returns:
        str: Secret value from Conjur, environment, or default
    """
    # Try Conjur first
    try:
        client = get_conjur_client()
        secret_value = client.get_secret(secret_path)
        if secret_value is not None:
            logger.debug(f"Retrieved {secret_path} from Conjur")
            return secret_value
    except Exception as e:
        logger.warning(f"Could not retrieve {secret_path} from Conjur: {e}")
    
    # Fall back to environment variable
    env_value = os.getenv(env_var)
    if env_value is not None:
        logger.debug(f"Using environment variable {env_var}")
        return env_value
    
    # Use default
    if default is not None:
        logger.debug(f"Using default value for {secret_path}")
        return default
    
    logger.error(f"No value found for secret {secret_path}")
    raise ValueError(f"No value available for secret: {secret_path}")

# Convenience functions for specific secret categories
def get_auth_secrets() -> Dict[str, str]:
    """Get all authentication-related secrets."""
    paths = [
        "BotApp/auth/jwt_secret",
        "BotApp/auth/admin_username", 
        "BotApp/auth/admin_password"
    ]
    return get_conjur_client().get_secrets_batch(paths)

def get_provider_secrets(provider: str) -> Dict[str, str]:
    """
    Get all secrets for a specific provider.
    
    Args:
        provider: Provider name (metrofiber, openserve, octotel, evotel)
        
    Returns:
        dict: Provider secrets
    """
    base_paths = {
        'metrofiber': ['url', 'email', 'password'],
        'openserve': ['url', 'email', 'password'],
        'octotel': ['url', 'username', 'password', 'totp_secret'],
        'evotel': ['url', 'email', 'password']
    }
    
    if provider not in base_paths:
        raise ValueError(f"Unknown provider: {provider}")
    
    paths = [f"BotApp/providers/{provider}/{field}" for field in base_paths[provider]]
    return get_conjur_client().get_secrets_batch(paths)

def test_conjur_connection():
    """Test Conjur connection and print status."""
    try:
        client = get_conjur_client()
        if client.health_check():
            print("✅ Conjur connection successful")
            
            # Test retrieving a secret
            jwt_secret = client.get_secret("BotApp/auth/jwt_secret")
            if jwt_secret:
                print(f"✅ Successfully retrieved JWT secret (length: {len(jwt_secret)})")
            else:
                print("⚠️ Could not retrieve test secret")
        else:
            print("❌ Conjur connection failed")
    except Exception as e:
        print(f"❌ Conjur test failed: {e}")

if __name__ == "__main__":
    # Test the connection when run directly
    test_conjur_connection()