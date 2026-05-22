import os
import boto3

_cache: dict[str, str] = {}


def get_secret(name: str) -> str:
    """Fetch a SecureString parameter from SSM, cached for the container lifetime."""
    if name not in _cache:
        region = os.environ.get("AWS_REGION", "us-east-1")
        client = boto3.client("ssm", region_name=region)
        _cache[name] = client.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    return _cache[name]
