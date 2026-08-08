# tools/http_client.py

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def get_retry_session() -> requests.Session:
    """
    Creates a resilient HTTP session with deterministic network retry logic.
    Prevents ephemeral network glitches from triggering expensive LLM reflection loops.
    """
    
    # requests.Session(): Maintains persistent connection parameters across multiple requests, boosting performance.
    session = requests.Session()
    
    # urllib3.util.Retry: The industry-standard class defining how and when to retry failed HTTP requests.
    retry_strategy = Retry(
        total=3,                # Max 3 retry attempts before ultimately giving up
        backoff_factor=1,       # Exponential wait time between retries: 1s, 2s, 4s
        
        # status_forcelist: Triggers a retry ONLY when receiving these specific transient HTTP error codes.
        # 429: Too Many Requests | 500: Internal Server Error | 502: Bad Gateway | 503: Service Unavailable | 504: Gateway Timeout
        status_forcelist=[429, 500, 502, 503, 504], 
        
        # allowed_methods: Safe HTTP verbs that are idempotent (can be safely repeated without mutating server data).
        allowed_methods=["GET", "POST"] 
    )
    
    # HTTPAdapter: A built-in bridge allowing the 'requests' library to utilize custom 'urllib3' settings.
    adapter = HTTPAdapter(max_retries=retry_strategy)
    
    # .mount(): Binds the resilient adapter to all HTTP and HTTPS requests originating from this session.
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session