import json
import time
import uuid
import asyncio
import aiohttp
from typing import Any, Dict, Optional
from pathlib import Path
from math import ceil

from ssage import SSAGE


class ApierClientError(Exception):
    """Exception raised for errors in the Apier client."""
    pass


class ApierClient:
    """
    Python client for APIer - communicates with GitLab CI/CD pipeline
    """

    def __init__(
        self,
        age_ci_public_key: str,
        gitlab_pipeline_endpoint: str,
        gitlab_token: str,
        gitlab_branch: str = 'main',
        max_data_size: int = 102400
    ):
        """
        Initialize Apier for communication with GitLab CI/CD pipeline
        
        Args:
            age_ci_public_key: Public key for AGE encryption
            gitlab_pipeline_endpoint: GitLab pipeline endpoint
            gitlab_token: GitLab pipeline token
            gitlab_branch: GitLab branch, default is 'main'
            max_data_size: Maximum data size for a single request, default is 100 kilobytes
        """
        self.__loaded = False
        self.__age_local: Optional[SSAGE] = None
        self.__age_ci_public_key = age_ci_public_key
        self.__pipeline_endpoint = gitlab_pipeline_endpoint
        self.__gitlab_token = gitlab_token
        self.__gitlab_branch = gitlab_branch
        self.__max_data_size = max_data_size

    async def send_request(
        self,
        path: str,
        data: Any,
        timeout: int = 300
    ) -> Any:
        """
        Send request to GitLab CI/CD pipeline
        
        Args:
            path: Virtual path to the API endpoint
            data: Data to be sent to the API endpoint
            timeout: Timeout in seconds, default is 300 seconds
            
        Returns:
            Response from the API endpoint
            
        Raises:
            ApierClientError: If there's an error in the request process
        """
        await self.__load_apier()

        request_id = self.__uuid()
        request_data = {
            'id': request_id,
            'data': data,
            'path': path,
            'age_public_key': self.__age_local.public_key
        }

        request_data_json = json.dumps(request_data)
        
        try:
            encrypted_request_data = self.__age_local.encrypt(
                request_data_json,
                additional_recipients=[self.__age_ci_public_key]
            )
        except Exception as e:
            raise ApierClientError(f"Encryption failed: {e}")

        # Split data into chunks if necessary
        data_requests = []
        max_data_size = self.__max_data_size - 100  # 100 bytes for metadata
        
        if len(encrypted_request_data) < max_data_size:
            data_requests.append(encrypted_request_data)
        else:
            parts = ceil(len(encrypted_request_data) / max_data_size)
            for i in range(parts):
                start_idx = i * max_data_size
                end_idx = (i + 1) * max_data_size
                part = encrypted_request_data[start_idx:end_idx]
                data_requests.append(f"MP_{request_id}_{i + 1}_{parts}_{part}")

        # Send all parts to the pipeline, one by one
        async with aiohttp.ClientSession() as session:
            for i, data_request in enumerate(data_requests):
                form_data = aiohttp.FormData()
                form_data.add_field('token', self.__gitlab_token)
                form_data.add_field('ref', self.__gitlab_branch)
                form_data.add_field('variables[APIER_DATA]', data_request)

                try:
                    async with session.post(
                        self.__pipeline_endpoint,
                        data=form_data
                    ) as response:
                        if not response.ok:
                            raise ApierClientError(
                                f"Failed to send request to {self.__pipeline_endpoint}: "
                                f"{response.status} {response.reason}"
                            )
                except aiohttp.ClientError as e:
                    raise ApierClientError(f"HTTP request failed: {e}")

                # Wait between requests (except for the last one)
                if i < len(data_requests) - 1:
                    await asyncio.sleep(1 + (time.time() % 1000) / 1000)

        # Wait for response
        response_url = f"apier-responses/{request_id}.txt"
        return await self.__wait_for_response(
            response_url,
            timeout,
            len(data_requests),
            self.__age_local.private_key
        )

    async def __wait_for_response(
        self,
        response_url: str,
        timeout: int,
        data_requests_count: int,
        private_key: str
    ) -> Any:
        """
        Wait for response from the API endpoint
        
        Args:
            response_url: URL to check for response
            timeout: Timeout in seconds
            data_requests_count: Number of data requests sent
            private_key: Private key for decryption
            
        Returns:
            Decrypted response data
            
        Raises:
            ApierClientError: If response times out or decryption fails
        """
        start_time = time.time()
        timeout_total = timeout * data_requests_count

        async with aiohttp.ClientSession() as session:
            while True:
                elapsed_time = time.time() - start_time
                
                if elapsed_time >= timeout_total:
                    raise ApierClientError(f"Request timeout for {response_url}")

                try:
                    async with session.get(response_url) as response:
                        if response.ok:
                            response_text = await response.text()
                            
                            try:
                                # Decrypt the response
                                decryptor = SSAGE(private_key)
                                decrypted_response_json = decryptor.decrypt(response_text)
                            except Exception as e:
                                raise ApierClientError(f"Response decryption failed: {e}")

                            try:
                                decrypted_response = json.loads(decrypted_response_json)
                            except json.JSONDecodeError as e:
                                raise ApierClientError(f"Response parsing failed: {e}")

                            if decrypted_response.get('status') != 'success':
                                raise ApierClientError(f"Server error: {decrypted_response}")

                            return decrypted_response.get('data')

                except aiohttp.ClientError:
                    # Response not ready yet, continue waiting
                    pass

                # Dynamic wait time: longer initially, shorter after initial delay
                wait_time = 15 if elapsed_time < (data_requests_count * 45) else 3.5
                await asyncio.sleep(wait_time)

    async def __load_apier(self) -> None:
        """
        Initialize AGE encryption
        """
        if self.__loaded:
            return

        # Generate a new AGE identity for this session
        self.__age_local = SSAGE()
        self.__loaded = True

    @staticmethod
    def __uuid() -> str:
        """
        Generate UUID
        
        Returns:
            UUID string
        """
        return str(uuid.uuid4())

    @classmethod
    async def auto(cls, config_path: str = 'apier/client.json') -> 'ApierClient':
        """
        Initialize Apier from well-known config file
        
        Args:
            config_path: Path to the config file
            
        Returns:
            ApierClient instance
            
        Raises:
            ApierClientError: If config file cannot be loaded or parsed
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(config_path) as response:
                    if not response.ok:
                        raise ApierClientError(f"Failed to load {config_path}")
                    
                    config = await response.json()
        except aiohttp.ClientError as e:
            raise ApierClientError(f"Failed to fetch config: {e}")
        except json.JSONDecodeError as e:
            raise ApierClientError(f"Failed to parse config JSON: {e}")

        try:
            return cls(
                age_ci_public_key=config['age_public_key'],
                gitlab_pipeline_endpoint=config['gitlab_pipeline_endpoint'],
                gitlab_token=config['gitlab_token'],
                gitlab_branch=config.get('gitlab_branch', 'main')
            )
        except KeyError as e:
            raise ApierClientError(f"Missing required config field: {e}")

    @classmethod
    def from_file(cls, config_path: Path) -> 'ApierClient':
        """
        Initialize Apier from local config file
        
        Args:
            config_path: Path to the local config file
            
        Returns:
            ApierClient instance
            
        Raises:
            ApierClientError: If config file cannot be loaded or parsed
        """
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
        except FileNotFoundError:
            raise ApierClientError(f"Config file not found: {config_path}")
        except json.JSONDecodeError as e:
            raise ApierClientError(f"Failed to parse config JSON: {e}")

        try:
            return cls(
                age_ci_public_key=config['age_public_key'],
                gitlab_pipeline_endpoint=config['gitlab_pipeline_endpoint'],
                gitlab_token=config['gitlab_token'],
                gitlab_branch=config.get('gitlab_branch', 'main')
            )
        except KeyError as e:
            raise ApierClientError(f"Missing required config field: {e}")


# Synchronous wrapper functions for convenience
class ApierClientSync:
    """
    Synchronous wrapper for ApierClient
    """
    
    def __init__(self, client: ApierClient):
        self._client = client

    def send_request(self, path: str, data: Any, timeout: int = 300) -> Any:
        """
        Send request to GitLab CI/CD pipeline (synchronous)
        
        Args:
            path: Virtual path to the API endpoint
            data: Data to be sent to the API endpoint
            timeout: Timeout in seconds, default is 300 seconds
            
        Returns:
            Response from the API endpoint
        """
        return asyncio.run(self._client.send_request(path, data, timeout))

    @classmethod
    def auto(cls, config_path: str = 'apier/client.json') -> 'ApierClientSync':
        """
        Initialize Apier from well-known config file (synchronous)
        
        Args:
            config_path: Path to the config file
            
        Returns:
            ApierClientSync instance
        """
        client = asyncio.run(ApierClient.auto(config_path))
        return cls(client)

    @classmethod
    def from_file(cls, config_path: Path) -> 'ApierClientSync':
        """
        Initialize Apier from local config file (synchronous)
        
        Args:
            config_path: Path to the local config file
            
        Returns:
            ApierClientSync instance
        """
        client = ApierClient.from_file(config_path)
        return cls(client)
