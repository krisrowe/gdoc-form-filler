"""
Google Docs API wrapper with retry logic.

Handles rate limiting with exponential backoff.
"""

import logging
import time

from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


def execute_with_retry(request, max_retries: int = 5, max_backoff: int = 64):
    """
    Execute a Google API request with exponential backoff on rate limit errors.

    Args:
        request: The API request object (call .execute() on it)
        max_retries: Maximum number of retry attempts
        max_backoff: Maximum wait time in seconds between retries

    Returns:
        The API response

    Raises:
        HttpError: If all retries are exhausted or a non-retryable error occurs
    """
    for attempt in range(max_retries + 1):
        try:
            return request.execute()
        except HttpError as e:
            if e.resp.status == 429 and attempt < max_retries:
                # Rate limit exceeded - exponential backoff starting at 1s
                wait_time = min(2 ** attempt, max_backoff)  # 1, 2, 4, 8, 16, 32, 64...
                logger.warning(
                    f"Rate limit exceeded. Waiting {wait_time}s before retry "
                    f"(attempt {attempt + 1}/{max_retries})..."
                )
                time.sleep(wait_time)
            else:
                raise


def batch_update(service, doc_id: str, requests: list) -> dict:
    """
    Execute a batchUpdate with retry logic.

    Args:
        service: Google Docs service object
        doc_id: Document ID
        requests: List of update requests

    Returns:
        The API response
    """
    return execute_with_retry(
        service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": requests}
        )
    )
